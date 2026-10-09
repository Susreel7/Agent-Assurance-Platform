"""Combine local, Redis, and Postgres cancel sources for streaming runs."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from uuid import UUID

from prompt.config import Settings
from prompt.db import repository as repo
from prompt.db.postgres import connect
from prompt.domains.playground import redis_cancel
from prompt.domains.playground.cancel_registry import register

log = logging.getLogger(__name__)


class StreamCancelCoordinator:
    """Durable status lives in Postgres; Redis is a best-effort wake-up signal."""

    def __init__(
        self,
        settings: Settings,
        *,
        org_id: UUID,
        project_id: UUID,
        run_id: UUID,
    ) -> None:
        self._settings = settings
        self._org_id = org_id
        self._project_id = project_id
        self._run_id = run_id
        self._event: asyncio.Event | None = None
        self._tasks: list[asyncio.Task[None]] = []

    def cancelled(self) -> bool:
        return self._event is not None and self._event.is_set()

    async def start(self) -> None:
        self._event = await register(self._run_id)
        self._tasks.append(asyncio.create_task(self._watch_postgres()))
        if self._settings.redis_url:
            self._tasks.append(asyncio.create_task(self._watch_redis()))

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks.clear()

    async def _watch_postgres(self) -> None:
        assert self._event is not None
        interval = self._settings.playground_cancel_db_poll_seconds
        while not self._event.is_set():
            await asyncio.sleep(interval)
            try:
                with connect(self._settings.database_url) as conn:
                    row = repo.get_playground_run(
                        conn, self._org_id, self._project_id, self._run_id
                    )
                if row is None:
                    continue
                status = str(row.get("status") or "")
                if status in {"cancel_requested", "cancelled"}:
                    self._event.set()
                    return
            except Exception:  # noqa: BLE001 — reconciler must not kill stream
                log.debug("playground cancel postgres poll failed", exc_info=True)

    async def _watch_redis(self) -> None:
        assert self._event is not None
        url = self._settings.redis_url
        if not url:
            return
        from redis.asyncio import Redis

        client = Redis.from_url(url, decode_responses=True)
        pubsub = client.pubsub()
        await pubsub.subscribe(redis_cancel.cancel_channel(self._settings))
        poll = self._settings.playground_cancel_redis_poll_seconds
        key = redis_cancel.cancel_key(self._run_id)
        try:
            while not self._event.is_set():
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=poll,
                )
                if message is not None and message.get("data") == str(self._run_id):
                    self._event.set()
                    return
                if await client.get(key) is not None:
                    self._event.set()
                    return
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.debug("playground cancel redis watch failed", exc_info=True)
        finally:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(redis_cancel.cancel_channel(self._settings))
                await pubsub.aclose()  # type: ignore[attr-defined]
                await client.aclose()  # type: ignore[attr-defined]
