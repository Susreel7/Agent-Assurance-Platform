"""Bounded list pagination helpers."""

from __future__ import annotations

import base64
import json
from datetime import datetime
from typing import Any
from uuid import UUID

from evaluate.config import Settings
from evaluate.errors import ValidationError


def clamp_limit(settings: Settings, limit: int | None) -> int:
    if limit is None:
        return settings.list_default_limit
    if limit < 1:
        raise ValidationError("limit must be at least 1")
    return min(limit, settings.list_max_limit)


def encode_cursor(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), default=str).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str | None) -> dict[str, Any] | None:
    if not cursor:
        return None
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
        parsed = json.loads(raw.decode("utf-8"))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValidationError("invalid cursor") from exc
    return parsed if isinstance(parsed, dict) else None


def cursor_keyset(
    cursor: str | None,
    *,
    created_field: str = "created_at",
    id_field: str = "id",
) -> tuple[datetime | None, UUID | None]:
    data = decode_cursor(cursor)
    if not data:
        return None, None
    created_raw = data.get(created_field)
    id_raw = data.get(id_field)
    if not created_raw or not id_raw:
        raise ValidationError("cursor missing created_at or id")
    if isinstance(created_raw, str):
        created = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
    elif isinstance(created_raw, datetime):
        created = created_raw
    else:
        raise ValidationError("invalid cursor timestamp")
    return created, UUID(str(id_raw))


def next_cursor_from_row(row: dict[str, Any], *, has_more: bool) -> str | None:
    if not has_more:
        return None
    created = row.get("created_at")
    row_id = row.get("id")
    if created is None or row_id is None:
        return None
    return encode_cursor({"created_at": created.isoformat(), "id": str(row_id)})
