"""Background worker.

Polls the ``jobs`` table with ``FOR UPDATE SKIP LOCKED``. This is roughly forty lines of
SQL in place of a message broker, and it is the reason Redis and Celery are not in the
stack. At the throughput this platform needs — attestation runs, probe sweeps, pack
rendering, graph rebuilds — a broker would be operational cost with no return.

Handlers are registered in HANDLERS. Each must be idempotent, because at-least-once
delivery is the only guarantee a polling queue can offer.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import socket
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import admin_session, dispose_engine

log = logging.getLogger("aap.worker")

#: Liveness marker, refreshed once per poll cycle.
#:
#: The worker shares its image with the API but runs no HTTP server, so the image's
#: HTTP health check can never pass here and the container sat permanently unhealthy.
#: A marker file is also a better check than a port would be: it goes stale if the poll
#: loop wedges, which is the failure this process actually has.
HEARTBEAT_PATH = Path(os.environ.get("AAP_WORKER_HEARTBEAT", "/tmp/aap-worker.heartbeat"))

JobHandler = Callable[[AsyncSession, dict[str, Any]], Awaitable[None]]

HANDLERS: dict[str, JobHandler] = {
    # Registered as each milestone lands. Kept explicit so the set of things that can
    # run in the background is auditable by reading one dictionary.
    #
    # "release.diff":            M1  compute the semantic delta for a new version
    # "bom.extract":             M1  pull components out of a descriptor
    # "graph.rebuild":           M3  refresh edges for an agent
    # "materiality.adjudicate":  M6  verdict a version delta against a baseline
    # "attestation.run":         M6  re-verify an accreditation
    # "pack.render":             M5  assemble and sign an accreditation dossier
    # "probe.run":               M8  adversarial probe sweep
    # "cve.scan":                M8  dependency vulnerability scan
    # "evidence.partition":      M2  create next month's partition, drop expired
}

DEQUEUE = text("""
    UPDATE jobs SET
        locked_by = :worker,
        locked_at = now(),
        attempts  = attempts + 1
    WHERE id = (
        SELECT id FROM jobs
        WHERE completed_at IS NULL
          AND failed_at IS NULL
          AND locked_by IS NULL
          AND run_after <= now()
        ORDER BY run_after
        FOR UPDATE SKIP LOCKED
        LIMIT 1
    )
    RETURNING id, kind, payload, attempts, max_attempts, org_id
""")


class Worker:
    def __init__(self) -> None:
        self._settings = get_settings()
        self._id = f"{socket.gethostname()}:{os.getpid()}"
        self._stopping = asyncio.Event()

    def request_stop(self) -> None:
        log.info("stop requested; finishing in-flight jobs")
        self._stopping.set()

    def _beat(self) -> None:
        """Refresh the liveness marker. Never raises: a read-only or full /tmp should
        not take down a worker that is otherwise processing jobs correctly."""
        with contextlib.suppress(OSError):
            HEARTBEAT_PATH.write_text(f"{self._id} {time.time():.0f}\n")

    async def run(self) -> None:
        log.info("worker starting", extra={"id": self._id, "mode": self._settings.deployment_mode})
        slots = asyncio.Semaphore(self._settings.worker_concurrency)
        inflight: set[asyncio.Task[None]] = set()

        self._beat()

        while not self._stopping.is_set():
            await slots.acquire()
            self._beat()

            job = await self._claim()
            if job is None:
                slots.release()
                # Nothing ready. Sleep, but wake immediately on shutdown.
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=self._settings.worker_poll_seconds
                    )
                continue

            task = asyncio.create_task(self._run_job(job, slots))
            inflight.add(task)
            task.add_done_callback(inflight.discard)

        if inflight:
            log.info("draining %d in-flight jobs", len(inflight))
            await asyncio.gather(*inflight, return_exceptions=True)

        await dispose_engine()
        log.info("worker stopped")

    async def _claim(self) -> dict[str, Any] | None:
        async with admin_session() as session:
            row = (await session.execute(DEQUEUE, {"worker": self._id})).mappings().first()
            return dict(row) if row else None

    async def _run_job(self, job: dict[str, Any], slots: asyncio.Semaphore) -> None:
        kind = job["kind"]
        job_id = job["id"]
        try:
            handler = HANDLERS.get(kind)
            if handler is None:
                # Do not retry an unknown kind — it will never succeed, and retrying
                # hides the deployment mismatch that caused it.
                await self._fail(job_id, f"no handler registered for kind {kind!r}", retry=False)
                return

            async with admin_session() as session:
                await handler(session, job["payload"])

            await self._complete(job_id)
            log.info("job complete", extra={"id": job_id, "kind": kind})

        except Exception as exc:
            retry = job["attempts"] < job["max_attempts"]
            log.exception("job failed", extra={"id": job_id, "kind": kind, "retry": retry})
            await self._fail(job_id, f"{exc.__class__.__name__}: {exc}", retry=retry)
        finally:
            slots.release()

    async def _complete(self, job_id: int) -> None:
        async with admin_session() as session:
            await session.execute(
                text("UPDATE jobs SET completed_at = now(), locked_by = NULL WHERE id = :id"),
                {"id": job_id},
            )

    async def _fail(self, job_id: int, error: str, *, retry: bool) -> None:
        async with admin_session() as session:
            if retry:
                # Exponential backoff, capped so a persistently failing job still gets
                # retried occasionally rather than effectively never.
                await session.execute(
                    text("""
                        UPDATE jobs SET
                            locked_by  = NULL,
                            locked_at  = NULL,
                            last_error = :error,
                            run_after  = now()
                                + (least(power(2, attempts), 3600) * interval '1 second')
                        WHERE id = :id
                    """),
                    {"id": job_id, "error": error[:2000]},
                )
            else:
                await session.execute(
                    text("""
                        UPDATE jobs SET
                            failed_at  = now(),
                            locked_by  = NULL,
                            last_error = :error
                        WHERE id = :id
                    """),
                    {"id": job_id, "error": error[:2000]},
                )


async def main() -> None:
    logging.basicConfig(level=get_settings().log_level)
    worker = Worker()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        # Windows development: signal handlers are unavailable in the event loop.
        with contextlib.suppress(NotImplementedError):
            loop.add_signal_handler(sig, worker.request_stop)

    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
