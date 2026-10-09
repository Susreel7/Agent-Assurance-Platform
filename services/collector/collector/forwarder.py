"""Forward spooled OTLP envelopes to Observe with bounded retry."""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING

import httpx

from collector.config import Settings
from collector.spool import SpoolStore

if TYPE_CHECKING:
    from collector.metrics import CollectorMetrics

log = logging.getLogger(__name__)


class Forwarder:
    def __init__(
        self,
        settings: Settings,
        spool: SpoolStore,
        metrics: CollectorMetrics,
    ) -> None:
        self._settings = settings
        self._spool = spool
        self._metrics = metrics
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="collector-forwarder")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task

    async def _run(self) -> None:
        while not self._stop.is_set():
            self._refresh_gauges()
            digests = self._spool.list_pending_oldest_first()
            if not digests:
                try:
                    await asyncio.wait_for(
                        self._stop.wait(), timeout=self._settings.forward_poll_seconds
                    )
                except TimeoutError:
                    pass
                continue

            for digest in digests:
                if self._stop.is_set():
                    break
                await self._forward_one(digest)

    def _refresh_gauges(self) -> None:
        self._metrics.set_gauge("spool_pending", self._spool.pending_count())
        self._metrics.set_gauge("spool_quarantine", self._spool.quarantine_count())

    async def _forward_one(self, digest: str) -> None:
        meta = self._spool.claim(digest)
        if meta is None:
            return
        envelope, meta = self._spool.load_inflight(digest)
        headers = {
            "Authorization": f"Bearer {self._settings.workload_bearer_token}",
            "Content-Type": meta.content_type,
            "Content-Encoding": meta.content_encoding,
        }
        if meta.traceparent:
            headers["traceparent"] = meta.traceparent
        if meta.tracestate:
            headers["tracestate"] = meta.tracestate

        delay = self._backoff_seconds(meta.attempt_count)
        if delay > 0:
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=delay)
                return
            except TimeoutError:
                pass

        try:
            async with httpx.AsyncClient(
                timeout=self._settings.forward_http_timeout_seconds
            ) as client:
                target = (
                    self._settings.observe_logs_ingest_url
                    if meta.signal_type == "logs"
                    else self._settings.observe_ingest_url
                )
                resp = await client.post(
                    target,
                    content=envelope,
                    headers=headers,
                )
        except httpx.HTTPError as exc:
            log.warning("forward transport error digest=%s err=%s", digest[:16], exc)
            self._on_failure(digest, meta.attempt_count)
            return

        if resp.status_code // 100 == 2:
            self._spool.release_success(digest)
            self._metrics.inc("forward_success")
            return

        log.warning(
            "forward rejected digest=%s status=%s",
            digest[:16],
            resp.status_code,
        )
        self._on_failure(digest, meta.attempt_count)

    def _on_failure(self, digest: str, attempt_count: int) -> None:
        poison = attempt_count + 1 >= self._settings.poison_attempt_threshold
        updated = self._spool.release_failure(digest, poison=poison)
        self._metrics.inc("forward_failure")
        if poison:
            self._metrics.inc("forward_poisoned")
            log.error(
                "quarantined poison envelope digest=%s attempts=%s",
                digest[:16],
                updated.attempt_count,
            )

    def _backoff_seconds(self, attempt_count: int) -> float:
        base = self._settings.forward_base_delay_seconds
        cap = self._settings.forward_max_delay_seconds
        delay = min(cap, base * (2**attempt_count))
        jitter = delay * self._settings.forward_jitter_ratio
        return float(max(0.0, delay + random.uniform(-jitter, jitter)))
