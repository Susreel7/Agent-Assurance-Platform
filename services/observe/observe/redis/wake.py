"""Redis wake-up channel (not durable queue)."""

from __future__ import annotations

import logging

import redis

from observe.config import Settings

log = logging.getLogger(__name__)


def publish_ingest_wake(settings: Settings, manifest_id: str) -> None:
    if not settings.redis_url:
        return
    try:
        client = redis.from_url(settings.redis_url)
        client.publish(settings.redis_wake_channel, manifest_id)
    except Exception:  # noqa: BLE001 — wake is best-effort
        log.warning("redis wake publish failed", exc_info=True)
