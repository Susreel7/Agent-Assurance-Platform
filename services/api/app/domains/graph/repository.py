"""Graph persistence. SQL only — traversals use recursive CTEs, not ORM walks.

Edges are never hard-deleted: ``retired_at`` preserves when a relationship stopped
being true, which is what incident reviews ask after a compromise. Deleting would make
"when did this agent lose access to payments?" unanswerable from our own store.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.graph import DiscoveryFinding, GraphEdge, GraphNode


async def upsert_node(session: AsyncSession, org_id: UUID, values: dict[str, Any]) -> GraphNode:
    stmt = (
        pg_insert(GraphNode)
        .values(org_id=org_id, **values)
        .on_conflict_do_update(
            constraint="graph_nodes_key_unique",
            set_={
                "label": values["label"],
                "entity_id": values.get("entity_id"),
                "attrs": values.get("attrs", {}),
                "is_declared": values.get("is_declared", False),
                "is_observed": values.get("is_observed", False),
                "last_seen_at": func.now(),
                "retired_at": None,
            },
        )
        .returning(GraphNode)
    )
    return (await session.execute(stmt)).scalar_one()


async def upsert_edge(session: AsyncSession, org_id: UUID, values: dict[str, Any]) -> GraphEdge:
    delta = int(values.pop("observation_delta", 0))
    row = {**values}
    stmt = (
        pg_insert(GraphEdge)
        .values(org_id=org_id, **row)
        .on_conflict_do_update(
            constraint="graph_edges_unique",
            set_={
                "confidence": row.get("confidence", 1),
                "agent_version_id": row.get("agent_version_id"),
                "attrs": row.get("attrs", {}),
                "last_seen_at": func.now(),
                "retired_at": None,
                "observation_count": GraphEdge.observation_count + delta,
            },
        )
        .returning(GraphEdge)
    )
    return (await session.execute(stmt)).scalar_one()


async def retire_declared_edges_not_in(
    session: AsyncSession,
    org_id: UUID,
    agent_version_id: UUID,
    live_keys: list[tuple[UUID, UUID, str]],
) -> int:
    """Mark declared edges absent from a rebuild as retired rather than deleting them.

    Retiring instead of deleting keeps an old accreditation explainable: a pack rendered
    last quarter described these dependencies, and a graph that silently loses them
    cannot answer why it said what it said.
    """
    params: dict[str, Any] = {"org_id": str(org_id), "version_id": str(agent_version_id)}
    keep_clause = ""

    if live_keys:
        # Bound parameters rather than string interpolation: every part of a key
        # originates in an uploaded descriptor, which makes ``kind`` untrusted input
        # heading for a SQL string.
        # CAST(...) rather than ::, because text() does not bind a parameter followed by
        # a colon and would send `:src_0::uuid` as literal text. See D-021.
        rows = ", ".join(
            f"(CAST(:src_{i} AS uuid), CAST(:dst_{i} AS uuid), :kind_{i})"
            for i in range(len(live_keys))
        )
        for i, (src, dst, kind) in enumerate(live_keys):
            params[f"src_{i}"] = str(src)
            params[f"dst_{i}"] = str(dst)
            params[f"kind_{i}"] = kind
        keep_clause = f"""
           AND NOT EXISTS (
               SELECT 1 FROM (VALUES {rows}) AS live(src_id, dst_id, kind)
               WHERE live.src_id = e.src_id
                 AND live.dst_id = e.dst_id
                 AND live.kind = e.kind::text
           )
        """

    result = await session.execute(
        text(f"""
            UPDATE graph_edges e
               SET retired_at = now()
             WHERE e.org_id = :org_id
               AND e.source = 'declared'
               AND e.agent_version_id = :version_id
               AND e.retired_at IS NULL
               {keep_clause}
         RETURNING e.id
        """),
        params,
    )
    return len(result.all())


async def get_node(session: AsyncSession, org_id: UUID, node_id: UUID) -> GraphNode | None:
    stmt = select(GraphNode).where(GraphNode.id == node_id, GraphNode.org_id == org_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_node_by_key(
    session: AsyncSession, org_id: UUID, kind: str, node_key: str
) -> GraphNode | None:
    stmt = select(GraphNode).where(
        GraphNode.org_id == org_id,
        GraphNode.kind == kind,
        GraphNode.node_key == node_key,
        GraphNode.retired_at.is_(None),
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_nodes(
    session: AsyncSession,
    org_id: UUID,
    *,
    kinds: list[str] | None = None,
    include_retired: bool = False,
    limit: int = 200,
    offset: int = 0,
) -> list[GraphNode]:
    stmt = select(GraphNode).where(GraphNode.org_id == org_id)
    if kinds:
        stmt = stmt.where(GraphNode.kind.in_(kinds))
    if not include_retired:
        stmt = stmt.where(GraphNode.retired_at.is_(None))
    stmt = stmt.order_by(GraphNode.kind, GraphNode.node_key).limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars())


async def list_edges(
    session: AsyncSession,
    org_id: UUID,
    *,
    sources: list[str] | None = None,
    kinds: list[str] | None = None,
    include_retired: bool = False,
    limit: int = 500,
    offset: int = 0,
) -> list[GraphEdge]:
    stmt = select(GraphEdge).where(GraphEdge.org_id == org_id)
    if sources:
        stmt = stmt.where(GraphEdge.source.in_(sources))
    if kinds:
        stmt = stmt.where(GraphEdge.kind.in_(kinds))
    if not include_retired:
        stmt = stmt.where(GraphEdge.retired_at.is_(None))
    stmt = stmt.order_by(GraphEdge.last_seen_at.desc()).limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars())


async def fetch_neighbourhood(
    session: AsyncSession,
    org_id: UUID,
    node_id: UUID,
    *,
    depth: int,
    edge_kinds: list[str] | None = None,
) -> list[Any]:
    depth = max(1, min(depth, 4))
    kind_filter = ""
    params: dict[str, Any] = {"org_id": str(org_id), "node_id": str(node_id), "max_depth": depth}
    if edge_kinds:
        kind_filter = "AND e.kind::text = ANY(:edge_kinds)"
        params["edge_kinds"] = edge_kinds

    stmt = text(f"""
        WITH RECURSIVE walk AS (
            SELECT
                e.dst_id AS node_id,
                1 AS depth,
                e.kind::text AS via_edge_kind,
                ARRAY[e.src_id, e.dst_id] AS path
            FROM graph_edges e
            WHERE e.org_id = :org_id
              AND e.src_id = :node_id
              AND e.retired_at IS NULL
              {kind_filter}
            UNION ALL
            SELECT
                e.dst_id,
                w.depth + 1,
                e.kind::text,
                w.path || e.dst_id
            FROM graph_edges e
            JOIN walk w ON e.src_id = w.node_id
            WHERE e.org_id = :org_id
              AND e.retired_at IS NULL
              AND NOT e.dst_id = ANY(w.path)
              AND w.depth < :max_depth
              {kind_filter}
        )
        SELECT DISTINCT ON (n.id)
            n.id, n.kind::text, n.node_key, n.label, w.depth, w.via_edge_kind
        FROM walk w
        JOIN graph_nodes n ON n.id = w.node_id AND n.org_id = :org_id
        ORDER BY n.id, w.depth
    """)
    return list((await session.execute(stmt, params)).all())


async def fetch_blast_radius(
    session: AsyncSession, org_id: UUID, node_id: UUID, *, max_depth: int
) -> list[Any]:
    max_depth = max(1, min(max_depth, 8))
    stmt = text("""
        WITH RECURSIVE walk AS (
            SELECT
                e.dst_id AS node_id,
                1 AS depth,
                ARRAY[e.src_id, e.dst_id] AS path
            FROM graph_edges e
            WHERE e.org_id = :org_id
              AND e.src_id = :node_id
              AND e.retired_at IS NULL
            UNION ALL
            SELECT
                e.dst_id,
                w.depth + 1,
                w.path || e.dst_id
            FROM graph_edges e
            JOIN walk w ON e.src_id = w.node_id
            WHERE e.org_id = :org_id
              AND e.retired_at IS NULL
              AND NOT e.dst_id = ANY(w.path)
              AND w.depth < :max_depth
        )
        SELECT DISTINCT ON (n.id)
            n.id, n.kind::text, n.node_key, n.label, w.depth
        FROM walk w
        JOIN graph_nodes n ON n.id = w.node_id AND n.org_id = :org_id
        ORDER BY n.id, w.depth
    """)
    params = {"org_id": str(org_id), "node_id": str(node_id), "max_depth": max_depth}
    return list((await session.execute(stmt, params)).all())


async def fetch_reverse_reachability(
    session: AsyncSession, org_id: UUID, node_id: UUID, *, max_depth: int = 8
) -> list[Any]:
    max_depth = max(1, min(max_depth, 8))
    stmt = text("""
        WITH RECURSIVE walk AS (
            SELECT
                e.src_id AS node_id,
                1 AS depth,
                ARRAY[e.dst_id, e.src_id] AS path
            FROM graph_edges e
            WHERE e.org_id = :org_id
              AND e.dst_id = :node_id
              AND e.retired_at IS NULL
            UNION ALL
            SELECT
                e.src_id,
                w.depth + 1,
                w.path || e.src_id
            FROM graph_edges e
            JOIN walk w ON e.dst_id = w.node_id
            WHERE e.org_id = :org_id
              AND e.retired_at IS NULL
              AND NOT e.src_id = ANY(w.path)
              AND w.depth < :max_depth
        )
        SELECT DISTINCT ON (n.id)
            n.id, n.kind::text, n.node_key, n.label, w.depth
        FROM walk w
        JOIN graph_nodes n ON n.id = w.node_id AND n.org_id = :org_id
        ORDER BY n.id, w.depth
    """)
    params = {"org_id": str(org_id), "node_id": str(node_id), "max_depth": max_depth}
    return list((await session.execute(stmt, params)).all())


async def fetch_shortest_path(
    session: AsyncSession, org_id: UUID, src_id: UUID, dst_id: UUID, *, max_depth: int = 12
) -> list[Any]:
    max_depth = max(1, min(max_depth, 12))
    stmt = text("""
        WITH RECURSIVE walk AS (
            SELECT
                e.dst_id AS node_id,
                ARRAY[e.src_id, e.dst_id] AS path,
                1 AS depth
            FROM graph_edges e
            WHERE e.org_id = :org_id
              AND e.src_id = :src_id
              AND e.retired_at IS NULL
            UNION ALL
            SELECT
                e.dst_id,
                w.path || e.dst_id,
                w.depth + 1
            FROM graph_edges e
            JOIN walk w ON e.src_id = w.node_id
            WHERE e.org_id = :org_id
              AND e.retired_at IS NULL
              AND NOT e.dst_id = ANY(w.path)
              AND w.depth < :max_depth
        ),
        hit AS (
            SELECT path
            FROM walk
            WHERE node_id = :dst_id
            ORDER BY depth
            LIMIT 1
        )
        SELECT n.id, n.kind::text, n.node_key, n.label, ordinality AS hop
        FROM hit,
        unnest((SELECT path FROM hit)) WITH ORDINALITY AS u(node_id, ordinality)
        JOIN graph_nodes n ON n.id = u.node_id AND n.org_id = :org_id
        ORDER BY ordinality
    """)
    params = {
        "org_id": str(org_id),
        "src_id": str(src_id),
        "dst_id": str(dst_id),
        "max_depth": max_depth,
    }
    rows = list((await session.execute(stmt, params)).all())
    return rows


async def fetch_reconciliation(
    session: AsyncSession, org_id: UUID, *, limit: int = 500, offset: int = 0
) -> list[Any]:
    stmt = text("""
        SELECT
            src_id,
            dst_id,
            kind::text AS kind,
            declared,
            observed,
            reconciliation,
            last_seen_at,
            observation_count
        FROM graph_edge_reconciliation
        WHERE org_id = :org_id
        ORDER BY observation_count DESC, last_seen_at DESC
        LIMIT :limit OFFSET :offset
    """)
    return list(
        (
            await session.execute(stmt, {"org_id": str(org_id), "limit": limit, "offset": offset})
        ).all()
    )


async def fetch_agents_reaching(
    session: AsyncSession, org_id: UUID, *, kind: str, node_key: str, max_depth: int = 8
) -> list[Any]:
    target = await get_node_by_key(session, org_id, kind, node_key)
    if target is None:
        return []
    rows = await fetch_reverse_reachability(session, org_id, target.id, max_depth=max_depth)
    return [r for r in rows if r.kind == "agent"]


async def list_discovery_findings(
    session: AsyncSession,
    org_id: UUID,
    *,
    states: list[str] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[DiscoveryFinding]:
    stmt = select(DiscoveryFinding).where(DiscoveryFinding.org_id == org_id)
    if states:
        stmt = stmt.where(DiscoveryFinding.state.in_(states))
    stmt = (
        stmt.order_by(DiscoveryFinding.confidence.desc(), DiscoveryFinding.last_seen_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list((await session.execute(stmt)).scalars())


async def get_discovery_finding(
    session: AsyncSession, org_id: UUID, finding_id: UUID
) -> DiscoveryFinding | None:
    stmt = select(DiscoveryFinding).where(
        DiscoveryFinding.id == finding_id, DiscoveryFinding.org_id == org_id
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def update_discovery_finding(
    session: AsyncSession, org_id: UUID, finding_id: UUID, values: dict[str, Any]
) -> DiscoveryFinding | None:
    stmt = (
        update(DiscoveryFinding)
        .where(DiscoveryFinding.id == finding_id, DiscoveryFinding.org_id == org_id)
        .values(**values)
        .returning(DiscoveryFinding)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def insert_observed_edge(
    session: AsyncSession, org_id: UUID, values: dict[str, Any]
) -> GraphEdge:
    now = datetime.now(UTC)
    payload = {
        **values,
        "source": "observed",
        "first_seen_at": now,
        "last_seen_at": now,
        "observation_delta": 1,
    }
    return await upsert_edge(session, org_id, payload)
