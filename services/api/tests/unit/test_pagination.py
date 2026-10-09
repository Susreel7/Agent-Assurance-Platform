"""Keyset cursors.

These are the mechanism that keeps the audit trail readable at billions of rows, so the
properties worth pinning are the ones a page-number listing does not have: a cursor is
opaque to the client, a malformed one is rejected rather than silently treated as "start
again", and the boundary between "there is more" and "that was everything" is exact.
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException

from app.api.pagination import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    TimeCursor,
    build_page,
    decode_time_cursor,
)


def _cursor(offset_seconds: int = 0) -> TimeCursor:
    return TimeCursor(
        occurred_at=datetime(2026, 9, 18, 10, 0, tzinfo=UTC) + timedelta(seconds=offset_seconds),
        row_id=uuid.uuid4(),
    )


def test_cursor_round_trips_through_its_encoding() -> None:
    original = _cursor()
    decoded = decode_time_cursor(original.encode())
    assert decoded is not None
    assert decoded.occurred_at == original.occurred_at
    assert decoded.row_id == original.row_id


def test_cursor_survives_microsecond_precision() -> None:
    """Two events in the same millisecond must not collapse onto one cursor.

    At the volumes this table is built for, several events inside one microsecond are
    ordinary. Losing sub-second precision in the encoding would make the seek skip or
    repeat rows at every page boundary.
    """
    original = TimeCursor(
        occurred_at=datetime(2026, 9, 18, 10, 0, 0, 123_456, tzinfo=UTC),
        row_id=uuid.uuid4(),
    )
    decoded = decode_time_cursor(original.encode())
    assert decoded is not None
    assert decoded.occurred_at.microsecond == 123_456


def test_absent_cursor_means_the_first_page() -> None:
    assert decode_time_cursor(None) is None


@pytest.mark.parametrize(
    "bad",
    [
        "not-base64-at-all!!",
        base64.urlsafe_b64encode(b"missing-separator").decode().rstrip("="),
        base64.urlsafe_b64encode(b"2026-09-18T10:00:00+00:00|not-a-uuid").decode().rstrip("="),
        base64.urlsafe_b64encode(b"not-a-timestamp|" + str(uuid.uuid4()).encode())
        .decode()
        .rstrip("="),
    ],
)
def test_malformed_cursor_is_refused_not_ignored(bad: str) -> None:
    """A bad cursor is a 400, never a silent restart.

    Treating it as "no cursor" would answer a request for page nine hundred with page one,
    and the caller has no way to tell that happened.
    """
    with pytest.raises(HTTPException) as refused:
        decode_time_cursor(bad)
    assert refused.value.status_code == 400


def test_full_page_reports_more_and_trims_the_probe_row() -> None:
    """The repository fetches `page_size + 1` to learn whether more exists.

    That extra row must not reach the caller, and it is the one whose cursor is *not*
    handed out: the next page starts at the last row actually returned.
    """
    rows = [_cursor(i) for i in range(4)]
    page = build_page(rows, page_size=3, cursor_of=lambda row: row)

    assert len(page.items) == 3
    assert page.items == rows[:3]
    assert page.next_cursor == rows[2].encode()
    assert page.has_more is True


def test_partial_page_is_the_end_of_the_trail() -> None:
    rows = [_cursor(i) for i in range(2)]
    page = build_page(rows, page_size=10, cursor_of=lambda row: row)

    assert page.next_cursor is None
    assert page.has_more is False


def test_exactly_full_page_without_a_probe_row_is_also_the_end() -> None:
    """`len(rows) == page_size` means the repository found no more, so no cursor.

    Emitting one here would give the console a "load more" button that returns nothing,
    which reads as a broken page rather than as the end of the data.
    """
    rows = [_cursor(i) for i in range(3)]
    page = build_page(rows, page_size=3, cursor_of=lambda row: row)
    assert page.next_cursor is None


def test_empty_result_is_a_terminal_page() -> None:
    empty: list[TimeCursor] = []
    page = build_page(empty, page_size=DEFAULT_PAGE_SIZE, cursor_of=lambda row: row)
    assert page.items == []
    assert page.next_cursor is None


def test_page_size_has_a_ceiling() -> None:
    """Bounded so one request cannot ask for a million audit rows."""
    assert DEFAULT_PAGE_SIZE <= MAX_PAGE_SIZE
    assert MAX_PAGE_SIZE <= 1000
