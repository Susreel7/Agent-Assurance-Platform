"""Redis wake channel — not durable job storage."""

from __future__ import annotations

import logging

from evaluate.config import Settings

log = logging.getLogger(__name__)


def publish_wake(settings: Settings, *, reason: str = "job") -> None:
    if not settings.redis_enabled:
        return
    try:
        import redis
    except ImportError:
        log.debug("redis not installed; skipping wake publish")
        return
    try:
        client = redis.from_url(settings.redis_url, socket_connect_timeout=1)
        client.publish(settings.redis_wake_channel, reason)
    except Exception:  # noqa: BLE001
        log.debug("redis wake publish failed", exc_info=True)


def wait_wake(settings: Settings, timeout_seconds: float) -> bool:
    if not settings.redis_enabled:
        return False
    try:
        import redis
    except ImportError:
        return False
    try:
        client = redis.from_url(settings.redis_url, socket_connect_timeout=1)
        pubsub = client.pubsub(ignore_subscribe_messages=True)
        pubsub.subscribe(settings.redis_wake_channel)
        msg = pubsub.get_message(timeout=timeout_seconds)
        pubsub.close()
        return msg is not None
    except Exception:  # noqa: BLE001
        log.debug("redis wake wait failed", exc_info=True)
        return False
