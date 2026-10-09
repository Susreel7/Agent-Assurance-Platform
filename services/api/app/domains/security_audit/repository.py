"""SQL for the append-only audit log.

Two access shapes, and the table is indexed for exactly these:

- **Write**: many rows, one statement, no returning clause. At the volumes this platform
  targets the audit trail is the highest-insert-rate table in Postgres, so the write path
  does nothing per row.
- **Read**: newest-first keyset seek within a bounded time window, so Postgres prunes to
  a partition or two and seeks rather than scanning.

There is deliberately no update and no delete. Retention happens by dropping a monthly
partition, which is a catalogue operation rather than a bulk delete that would rewrite
the table and bloat it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.pagination import TimeCursor
from app.db.models.security_audit import SecurityAuditEvent


async def insert_events(session: AsyncSession, org_id: UUID, rows: list[dict[str, Any]]) -> int:
    """Append a batch in one statement.

    No ``RETURNING``: the caller has nothing to do with the ids, and asking for them on a
    thousand-row insert makes the database materialise a result set for no reader.
    """
    if not rows:
        return 0
    await session.execute(
        pg_insert(SecurityAuditEvent).values([{"org_id": org_id, **row} for row in rows])
    )
    return len(rows)


def _filtered(
    org_id: UUID,
    *,
    category: str | None,
    severity: str | None,
    outcome: str | None,
    actor_id: UUID | None,
    target_id: UUID | None,
    event_type: str | None,
    since: datetime | None,
    until: datetime | None,
) -> list[Any]:
    """Predicates shared by the listing and the digest, so they cannot diverge."""
    filters: list[Any] = [SecurityAuditEvent.org_id == org_id]
    if since is not None:
        filters.append(SecurityAuditEvent.occurred_at >= since)
    if until is not None:
        filters.append(SecurityAuditEvent.occurred_at < until)
    if category is not None:
        filters.append(SecurityAuditEvent.category == category)
    if severity is not None:
        filters.append(SecurityAuditEvent.severity == severity)
    if outcome is not None:
        filters.append(SecurityAuditEvent.outcome == outcome)
    if actor_id is not None:
        filters.append(SecurityAuditEvent.actor_id == actor_id)
    if target_id is not None:
        filters.append(SecurityAuditEvent.target_id == target_id)
    if event_type is not None:
        filters.append(SecurityAuditEvent.event_type == event_type)
    return filters


def _seek(statement: Select[Any], cursor: TimeCursor | None) -> Select[Any]:
    """Apply the keyset predicate for a newest-first listing.

    The tuple comparison — earlier timestamp, or same timestamp and smaller id — is what
    makes the page boundary exact. Comparing the timestamp alone would drop or repeat rows
    written in the same microsecond, which under load is most of them.
    """
    if cursor is None:
        return statement
    return statement.where(
        or_(
            SecurityAuditEvent.occurred_at < cursor.occurred_at,
            and_(
                SecurityAuditEvent.occurred_at == cursor.occurred_at,
                SecurityAuditEvent.id < cursor.row_id,
            ),
        )
    )


async def list_events(
    session: AsyncSession,
    org_id: UUID,
    *,
    limit: int,
    cursor: TimeCursor | None,
    category: str | None = None,
    severity: str | None = None,
    outcome: str | None = None,
    actor_id: UUID | None = None,
    target_id: UUID | None = None,
    event_type: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> list[SecurityAuditEvent]:
    """Fetch ``limit`` rows newest-first. The caller over-fetches by one to detect more."""
    statement = _seek(
        select(SecurityAuditEvent).where(
            *_filtered(
                org_id,
                category=category,
                severity=severity,
                outcome=outcome,
                actor_id=actor_id,
                target_id=target_id,
                event_type=event_type,
                since=since,
                until=until,
            )
        ),
        cursor,
    )
    rows = await session.execute(
        statement.order_by(
            SecurityAuditEvent.occurred_at.desc(),
            SecurityAuditEvent.id.desc(),
        ).limit(limit)
    )
    return list(rows.scalars())


async def digest(
    session: AsyncSession,
    org_id: UUID,
    *,
    since: datetime,
    until: datetime,
) -> tuple[list[tuple[str, str, int]], int, int]:
    """Grouped counts plus the two headline figures, in one round trip.

    Denied and critical totals are derived from the same grouped rows rather than issued
    as two more aggregates: the window is already scanned, so summing in Python is free
    where two more queries are not.
    """
    filters = _filtered(
        org_id,
        category=None,
        severity=None,
        outcome=None,
        actor_id=None,
        target_id=None,
        event_type=None,
        since=since,
        until=until,
    )
    rows = await session.execute(
        select(
            SecurityAuditEvent.category,
            SecurityAuditEvent.severity,
            func.count().label("event_count"),
            func.count().filter(SecurityAuditEvent.outcome == "denied").label("denied_count"),
        )
        .where(*filters)
        .group_by(SecurityAuditEvent.category, SecurityAuditEvent.severity)
        .order_by(SecurityAuditEvent.category, SecurityAuditEvent.severity)
    )

    counts: list[tuple[str, str, int]] = []
    denied = 0
    critical = 0
    for category, severity, event_count, denied_count in rows.all():
        counts.append((category, severity, int(event_count)))
        denied += int(denied_count or 0)
        if severity == "critical":
            critical += int(event_count)
    return counts, denied, critical
