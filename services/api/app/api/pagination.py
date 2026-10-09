"""Opaque keyset cursors for large tables.

``LIMIT ... OFFSET n`` makes Postgres produce and discard ``n`` rows. On a table the
size of ``security_audit_events`` that turns page 5,000 into a scan, and the cost grows
with the page number rather than the page size. Keyset pagination instead asks for "the
rows after this one", which is an index seek at any depth.

The cursor is base64url of ``"<sort key>|<uuid>"``. It is opaque on purpose: encoding it
means a client cannot hand-build one that skips the tenant predicate, and it means the
sort key can change shape later without breaking a stored bookmark. It is *not*
encrypted — it carries no secret, only a position — so this is obfuscation for coupling,
not for confidentiality.

Every cursor pairs the sort column with the row id. A timestamp alone is not a stable
key: two audit events written in the same microsecond would make one of them invisible
or duplicated depending on which side of the boundary the page fell.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException, status
from pydantic import BaseModel, Field

MAX_PAGE_SIZE = 200
DEFAULT_PAGE_SIZE = 50

_SEPARATOR = "|"


@dataclass(frozen=True, slots=True)
class TimeCursor:
    """A position in a newest-first listing."""

    occurred_at: datetime
    row_id: UUID

    def encode(self) -> str:
        raw = f"{self.occurred_at.isoformat()}{_SEPARATOR}{self.row_id}"
        return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_time_cursor(cursor: str | None) -> TimeCursor | None:
    """Decode a cursor, or 400 if it is not one we issued.

    Rejecting a malformed cursor rather than ignoring it matters: silently starting
    from the top would make a client with a corrupted bookmark re-read the whole table
    and never notice.
    """
    if cursor is None or cursor == "":
        return None

    padding = "=" * (-len(cursor) % 4)
    try:
        raw = base64.urlsafe_b64decode(cursor + padding).decode()
        timestamp, _, row_id = raw.partition(_SEPARATOR)
        if not row_id:
            raise ValueError("cursor is missing its row id")
        parsed = datetime.fromisoformat(timestamp)
        decoded = TimeCursor(
            occurred_at=parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC),
            row_id=UUID(row_id),
        )
    except (ValueError, binascii.Error, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cursor is not valid",
        ) from exc

    return decoded


class KeysetPage[ItemT](BaseModel):
    """One page, and the cursor for the next.

    No total count. Counting a partitioned append-only table to render "page 3 of 4,192"
    costs more than the page itself and the answer is stale before it is rendered. The
    console shows "more" or nothing, which is what a keyset listing can honestly say.
    """

    items: list[ItemT]
    next_cursor: str | None = None
    page_size: int = Field(ge=1, le=MAX_PAGE_SIZE)

    @property
    def has_more(self) -> bool:
        return self.next_cursor is not None


def build_page[ItemT](
    rows: list[ItemT],
    *,
    page_size: int,
    cursor_of: Callable[[ItemT], TimeCursor],
) -> KeysetPage[ItemT]:
    """Trim an over-fetched result into a page plus its next cursor.

    Callers query ``page_size + 1`` rows. The extra row is how we know there is a next
    page without a COUNT, and it is discarded rather than returned.
    """
    if len(rows) > page_size:
        page = rows[:page_size]
        return KeysetPage(
            items=page,
            next_cursor=cursor_of(page[-1]).encode(),
            page_size=page_size,
        )
    return KeysetPage(items=rows, next_cursor=None, page_size=page_size)
