"""Audit trail behaviour: append, list, aggregate.

The invariant this domain protects: **an audit event is written once and never changes.**
There is no update path and no delete path, not because one was forgotten but because a
trail that can be edited is not evidence. The database enforces it with a trigger; this
module simply has nowhere to call.

The service is intentionally thin. Everything interesting about the audit log is in its
storage shape — monthly partitions, keyset reads, a size-capped detail column — and a
service that added behaviour on top would be a place for the trail to acquire opinions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.pagination import KeysetPage, TimeCursor, build_page
from app.db.models.security_audit import SecurityAuditEvent
from app.domains.security_audit import repository as repo
from app.domains.security_audit.schemas import (
    ActorKind,
    AuditDigest,
    AuditEventOut,
    AuditQuery,
    AuditRecord,
    CategoryCount,
    Outcome,
    Severity,
)

DEFAULT_DIGEST_DAYS = 7
MAX_DIGEST_DAYS = 90
MAX_BATCH = 1000


class SecurityAuditError(Exception):
    """Base class so the router maps one exception family."""


class BatchTooLargeError(SecurityAuditError):
    """More events than one statement should carry."""


class WindowTooWideError(SecurityAuditError):
    """A digest window wider than the aggregate can serve interactively."""


def _row_to_out(row: SecurityAuditEvent) -> AuditEventOut:
    return AuditEventOut(
        id=row.id,
        occurred_at=row.occurred_at,
        event_type=row.event_type,
        category=row.category,
        severity=Severity(row.severity),
        outcome=Outcome(row.outcome),
        actor_kind=ActorKind(row.actor_kind),
        actor_id=row.actor_id,
        actor_label=row.actor_label,
        target_kind=row.target_kind,
        target_id=row.target_id,
        target_label=row.target_label,
        reason_code=row.reason_code,
        policy_digest_hex=row.policy_digest.hex() if row.policy_digest else None,
        request_id=row.request_id,
        trace_id=row.trace_id,
        source_ip=str(row.source_ip) if row.source_ip else None,
        detail=row.detail or {},
    )


def _record_to_row(record: AuditRecord) -> dict[str, Any]:
    return {
        "event_type": record.event_type,
        "category": record.category.value,
        "severity": record.severity.value,
        "outcome": record.outcome.value,
        "actor_kind": record.actor_kind.value,
        "actor_id": record.actor_id,
        "actor_label": record.actor_label,
        "target_kind": record.target_kind,
        "target_id": record.target_id,
        "target_label": record.target_label,
        "reason_code": record.reason_code,
        "policy_digest": (
            bytes.fromhex(record.policy_digest_hex) if record.policy_digest_hex else None
        ),
        "request_id": record.request_id,
        "trace_id": record.trace_id,
        "source_ip": record.source_ip,
        "detail": record.detail,
    }


async def record(session: AsyncSession, org_id: UUID, event: AuditRecord) -> None:
    """Append one event.

    Returns nothing. There is no id worth handing back — the caller cannot amend the row
    it just wrote, and offering an identifier would imply otherwise.
    """
    await repo.insert_events(session, org_id, [_record_to_row(event)])


async def record_many(session: AsyncSession, org_id: UUID, events: list[AuditRecord]) -> int:
    """Append a batch in one statement.

    Bounded at ``MAX_BATCH``. Unbounded batches turn one slow producer into a transaction
    long enough to hold up every other writer on the table.
    """
    if len(events) > MAX_BATCH:
        raise BatchTooLargeError(f"{len(events)} events exceeds the {MAX_BATCH} limit")
    return await repo.insert_events(session, org_id, [_record_to_row(event) for event in events])


async def list_events(
    session: AsyncSession,
    org_id: UUID,
    query: AuditQuery,
    *,
    page_size: int,
    cursor: TimeCursor | None,
) -> KeysetPage[AuditEventOut]:
    """A newest-first page.

    Over-fetches one row so the page can report whether there is a next one without a
    COUNT — the count on a partitioned table of this size costs more than the page.
    """
    rows = await repo.list_events(
        session,
        org_id,
        limit=page_size + 1,
        cursor=cursor,
        category=query.category.value if query.category else None,
        severity=query.severity.value if query.severity else None,
        outcome=query.outcome.value if query.outcome else None,
        actor_id=query.actor_id,
        target_id=query.target_id,
        event_type=query.event_type,
        since=query.since,
        until=query.until,
    )
    return build_page(
        [_row_to_out(row) for row in rows],
        page_size=page_size,
        cursor_of=lambda item: TimeCursor(occurred_at=item.occurred_at, row_id=item.id),
    )


async def digest(
    session: AsyncSession,
    org_id: UUID,
    *,
    days: int = DEFAULT_DIGEST_DAYS,
) -> AuditDigest:
    """Counts by category and severity over a bounded window.

    The window cap is the point. This aggregate is computed live so it is always current,
    which is only affordable because the range prunes to a partition or two; "all time"
    would scan the whole trail on every render of the security overview.
    """
    if days > MAX_DIGEST_DAYS:
        raise WindowTooWideError(f"{days} days exceeds the {MAX_DIGEST_DAYS} day limit")

    until = datetime.now(UTC)
    since = until - timedelta(days=days)
    counts, denied, critical = await repo.digest(session, org_id, since=since, until=until)
    return AuditDigest(
        since=since,
        until=until,
        counts=[
            CategoryCount(
                category=category,
                severity=Severity(severity),
                event_count=event_count,
            )
            for category, severity, event_count in counts
        ],
        denied_count=denied,
        critical_count=critical,
    )


__all__ = [
    "BatchTooLargeError",
    "SecurityAuditError",
    "WindowTooWideError",
    "digest",
    "list_events",
    "record",
    "record_many",
]
