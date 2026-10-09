"""In-process cancel tokens for streaming playground runs."""

from __future__ import annotations

import asyncio
from uuid import UUID

_lock = asyncio.Lock()
_tokens: dict[UUID, asyncio.Event] = {}


async def register(run_id: UUID) -> asyncio.Event:
    async with _lock:
        existing = _tokens.get(run_id)
        if existing is not None:
            return existing
        event = asyncio.Event()
        _tokens[run_id] = event
        return event


async def cancel(run_id: UUID) -> bool:
    async with _lock:
        event = _tokens.get(run_id)
    if event is None:
        return False
    event.set()
    return True


async def drop(run_id: UUID) -> None:
    async with _lock:
        _tokens.pop(run_id, None)
