"""The audit trail against real Postgres.

Three claims that only a real server can settle: the trigger actually refuses a rewrite,
rows land in a month partition rather than the default one, and paging a large trail by
cursor returns every row exactly once. The last is the one most likely to be quietly wrong
— an off-by-one in a seek predicate duplicates or skips a row at each page boundary, and a
page of audit events looks entirely plausible either way.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.pagination import TimeCursor, decode_time_cursor
from app.domains.security_audit import service
from app.domains.security_audit.schemas import (
    ActorKind,
    AuditQuery,
    AuditRecord,
    Category,
    Outcome,
    Severity,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _record(
    index: int,
    *,
    category: Category = Category.MCP,
    outcome: Outcome = Outcome.DENIED,
    severity: Severity = Severity.INFO,
) -> AuditRecord:
    return AuditRecord(
        event_type="mcp.tool_call.denied",
        category=category,
        severity=severity,
        outcome=outcome,
        actor_kind=ActorKind.AGENT,
        actor_label=f"agent:triage-{index}",
        detail={"sequence": index},
    )


async def _fill(session: AsyncSession, org_id: uuid.UUID, count: int) -> None:
    await service.record_many(session, org_id, [_record(i) for i in range(count)])
    await session.flush()


# ---- append-only ----------------------------------------------------------------------


async def test_every_category_the_api_can_produce_is_accepted(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """The category list lives in both the schema and a CHECK constraint.

    A category the API emits and the constraint rejects fails only for the events carrying
    it, so the trail looks healthy while one subsystem's history silently never lands.
    """
    for category in Category:
        await service.record(session, org_id, _record(0, category=category))
    await session.flush()

    page = await service.list_events(session, org_id, AuditQuery(), page_size=100, cursor=None)
    assert {event.category for event in page.items} == {c.value for c in Category}


async def test_an_audit_event_cannot_be_amended(session: AsyncSession, org_id: uuid.UUID) -> None:
    """The guarantee the whole table exists for.

    There is no service path that would try this, which is why the test goes around the
    service: what is being checked is that the database refuses, not that the code declines
    to ask.
    """
    await service.record(session, org_id, _record(0))
    await session.flush()

    with pytest.raises(Exception, match="append-only"):
        await session.execute(
            text("UPDATE security_audit_events SET outcome = 'allowed' WHERE org_id = :org"),
            {"org": org_id},
        )
        await session.flush()


async def test_an_audit_event_cannot_be_deleted(session: AsyncSession, org_id: uuid.UUID) -> None:
    """Retention is a partition drop, not a DELETE. A row-level delete would also be the
    obvious way to remove the one event somebody did not want seen."""
    await service.record(session, org_id, _record(0))
    await session.flush()

    with pytest.raises(Exception, match="append-only"):
        await session.execute(
            text("DELETE FROM security_audit_events WHERE org_id = :org"),
            {"org": org_id},
        )
        await session.flush()


async def test_events_land_in_a_month_partition(session: AsyncSession, org_id: uuid.UUID) -> None:
    """The default partition is a safety net, not a destination.

    Rows accumulating there mean the partition maintenance job has stopped, and the symptom
    otherwise appears months later as a table that cannot be pruned.
    """
    await service.record(session, org_id, _record(0))
    await session.flush()

    partition = await session.scalar(
        text(
            "SELECT tableoid::regclass::text FROM security_audit_events WHERE org_id = :org LIMIT 1"
        ),
        {"org": org_id},
    )
    assert partition is not None
    assert partition not in ("security_audit_events", "security_audit_events_default")


# ---- keyset pagination ----------------------------------------------------------------


async def test_paging_the_whole_trail_returns_every_row_exactly_once(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """The property an `OFFSET` listing does not have either.

    Written as a full walk rather than a two-page check because the failure mode is one row
    at a boundary, and with three rows per page a boundary bug shows up as a duplicate or a
    hole somewhere in the middle.
    """
    total = 25
    await _fill(session, org_id, total)

    seen: list[uuid.UUID] = []
    cursor: TimeCursor | None = None
    for _ in range(total):  # A generous bound; the loop breaks on the terminal page.
        page = await service.list_events(session, org_id, AuditQuery(), page_size=4, cursor=cursor)
        seen.extend(event.id for event in page.items)
        if page.next_cursor is None:
            break
        cursor = decode_time_cursor(page.next_cursor)
    else:
        pytest.fail("paging did not terminate")

    assert len(seen) == total
    assert len(set(seen)) == total


async def test_pages_come_back_newest_first(session: AsyncSession, org_id: uuid.UUID) -> None:
    """The order the console reads in, and the order the index is built for."""
    await _fill(session, org_id, 10)

    page = await service.list_events(session, org_id, AuditQuery(), page_size=10, cursor=None)
    timestamps = [event.occurred_at for event in page.items]
    assert timestamps == sorted(timestamps, reverse=True)


async def test_rows_written_in_the_same_transaction_still_page_apart(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """A bulk insert gives every row the same `now()`.

    That is the case a timestamp-only cursor cannot page through — it either loops on the
    first row forever or skips the rest of the tied group. The id tiebreaker is what makes
    it work, and a batch write is how it happens in production.
    """
    await _fill(session, org_id, 12)

    distinct = await session.scalar(
        text("SELECT count(DISTINCT occurred_at) FROM security_audit_events WHERE org_id = :org"),
        {"org": org_id},
    )
    assert distinct == 1, "the premise of this test is that the timestamps tie"

    seen: list[uuid.UUID] = []
    cursor: TimeCursor | None = None
    while True:
        page = await service.list_events(session, org_id, AuditQuery(), page_size=5, cursor=cursor)
        assert page.items, "a page inside a tied group came back empty"
        seen.extend(event.id for event in page.items)
        if page.next_cursor is None:
            break
        cursor = decode_time_cursor(page.next_cursor)

    assert len(set(seen)) == 12


async def test_the_final_page_reports_no_cursor(session: AsyncSession, org_id: uuid.UUID) -> None:
    """Otherwise the console shows a "load more" that returns nothing, which reads as a
    broken page rather than as the end of the trail."""
    await _fill(session, org_id, 3)

    page = await service.list_events(session, org_id, AuditQuery(), page_size=10, cursor=None)
    assert len(page.items) == 3
    assert page.next_cursor is None
    assert page.has_more is False


async def test_an_empty_trail_pages_without_error(session: AsyncSession, org_id: uuid.UUID) -> None:
    page = await service.list_events(session, org_id, AuditQuery(), page_size=10, cursor=None)
    assert page.items == []
    assert page.next_cursor is None


# ---- filters --------------------------------------------------------------------------


async def test_filters_narrow_without_losing_the_cursor(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """A filter and a cursor have to compose: the console applies both at once.

    If the seek predicate ignores the filter, page two of a filtered view starts from an
    unfiltered position and silently drops rows.
    """
    await service.record_many(
        session,
        org_id,
        [_record(i, category=Category.MCP) for i in range(6)]
        + [_record(i, category=Category.ACCESS) for i in range(6)],
    )
    await session.flush()

    seen: list[str] = []
    cursor: TimeCursor | None = None
    while True:
        page = await service.list_events(
            session,
            org_id,
            AuditQuery(category=Category.ACCESS),
            page_size=2,
            cursor=cursor,
        )
        seen.extend(event.category for event in page.items)
        if page.next_cursor is None:
            break
        cursor = decode_time_cursor(page.next_cursor)

    assert seen == [Category.ACCESS.value] * 6


async def test_a_denied_filter_finds_the_denials(session: AsyncSession, org_id: uuid.UUID) -> None:
    """The partial index this filter uses is the one the security overview depends on."""
    await service.record_many(
        session,
        org_id,
        [_record(0, outcome=Outcome.ALLOWED), _record(1, outcome=Outcome.DENIED)],
    )
    await session.flush()

    page = await service.list_events(
        session, org_id, AuditQuery(outcome=Outcome.DENIED), page_size=10, cursor=None
    )
    assert [event.outcome for event in page.items] == [Outcome.DENIED]


async def test_a_time_window_excludes_what_falls_outside_it(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    await _fill(session, org_id, 4)

    future = datetime.now(UTC) + timedelta(hours=1)
    page = await service.list_events(
        session, org_id, AuditQuery(since=future), page_size=10, cursor=None
    )
    assert page.items == []


# ---- aggregate and limits -------------------------------------------------------------


async def test_the_digest_counts_by_category_and_severity(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    await service.record_many(
        session,
        org_id,
        [
            _record(0, category=Category.MCP, severity=Severity.CRITICAL),
            _record(1, category=Category.MCP, severity=Severity.CRITICAL),
            _record(2, category=Category.ACCESS, severity=Severity.INFO),
            _record(3, category=Category.ACCESS, outcome=Outcome.ALLOWED),
        ],
    )
    await session.flush()

    digest = await service.digest(session, org_id, days=1)

    assert digest.critical_count == 2
    assert digest.denied_count == 3
    counted = {(row.category, row.severity): row.event_count for row in digest.counts}
    assert counted[(Category.MCP.value, Severity.CRITICAL)] == 2


async def test_a_digest_window_wider_than_the_cap_is_refused(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """The aggregate is computed live, which is only affordable because the window prunes
    to a partition or two. "All time" would scan the whole trail on every page render."""
    with pytest.raises(service.WindowTooWideError):
        await service.digest(session, org_id, days=service.MAX_DIGEST_DAYS + 1)


async def test_an_oversized_batch_is_refused(session: AsyncSession, org_id: uuid.UUID) -> None:
    """One slow producer must not be able to hold a transaction long enough to block every
    other writer on the hottest table in the system."""
    with pytest.raises(service.BatchTooLargeError):
        await service.record_many(
            session, org_id, [_record(i) for i in range(service.MAX_BATCH + 1)]
        )


# ---- tenancy --------------------------------------------------------------------------


async def test_one_account_never_sees_another_accounts_trail(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    """The audit log is the most sensitive table here, and the one an unscoped listing
    would be least likely to be noticed on."""
    await _fill(session, org_id, 5)

    page = await service.list_events(session, other_org_id, AuditQuery(), page_size=10, cursor=None)
    assert page.items == []

    digest = await service.digest(session, other_org_id, days=1)
    assert digest.denied_count == 0
