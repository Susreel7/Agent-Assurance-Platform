"""Evidence persistence. SQL only — no business logic, no HTTP concerns.

Every function takes ``org_id`` explicitly. Row-level security already scopes the
connection, but an explicit predicate means a misconfigured policy degrades to returning
nothing rather than to returning everything.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.evidence import EvidenceBatch, EvidenceCheckpoint, EvidenceEvent

# ----------------------------------------------------------------------
# Events — write
# ----------------------------------------------------------------------


async def insert_events(
    session: AsyncSession, org_id: UUID, rows: list[dict[str, Any]]
) -> list[UUID]:
    """Bulk insert. Returns the new ids in submission order.

    One statement rather than a loop: a reconnecting collector commonly delivers
    thousands of buffered events, and a round trip per row turns a routine catch-up
    into an outage.
    """
    if not rows:
        return []

    stmt = (
        insert(EvidenceEvent)
        .values([{**r, "org_id": org_id} for r in rows])
        .returning(EvidenceEvent.id)
    )
    return list((await session.execute(stmt)).scalars())


async def anchor_events(
    session: AsyncSession,
    org_id: UUID,
    batch_id: UUID,
    assignments: list[tuple[UUID, datetime, int]],
) -> int:
    """Stamp ``batch_id`` and ``leaf_index`` onto sealed events.

    The only permitted mutation of an evidence row, and the ``evidence_events_append_only``
    trigger allows it exactly once. ``occurred_at`` is in the predicate because it is
    part of the primary key and lets Postgres prune to a single partition per row.

    Executed as one statement built from a VALUES list, because a batch can hold
    thousands of events and this runs inside the sealing transaction.
    """
    if not assignments:
        return 0

    # CAST(:p AS t) rather than :p::t. SQLAlchemy's text() ignores a bind parameter that
    # is followed immediately by another colon, so it can leave PostgreSQL's :: cast
    # operator alone — which means `:id_0::uuid` binds nothing and reaches the server as
    # literal text. Sealing then failed with a syntax error at ":" the first time it ran
    # against a real database. See D-021.
    values_sql = ", ".join(
        f"(CAST(:id_{i} AS uuid), CAST(:ts_{i} AS timestamptz), CAST(:ix_{i} AS integer))"
        for i in range(len(assignments))
    )
    params: dict[str, Any] = {"batch_id": str(batch_id), "org_id": str(org_id)}
    for i, (event_id, occurred_at, leaf_index) in enumerate(assignments):
        params[f"id_{i}"] = str(event_id)
        params[f"ts_{i}"] = occurred_at
        params[f"ix_{i}"] = leaf_index

    result = await session.execute(
        text(
            f"""
            UPDATE evidence_events e
               SET batch_id = :batch_id, leaf_index = v.leaf_index
              FROM (VALUES {values_sql}) AS v(id, occurred_at, leaf_index)
             WHERE e.id = v.id
               AND e.occurred_at = v.occurred_at
               AND e.org_id = :org_id
               AND e.batch_id IS NULL
         RETURNING e.id
            """
        ),
        params,
    )
    return len(result.all())


# ----------------------------------------------------------------------
# Events — read
# ----------------------------------------------------------------------


def _event_filters(
    stmt: Select[Any],
    org_id: UUID,
    *,
    kinds: list[str] | None,
    agent_id: UUID | None,
    engagement_id: UUID | None,
    customer_id: UUID | None,
    outcomes: list[str] | None,
    region: str | None,
    data_class: str | None,
    since: datetime | None,
    until: datetime | None,
    unsealed_only: bool,
) -> Select[Any]:
    """Shared predicate builder so the page query and its count cannot diverge.

    The one place in this repository where a helper is worth the indirection: two
    hand-maintained copies of nine filters would eventually disagree, and a total that
    contradicts the rows below it reads as data loss.
    """
    stmt = stmt.where(EvidenceEvent.org_id == org_id)

    if kinds:
        stmt = stmt.where(EvidenceEvent.kind.in_(kinds))
    if agent_id is not None:
        stmt = stmt.where(EvidenceEvent.agent_id == agent_id)
    if engagement_id is not None:
        stmt = stmt.where(EvidenceEvent.engagement_id == engagement_id)
    if customer_id is not None:
        stmt = stmt.where(EvidenceEvent.customer_id == customer_id)
    if outcomes:
        stmt = stmt.where(EvidenceEvent.outcome.in_(outcomes))
    if region:
        stmt = stmt.where(EvidenceEvent.region == region)
    if data_class:
        # Array containment, which the GIN index on data_classes serves.
        stmt = stmt.where(EvidenceEvent.data_classes.contains([data_class]))
    if since is not None:
        stmt = stmt.where(EvidenceEvent.occurred_at >= since)
    if until is not None:
        stmt = stmt.where(EvidenceEvent.occurred_at < until)
    if unsealed_only:
        stmt = stmt.where(EvidenceEvent.batch_id.is_(None))

    return stmt


async def list_events(
    session: AsyncSession,
    org_id: UUID,
    *,
    kinds: list[str] | None = None,
    agent_id: UUID | None = None,
    engagement_id: UUID | None = None,
    customer_id: UUID | None = None,
    outcomes: list[str] | None = None,
    region: str | None = None,
    data_class: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    unsealed_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[EvidenceEvent]:
    stmt = _event_filters(
        select(EvidenceEvent),
        org_id,
        kinds=kinds,
        agent_id=agent_id,
        engagement_id=engagement_id,
        customer_id=customer_id,
        outcomes=outcomes,
        region=region,
        data_class=data_class,
        since=since,
        until=until,
        unsealed_only=unsealed_only,
    )
    stmt = (
        stmt.order_by(EvidenceEvent.occurred_at.desc(), EvidenceEvent.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list((await session.execute(stmt)).scalars())


async def count_events(
    session: AsyncSession,
    org_id: UUID,
    *,
    kinds: list[str] | None = None,
    agent_id: UUID | None = None,
    engagement_id: UUID | None = None,
    customer_id: UUID | None = None,
    outcomes: list[str] | None = None,
    region: str | None = None,
    data_class: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    unsealed_only: bool = False,
) -> int:
    stmt = _event_filters(
        select(func.count()).select_from(EvidenceEvent),
        org_id,
        kinds=kinds,
        agent_id=agent_id,
        engagement_id=engagement_id,
        customer_id=customer_id,
        outcomes=outcomes,
        region=region,
        data_class=data_class,
        since=since,
        until=until,
        unsealed_only=unsealed_only,
    )
    return int((await session.execute(stmt)).scalar_one())


async def get_event(
    session: AsyncSession,
    org_id: UUID,
    event_id: UUID,
    occurred_at: datetime | None = None,
) -> EvidenceEvent | None:
    """Fetch one event.

    ``occurred_at`` is optional but wanted: supplying it lets Postgres prune to one
    partition instead of scanning every month the install retains.
    """
    stmt = select(EvidenceEvent).where(EvidenceEvent.id == event_id, EvidenceEvent.org_id == org_id)
    if occurred_at is not None:
        stmt = stmt.where(EvidenceEvent.occurred_at == occurred_at)
    return (await session.execute(stmt)).scalars().first()


async def fetch_unsealed(
    session: AsyncSession, org_id: UUID, *, until: datetime, limit: int
) -> list[EvidenceEvent]:
    """Events awaiting a batch, in the order they will become leaves.

    Leaf order is ``(occurred_at, id)`` and that ordering is part of the frozen
    contract: a proof built against a different order recomputes a different root.
    """
    stmt = (
        select(EvidenceEvent)
        .where(
            EvidenceEvent.org_id == org_id,
            EvidenceEvent.batch_id.is_(None),
            EvidenceEvent.occurred_at < until,
        )
        .order_by(EvidenceEvent.occurred_at, EvidenceEvent.id)
        .limit(limit)
    )
    return list((await session.execute(stmt)).scalars())


async def fetch_batch_leaves(
    session: AsyncSession, org_id: UUID, batch_id: UUID
) -> list[tuple[int, UUID, str]]:
    """``(leaf_index, event_id, content_digest)`` for a sealed batch, in leaf order.

    Used to re-derive a root during verification and to build inclusion proofs.
    """
    stmt = (
        select(
            EvidenceEvent.leaf_index,
            EvidenceEvent.id,
            EvidenceEvent.content_digest,
        )
        .where(EvidenceEvent.org_id == org_id, EvidenceEvent.batch_id == batch_id)
        .order_by(EvidenceEvent.leaf_index)
    )
    rows = (await session.execute(stmt)).all()
    # leaf_index is non-null for any event carrying a batch_id, enforced by the
    # evidence_events_anchor_consistent constraint.
    return [(int(r[0]), r[1], r[2]) for r in rows]


async def fetch_kind_counts(
    session: AsyncSession, org_id: UUID, *, since: datetime | None = None
) -> dict[str, int]:
    """Facet counts for the evidence explorer."""
    stmt = (
        select(EvidenceEvent.kind, func.count())
        .where(EvidenceEvent.org_id == org_id)
        .group_by(EvidenceEvent.kind)
    )
    if since is not None:
        stmt = stmt.where(EvidenceEvent.occurred_at >= since)
    return {row[0]: row[1] for row in (await session.execute(stmt)).all()}


# ----------------------------------------------------------------------
# Batches
# ----------------------------------------------------------------------


async def insert_batch(
    session: AsyncSession, org_id: UUID, values: dict[str, Any]
) -> EvidenceBatch:
    stmt = insert(EvidenceBatch).values(org_id=org_id, **values).returning(EvidenceBatch)
    return (await session.execute(stmt)).scalar_one()


async def get_last_batch(session: AsyncSession, org_id: UUID) -> EvidenceBatch | None:
    """The chain head.

    ``FOR UPDATE`` because two sealers racing here would both read the same head and
    both claim the next sequence number, and the unique constraint on ``(org_id, seq)``
    would turn that into a failed job rather than a corrupted chain — but a failed job
    every cycle is still an outage.
    """
    stmt = (
        select(EvidenceBatch)
        .where(EvidenceBatch.org_id == org_id)
        .order_by(EvidenceBatch.seq.desc())
        .limit(1)
        .with_for_update()
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_batch(session: AsyncSession, org_id: UUID, batch_id: UUID) -> EvidenceBatch | None:
    stmt = select(EvidenceBatch).where(EvidenceBatch.id == batch_id, EvidenceBatch.org_id == org_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_batches(
    session: AsyncSession,
    org_id: UUID,
    *,
    from_seq: int | None = None,
    limit: int = 100,
    offset: int = 0,
    ascending: bool = False,
) -> list[EvidenceBatch]:
    stmt = select(EvidenceBatch).where(EvidenceBatch.org_id == org_id)
    if from_seq is not None:
        stmt = stmt.where(EvidenceBatch.seq >= from_seq)
    order = EvidenceBatch.seq.asc() if ascending else EvidenceBatch.seq.desc()
    stmt = stmt.order_by(order).limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars())


async def count_batches(session: AsyncSession, org_id: UUID) -> int:
    stmt = select(func.count()).select_from(EvidenceBatch).where(EvidenceBatch.org_id == org_id)
    return (await session.execute(stmt)).scalar_one()


# No update function for batches. The signature is written inside the sealing
# transaction, before the row exists, because evidence_batches is immutable. Key
# rotation produces a new checkpoint rather than a re-signature — re-signing would
# change what an auditor has already verified.


# ----------------------------------------------------------------------
# Checkpoints
# ----------------------------------------------------------------------


async def insert_checkpoint(
    session: AsyncSession, org_id: UUID, values: dict[str, Any]
) -> EvidenceCheckpoint:
    stmt = insert(EvidenceCheckpoint).values(org_id=org_id, **values).returning(EvidenceCheckpoint)
    return (await session.execute(stmt)).scalar_one()


async def list_checkpoints(
    session: AsyncSession,
    org_id: UUID,
    *,
    published_to: str | None = None,
    limit: int = 50,
) -> list[EvidenceCheckpoint]:
    stmt = select(EvidenceCheckpoint).where(EvidenceCheckpoint.org_id == org_id)
    if published_to:
        stmt = stmt.where(EvidenceCheckpoint.published_to == published_to)
    stmt = stmt.order_by(EvidenceCheckpoint.published_at.desc()).limit(limit)
    return list((await session.execute(stmt)).scalars())


async def get_latest_checkpoint(
    session: AsyncSession, org_id: UUID, published_to: str
) -> EvidenceCheckpoint | None:
    stmt = (
        select(EvidenceCheckpoint)
        .where(
            EvidenceCheckpoint.org_id == org_id,
            EvidenceCheckpoint.published_to == published_to,
        )
        .order_by(EvidenceCheckpoint.tree_size.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


# ----------------------------------------------------------------------
# Partition maintenance
# ----------------------------------------------------------------------


async def ensure_partition(session: AsyncSession, month: datetime) -> str:
    """Create next month's partition if it does not exist.

    Calls the SQL function from migration 0003 rather than reimplementing it: the
    function also drains rows the default partition caught, and doing that from Python
    would need the maintenance session flag set from application code.
    """
    result = await session.execute(
        text("SELECT ensure_evidence_partition(:month)"), {"month": month.date()}
    )
    return str(result.scalar_one())


async def update_events_anchored_stat(session: AsyncSession, org_id: UUID) -> int:
    """Count of accepted-but-unsealed events.

    Not a fault on its own — the sealer runs on a cadence — but a number that keeps
    climbing means the worker has stopped, and that is worth surfacing before an
    auditor notices the gap.
    """
    stmt = (
        select(func.count())
        .select_from(EvidenceEvent)
        .where(EvidenceEvent.org_id == org_id, EvidenceEvent.batch_id.is_(None))
    )
    return (await session.execute(stmt)).scalar_one()
