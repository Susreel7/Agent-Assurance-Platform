"""SQL for MCP servers, snapshots, capabilities, grants and usage rollups.

``decide_tool_call`` is the query the gateway runs before every tool invocation. It is
written as a single statement joining the grant to the capability within the pinned or
approved snapshot, because the alternative — fetch grants, fetch capabilities, intersect
in Python — is three round trips on the hottest path in the product.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.access import Team
from app.db.models.mcp_registry import (
    McpCapability,
    McpCapabilityUsageDaily,
    McpGrant,
    McpServer,
    McpSnapshot,
)


async def insert_server(session: AsyncSession, org_id: UUID, row: dict[str, Any]) -> McpServer:
    server = McpServer(org_id=org_id, **row)
    session.add(server)
    await session.flush()
    return server


async def get_server(session: AsyncSession, org_id: UUID, server_id: UUID) -> McpServer | None:
    result = await session.execute(
        select(McpServer).where(McpServer.org_id == org_id, McpServer.id == server_id)
    )
    return result.scalar_one_or_none()


async def get_server_by_slug(session: AsyncSession, org_id: UUID, slug: str) -> McpServer | None:
    result = await session.execute(
        select(McpServer).where(
            McpServer.org_id == org_id,
            func.lower(McpServer.slug) == slug.lower(),
        )
    )
    return result.scalar_one_or_none()


async def update_server(
    session: AsyncSession,
    org_id: UUID,
    server_id: UUID,
    values: dict[str, Any],
) -> McpServer | None:
    result = await session.execute(
        update(McpServer)
        .where(McpServer.org_id == org_id, McpServer.id == server_id)
        .values(**values, updated_at=func.now())
        .returning(McpServer)
    )
    return result.scalar_one_or_none()


async def lock_server(session: AsyncSession, org_id: UUID, server_id: UUID) -> McpServer | None:
    """Row-lock for snapshot submission and approval.

    Submitting a snapshot reads the approved digest, compares, and may flip the health to
    ``drift``. Two discovery runs racing there would produce a server whose health does
    not match either snapshot.
    """
    result = await session.execute(
        select(McpServer)
        .where(McpServer.org_id == org_id, McpServer.id == server_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def list_servers(
    session: AsyncSession,
    org_id: UUID,
    *,
    limit: int,
    offset: int,
    state: str | None = None,
    trust_tier: str | None = None,
    server_id: UUID | None = None,
    since: date | None = None,
) -> tuple[list[tuple[McpServer, str | None, int, int, int, int, int]], int]:
    """Servers with owner, capability counts, grant count and a 7-day usage window.

    ``server_id`` narrows the same statement to one row, so the detail page and the list
    page compute their counts identically instead of drifting apart over time.
    """
    # Each of these is a correlated scalar subquery against the outer McpServer row, so
    # the whole page is one statement. Written as separate SELECTs it would be four more
    # round trips per page, and a per-row count would be N+1.
    tool_count = (
        select(func.count())
        .select_from(McpCapability)
        .where(
            McpCapability.org_id == McpServer.org_id,
            McpCapability.snapshot_id == McpServer.approved_snapshot_id,
        )
        .scalar_subquery()
    )

    dangerous_count = (
        select(func.count())
        .select_from(McpCapability)
        .where(
            McpCapability.org_id == McpServer.org_id,
            McpCapability.snapshot_id == McpServer.approved_snapshot_id,
            or_(
                McpCapability.verified_irreversible.is_(True),
                McpCapability.verified_risk.in_(("high", "critical")),
            ),
        )
        .scalar_subquery()
    )

    grant_count = (
        select(func.count())
        .select_from(McpGrant)
        .where(
            McpGrant.org_id == McpServer.org_id,
            McpGrant.server_id == McpServer.id,
            McpGrant.revoked_at.is_(None),
        )
        .scalar_subquery()
    )

    usage_filters = [
        McpCapabilityUsageDaily.org_id == McpServer.org_id,
        McpCapabilityUsageDaily.server_id == McpServer.id,
    ]
    if since is not None:
        usage_filters.append(McpCapabilityUsageDaily.usage_date >= since)

    calls = (
        select(func.sum(McpCapabilityUsageDaily.call_count)).where(*usage_filters).scalar_subquery()
    )
    denials = (
        select(func.sum(McpCapabilityUsageDaily.denied_count))
        .where(*usage_filters)
        .scalar_subquery()
    )

    filters = [McpServer.org_id == org_id, McpServer.state != "retired"]
    if state is not None:
        filters = [McpServer.org_id == org_id, McpServer.state == state]
    if trust_tier is not None:
        filters.append(McpServer.trust_tier == trust_tier)
    if server_id is not None:
        # A retired server still has a detail page; its history is the reason to keep one.
        filters = [McpServer.org_id == org_id, McpServer.id == server_id]

    total = await session.scalar(
        select(func.count()).select_from(select(McpServer).where(*filters).subquery())
    )

    rows = await session.execute(
        select(
            McpServer,
            Team.name,
            tool_count,
            grant_count,
            dangerous_count,
            calls,
            denials,
        )
        .outerjoin(
            Team,
            and_(Team.org_id == McpServer.org_id, Team.id == McpServer.owner_team_id),
        )
        .where(*filters)
        .order_by(McpServer.name, McpServer.id)
        .limit(limit)
        .offset(offset)
    )

    return [
        (
            server,
            team_name,
            int(tools or 0),
            int(grants or 0),
            int(dangerous or 0),
            int(call_total or 0),
            int(denial_total or 0),
        )
        for server, team_name, tools, grants, dangerous, call_total, denial_total in rows.all()
    ], int(total or 0)


async def find_snapshot_by_digest(
    session: AsyncSession,
    org_id: UUID,
    server_id: UUID,
    digest: bytes,
) -> McpSnapshot | None:
    result = await session.execute(
        select(McpSnapshot).where(
            McpSnapshot.org_id == org_id,
            McpSnapshot.server_id == server_id,
            McpSnapshot.capability_digest == digest,
        )
    )
    return result.scalar_one_or_none()


async def get_snapshot(
    session: AsyncSession,
    org_id: UUID,
    snapshot_id: UUID,
) -> McpSnapshot | None:
    result = await session.execute(
        select(McpSnapshot).where(McpSnapshot.org_id == org_id, McpSnapshot.id == snapshot_id)
    )
    return result.scalar_one_or_none()


async def insert_snapshot(
    session: AsyncSession,
    org_id: UUID,
    row: dict[str, Any],
) -> McpSnapshot:
    snapshot = McpSnapshot(org_id=org_id, **row)
    session.add(snapshot)
    await session.flush()
    return snapshot


async def touch_snapshot_discovery(
    session: AsyncSession,
    org_id: UUID,
    snapshot_id: UUID,
) -> McpSnapshot:
    """Re-discovering an unchanged server updates the timestamp, not the row set.

    This is what keeps ``mcp_snapshots`` bounded under continuous discovery: a server
    polled every five minutes for a year produces one row, not a hundred thousand.
    ``discovered_at`` is not in the trigger's immutable column list, so this is allowed.
    """
    result = await session.execute(
        update(McpSnapshot)
        .where(McpSnapshot.org_id == org_id, McpSnapshot.id == snapshot_id)
        .values(discovered_at=func.now())
        .returning(McpSnapshot)
    )
    return result.scalar_one()


async def approve_snapshot(
    session: AsyncSession,
    org_id: UUID,
    snapshot_id: UUID,
    *,
    approved_by: str,
) -> McpSnapshot | None:
    """Stamp an approval, and only if there is not one already.

    The ``approved_at IS NULL`` predicate matters because the trigger refuses to move an
    existing approval: without it a second approve would raise a database exception rather
    than returning a clean conflict.
    """
    result = await session.execute(
        update(McpSnapshot)
        .where(
            McpSnapshot.org_id == org_id,
            McpSnapshot.id == snapshot_id,
            McpSnapshot.approved_at.is_(None),
        )
        .values(approved_at=func.now(), approved_by=approved_by)
        .returning(McpSnapshot)
    )
    return result.scalar_one_or_none()


async def supersede_snapshot(session: AsyncSession, org_id: UUID, snapshot_id: UUID) -> None:
    """Mark a previously approved snapshot as no longer the current approval.

    The row stays. A grant pinned to it must keep resolving, and the approval it carries
    is the evidence that someone reviewed those capabilities on that date.
    ``superseded_at`` is outside the immutability trigger's column list for this reason.
    """
    await session.execute(
        update(McpSnapshot)
        .where(
            McpSnapshot.org_id == org_id,
            McpSnapshot.id == snapshot_id,
            McpSnapshot.superseded_at.is_(None),
        )
        .values(superseded_at=func.now())
    )


async def insert_capabilities(
    session: AsyncSession,
    org_id: UUID,
    rows: list[dict[str, Any]],
) -> int:
    """Bulk insert a snapshot's capabilities.

    One statement for up to 4,096 rows. A server with a thousand tools is not unusual and
    per-row inserts would make discovery a visible pause.
    """
    if not rows:
        return 0
    await session.execute(
        pg_insert(McpCapability).values([{"org_id": org_id, **row} for row in rows])
    )
    return len(rows)


async def list_capabilities(
    session: AsyncSession,
    org_id: UUID,
    snapshot_id: UUID,
) -> list[McpCapability]:
    rows = await session.execute(
        select(McpCapability)
        .where(McpCapability.org_id == org_id, McpCapability.snapshot_id == snapshot_id)
        .order_by(McpCapability.kind, McpCapability.name)
    )
    return list(rows.scalars())


async def get_capability(
    session: AsyncSession,
    org_id: UUID,
    capability_id: UUID,
) -> McpCapability | None:
    result = await session.execute(
        select(McpCapability).where(
            McpCapability.org_id == org_id,
            McpCapability.id == capability_id,
        )
    )
    return result.scalar_one_or_none()


async def review_capability(
    session: AsyncSession,
    org_id: UUID,
    capability_id: UUID,
    values: dict[str, Any],
) -> McpCapability | None:
    result = await session.execute(
        update(McpCapability)
        .where(McpCapability.org_id == org_id, McpCapability.id == capability_id)
        .values(**values, reviewed_at=func.now())
        .returning(McpCapability)
    )
    return result.scalar_one_or_none()


async def insert_grant(session: AsyncSession, org_id: UUID, row: dict[str, Any]) -> McpGrant:
    grant = McpGrant(org_id=org_id, **row)
    session.add(grant)
    await session.flush()
    return grant


async def list_grants(
    session: AsyncSession,
    org_id: UUID,
    server_id: UUID,
) -> list[McpGrant]:
    rows = await session.execute(
        select(McpGrant)
        .where(
            McpGrant.org_id == org_id,
            McpGrant.server_id == server_id,
            McpGrant.revoked_at.is_(None),
        )
        .order_by(McpGrant.created_at.desc())
    )
    return list(rows.scalars())


async def revoke_grant(session: AsyncSession, org_id: UUID, grant_id: UUID) -> bool:
    result = await session.execute(
        update(McpGrant)
        .where(
            McpGrant.org_id == org_id,
            McpGrant.id == grant_id,
            McpGrant.revoked_at.is_(None),
        )
        .values(revoked_at=func.now())
        .returning(McpGrant.id)
    )
    return result.scalar_one_or_none() is not None


async def decide_tool_call(
    session: AsyncSession,
    org_id: UUID,
    *,
    server_slug: str,
    capability_name: str,
    subjects: list[tuple[str, UUID]],
    environment: str,
    now: datetime,
) -> tuple[McpServer | None, McpCapability | None, McpGrant | None]:
    """Resolve one tool call to its server, capability and governing grant.

        Three joins, one statement. The gateway calls this before every tool invocation, so
    the shape matters more here than anywhere else in the codebase:

        - The server is matched by slug, which is what a client config actually contains.
        - The capability is read from the grant's *pinned* snapshot when it has one, and from
          the server's approved snapshot otherwise. That is the whole point of pinning: a
          server that adds a tool after approval does not thereby grant it.
        - A grant naming the capability wins over a whole-server grant, because the narrower
          grant may carry a different approval requirement.

        Returning three optionals rather than a boolean lets the caller distinguish "no such
    server", "not in the approved snapshot" and "no grant" — three denials that need three
        different messages.
    """
    server = await get_server_by_slug(session, org_id, server_slug)
    if server is None:
        return None, None, None

    if not subjects:
        return server, None, None

    subject_predicate = or_(
        *[
            and_(McpGrant.subject_kind == kind, McpGrant.subject_id == subject_id)
            for kind, subject_id in subjects
        ]
    )

    rows = await session.execute(
        select(McpGrant, McpCapability)
        .outerjoin(
            McpCapability,
            and_(
                McpCapability.org_id == McpGrant.org_id,
                McpCapability.server_id == McpGrant.server_id,
                McpCapability.name == capability_name,
                McpCapability.snapshot_id
                == func.coalesce(McpGrant.pinned_snapshot_id, server.approved_snapshot_id),
            ),
        )
        .where(
            McpGrant.org_id == org_id,
            McpGrant.server_id == server.id,
            McpGrant.revoked_at.is_(None),
            or_(McpGrant.expires_at.is_(None), McpGrant.expires_at > now),
            # `@> ARRAY[env]`, the codebase's form for array membership. Unindexed, and
            # deliberately so: the predicates above already narrow this to one server's
            # live grants, and a GIN index on a column this small would cost more on every
            # grant write than it saves here.
            McpGrant.environments.contains([environment]),
            or_(
                McpGrant.capability_name == capability_name,
                McpGrant.capability_name.is_(None),
            ),
            subject_predicate,
        )
        # A capability-specific grant sorts before a whole-server one.
        .order_by(McpGrant.capability_name.is_(None))
        .limit(1)
    )

    found = rows.first()
    if found is None:
        return server, None, None

    grant, capability = found
    return server, capability, grant


async def upsert_usage(
    session: AsyncSession,
    org_id: UUID,
    rows: list[dict[str, Any]],
) -> int:
    """Merge daily usage aggregates.

    Counts are *added* rather than replaced, because the worker delivers a window at a
        time and a re-delivered window must not double-count nor reset. ``p95_latency_ms``
        takes the larger of the two: a percentile cannot be summed, and the worse figure is
        the safer one to show a reviewer.
    """
    if not rows:
        return 0

    statement = pg_insert(McpCapabilityUsageDaily).values(
        [{"org_id": org_id, **row} for row in rows]
    )
    await session.execute(
        statement.on_conflict_do_update(
            index_elements=[
                McpCapabilityUsageDaily.org_id,
                McpCapabilityUsageDaily.usage_date,
                McpCapabilityUsageDaily.server_id,
                McpCapabilityUsageDaily.capability_name,
                McpCapabilityUsageDaily.agent_id,
                McpCapabilityUsageDaily.member_id,
            ],
            set_={
                "call_count": McpCapabilityUsageDaily.call_count + statement.excluded.call_count,
                "denied_count": McpCapabilityUsageDaily.denied_count
                + statement.excluded.denied_count,
                "approval_count": McpCapabilityUsageDaily.approval_count
                + statement.excluded.approval_count,
                "error_count": McpCapabilityUsageDaily.error_count + statement.excluded.error_count,
                "p95_latency_ms": func.greatest(
                    McpCapabilityUsageDaily.p95_latency_ms,
                    statement.excluded.p95_latency_ms,
                ),
                "cost_micros": McpCapabilityUsageDaily.cost_micros + statement.excluded.cost_micros,
                "updated_at": func.now(),
            },
        )
    )
    return len(rows)


async def usage_for_server(
    session: AsyncSession,
    org_id: UUID,
    server_id: UUID,
    *,
    since: date,
) -> list[McpCapabilityUsageDaily]:
    rows = await session.execute(
        select(McpCapabilityUsageDaily)
        .where(
            McpCapabilityUsageDaily.org_id == org_id,
            McpCapabilityUsageDaily.server_id == server_id,
            McpCapabilityUsageDaily.usage_date >= since,
        )
        .order_by(
            McpCapabilityUsageDaily.usage_date.desc(),
            McpCapabilityUsageDaily.call_count.desc(),
        )
    )
    return list(rows.scalars())
