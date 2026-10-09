"""Keyset list helpers with totals."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from evaluate.api.pagination import (
    clamp_limit,
    cursor_keyset,
    decode_cursor,
    encode_cursor,
    next_cursor_from_row,
)
from evaluate.config import Settings


def keyset_page(
    settings: Settings,
    *,
    limit: int | None,
    cursor: str | None,
    count: Callable[[], int],
    fetch: Callable[..., list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], int, int, str | None]:
    page_size = clamp_limit(settings, limit)
    created_at, row_id = cursor_keyset(cursor)
    rows = fetch(limit=page_size + 1, cursor_created_at=created_at, cursor_id=row_id)
    has_more = len(rows) > page_size
    page = rows[:page_size]
    next_cursor = next_cursor_from_row(page[-1], has_more=has_more) if page and has_more else None
    return page, count(), page_size, next_cursor


def example_keyset_page(
    settings: Settings,
    *,
    limit: int | None,
    cursor: str | None,
    count: Callable[[], int],
    fetch: Callable[..., list[dict[str, Any]]],
) -> tuple[list[dict[str, Any]], int, int, str | None]:
    page_size = clamp_limit(settings, limit)
    data = decode_cursor(cursor)
    ordinal: int | None = None
    row_id: UUID | None = None
    if data:
        if "ordinal" not in data or "id" not in data:
            from evaluate.errors import ValidationError

            raise ValidationError("invalid cursor")
        ordinal = int(data["ordinal"])
        row_id = UUID(str(data["id"]))
    rows = fetch(limit=page_size + 1, cursor_ordinal=ordinal, cursor_id=row_id)
    has_more = len(rows) > page_size
    page = rows[:page_size]
    next_cursor: str | None = None
    if page and has_more:
        last = page[-1]
        next_cursor = encode_cursor({"ordinal": last["ordinal"], "id": str(last["id"])})
    return page, count(), page_size, next_cursor
