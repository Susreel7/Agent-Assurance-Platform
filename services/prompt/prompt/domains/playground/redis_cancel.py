"""Ephemeral Redis cancel signals for multi-instance playground streaming."""

from __future__ import annotations

import logging
from uuid import UUID

from prompt.config import Settings

log = logging.getLogger(__name__)


def cancel_channel(settings: Settings) -> str:
    return settings.redis_cancel_channel


def cancel_key(run_id: UUID) -> str:
    return f"prompt:playground:cancel:{run_id}"


async def publish_cancel(settings: Settings, run_id: UUID) -> bool:
    """Publish cancel signal; returns False when Redis is not configured."""
    if not settings.redis_url:
        return False
    try:
        from redis.asyncio import Redis
    except ImportError as exc:
        log.warning("redis package missing; cannot publish playground cancel")
        raise RuntimeError("redis package required when PROMPT_REDIS_URL is set") from exc

    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        ttl = settings.redis_cancel_signal_ttl_seconds
        await client.set(cancel_key(run_id), "1", ex=ttl)
        await client.publish(cancel_channel(settings), str(run_id))
    finally:
        await client.aclose()  # type: ignore[attr-defined]
    return True


async def signal_present(settings: Settings, run_id: UUID) -> bool:
    if not settings.redis_url:
        return False
    from redis.asyncio import Redis

    client = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        val = await client.get(cancel_key(run_id))
        return val is not None
    finally:
        await client.aclose()  # type: ignore[attr-defined]
