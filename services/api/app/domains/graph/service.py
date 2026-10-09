"""Graph business logic — rebuild, traversals, reconciliation and discovery."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.graph import repository as repo
from app.domains.graph.schemas import (
    BlastRadius,
    BlastRadiusNode,
    DiscoveryFindingOut,
    DiscoveryFindingResolve,
    GraphEdgeKind,
    GraphEdgeOut,
    GraphNodeKind,
    GraphNodeOut,
    GraphSource,
    Neighbourhood,
    NeighbourhoodNode,
    PathHop,
    PathResult,
    ReconciliationRow,
    ReconciliationSummary,
)


@dataclass(frozen=True, slots=True)
class DeclaredNode:
    kind: str
    node_key: str
    label: str
    entity_id: UUID | None = None
    attrs: Mapping[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class DeclaredEdge:
    src_key: str
    dst_key: str
    kind: str


class GraphError(Exception):
    """Base for everything this module raises."""


class GraphNodeNotFoundError(GraphError):
    def __init__(self, node_id: UUID) -> None:
        super().__init__(f"graph node {node_id} not found")
        self.node_id = node_id


class DiscoveryFindingNotFoundError(GraphError):
    def __init__(self, finding_id: UUID) -> None:
        super().__init__(f"discovery finding {finding_id} not found")
        self.finding_id = finding_id


class DiscoveryResolveError(GraphError):
    pass


def _model_node_key(model: dict[str, Any]) -> str:
    provider = str(model.get("provider", "unknown"))
    family = str(model.get("family", "unknown"))
    ident = str(model.get("id") or model.get("family") or "unknown")
    return f"{provider}/{family}/{ident}"


def derive_declared_graph(
    agent_id: UUID,
    agent_urn: str,
    agent_label: str,
    descriptor: dict[str, Any],
) -> tuple[list[DeclaredNode], list[DeclaredEdge]]:
    """Pure derivation of declared nodes and edges from an AAP descriptor.

    Natural keys match migration 0004 so telemetry and descriptors converge on the
    same rows across rebuilds.
    """
    nodes: dict[tuple[str, str], DeclaredNode] = {}
    edges: list[DeclaredEdge] = []

    def add_node(kind: str, key: str, label: str, **attrs: Any) -> None:
        nodes[(kind, key)] = DeclaredNode(
            kind=kind,
            node_key=key,
            label=label,
            entity_id=agent_id if kind == GraphNodeKind.AGENT.value and key == agent_urn else None,
            attrs=attrs or None,
        )

    add_node(GraphNodeKind.AGENT.value, agent_urn, agent_label, agent_id=str(agent_id))

    for model in descriptor.get("models") or []:
        if not isinstance(model, dict):
            continue
        key = _model_node_key(model)
        add_node(GraphNodeKind.MODEL.value, key, key)
        edges.append(DeclaredEdge(agent_urn, key, GraphEdgeKind.USES_MODEL.value))

    for prompt in descriptor.get("prompts") or []:
        if not isinstance(prompt, dict) or not prompt.get("name"):
            continue
        name = str(prompt["name"])
        add_node(GraphNodeKind.PROMPT.value, name, name)
        edges.append(DeclaredEdge(agent_urn, name, GraphEdgeKind.USES_PROMPT.value))

    for tool in descriptor.get("tools") or []:
        if not isinstance(tool, dict) or not tool.get("name"):
            continue
        name = str(tool["name"])
        kind_raw = str(tool.get("kind", "tool"))
        key = f"{kind_raw}:{name}"
        add_node(GraphNodeKind.TOOL.value, key, name)
        edge_kind = GraphEdgeKind.INVOKES_TOOL.value
        edges.append(DeclaredEdge(agent_urn, key, edge_kind))

    for server in (descriptor.get("references") or {}).get("mcp_servers") or []:
        if not isinstance(server, dict) or not server.get("url"):
            continue
        url = str(server["url"])
        add_node(GraphNodeKind.MCP_SERVER.value, url, url)
        edges.append(DeclaredEdge(agent_urn, url, GraphEdgeKind.CONNECTS_MCP.value))

    data = descriptor.get("data") or {}
    for cls in data.get("classes") or []:
        label = str(cls)
        add_node(GraphNodeKind.DATA_CLASS.value, label, label)
        edges.append(DeclaredEdge(agent_urn, label, GraphEdgeKind.READS_DATA.value))

    for source in data.get("sources") or []:
        if not isinstance(source, dict) or not source.get("name"):
            continue
        name = str(source["name"])
        add_node(GraphNodeKind.DATA_SOURCE.value, name, name, region=source.get("region"))
        effect = str(source.get("effect", "read")).lower()
        if effect == "write":
            kind = GraphEdgeKind.WRITES_DATA.value
        else:
            kind = GraphEdgeKind.READS_DATA.value
        edges.append(DeclaredEdge(agent_urn, name, kind))
        region = source.get("region")
        if region:
            region_key = str(region)
            add_node(GraphNodeKind.REGION.value, region_key, region_key)
            edges.append(DeclaredEdge(name, region_key, GraphEdgeKind.PROCESSES_IN.value))

    residency = data.get("residency") or {}
    for region in residency.get("permitted_regions") or []:
        region_key = str(region)
        add_node(GraphNodeKind.REGION.value, region_key, region_key)
        edges.append(DeclaredEdge(agent_urn, region_key, GraphEdgeKind.DEPLOYED_IN.value))

    for delegate in descriptor.get("delegates_to") or []:
        if not isinstance(delegate, dict) or not delegate.get("urn"):
            continue
        urn = str(delegate["urn"])
        add_node(GraphNodeKind.AGENT.value, urn, urn)
        edges.append(DeclaredEdge(agent_urn, urn, GraphEdgeKind.DELEGATES_TO.value))

    accountability = descriptor.get("accountability") or {}
    team = accountability.get("owning_team")
    if team:
        team_key = str(team)
        add_node(GraphNodeKind.TEAM.value, team_key, team_key)
        edges.append(DeclaredEdge(agent_urn, team_key, GraphEdgeKind.OWNED_BY.value))

    person = accountability.get("accountable_person")
    if person:
        person_key = str(person)
        add_node(GraphNodeKind.PERSON.value, person_key, person_key)
        edges.append(DeclaredEdge(agent_urn, person_key, GraphEdgeKind.ACCOUNTABLE_FOR.value))

    for defence in (descriptor.get("security") or {}).get("prompt_injection_defences") or []:
        key = str(defence)
        add_node(GraphNodeKind.GUARDRAIL.value, key, key)
        edges.append(DeclaredEdge(agent_urn, key, GraphEdgeKind.GUARDED_BY.value))

    return list(nodes.values()), edges


class ReconciliationRecord(Protocol):
    """Shape of one row from ``repository.fetch_reconciliation``.

    Declared structurally so the classification below can be exercised with plain
    objects rather than only against a live query result.
    """

    src_id: UUID
    dst_id: UUID
    kind: str
    declared: bool
    observed: bool
    reconciliation: str
    last_seen_at: datetime | None
    observation_count: int


def summarise_reconciliation(rows: Iterable[ReconciliationRecord]) -> ReconciliationSummary:
    """Classify declared/observed gaps — the product signal security reviewers buy."""
    confirmed = 0
    declared_not_observed = 0
    observed_not_declared = 0
    out_rows: list[ReconciliationRow] = []

    for row in rows:
        status = str(getattr(row, "reconciliation", ""))
        if status == "confirmed":
            confirmed += 1
        elif status == "declared_not_observed":
            declared_not_observed += 1
        elif status == "observed_not_declared":
            observed_not_declared += 1
        out_rows.append(
            ReconciliationRow(
                src_id=row.src_id,
                dst_id=row.dst_id,
                kind=GraphEdgeKind(row.kind),
                declared=bool(row.declared),
                observed=bool(row.observed),
                reconciliation=status,
                last_seen_at=row.last_seen_at,
                observation_count=int(getattr(row, "observation_count", 0)),
            )
        )

    return ReconciliationSummary(
        confirmed=confirmed,
        declared_not_observed=declared_not_observed,
        observed_not_declared=observed_not_declared,
        rows=out_rows,
    )


async def rebuild_from_version(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
    version_id: UUID,
    descriptor: dict[str, Any],
) -> None:
    agent = descriptor.get("agent") or {}
    urn = str(agent.get("urn", f"agent:{agent_id}"))
    label = str(agent.get("name") or urn)
    declared_nodes, declared_edges = derive_declared_graph(agent_id, urn, label, descriptor)

    key_to_id: dict[tuple[str, str], UUID] = {}
    for node in declared_nodes:
        saved = await repo.upsert_node(
            session,
            org_id,
            {
                "kind": node.kind,
                "node_key": node.node_key,
                "label": node.label,
                "entity_id": node.entity_id,
                "attrs": dict(node.attrs or {}),
                "is_declared": True,
            },
        )
        key_to_id[(node.kind, node.node_key)] = saved.id

    live_keys: list[tuple[UUID, UUID, str]] = []
    for edge in declared_edges:
        src_kind_key = _resolve_node_key(edge.src_key, urn, declared_nodes)
        dst_kind_key = _resolve_node_key(edge.dst_key, urn, declared_nodes)
        if src_kind_key is None or dst_kind_key is None:
            continue
        src = key_to_id.get(src_kind_key)
        dst = key_to_id.get(dst_kind_key)
        if src is None or dst is None:
            continue
        await repo.upsert_edge(
            session,
            org_id,
            {
                "src_id": src,
                "dst_id": dst,
                "kind": edge.kind,
                "source": GraphSource.DECLARED.value,
                "agent_version_id": version_id,
                "confidence": Decimal("1.00"),
                "observation_delta": 0,
            },
        )
        live_keys.append((src, dst, edge.kind))

    await repo.retire_declared_edges_not_in(session, org_id, version_id, live_keys)


def _resolve_node_key(
    key: str, agent_urn: str, nodes: list[DeclaredNode]
) -> tuple[str, str] | None:
    if key == agent_urn:
        return (GraphNodeKind.AGENT.value, agent_urn)
    for node in nodes:
        if node.node_key == key:
            return (node.kind, node.node_key)
    return None


async def record_observed_edge(
    session: AsyncSession,
    org_id: UUID,
    *,
    src_id: UUID,
    dst_id: UUID,
    kind: GraphEdgeKind,
    confidence: Decimal = Decimal("0.80"),
) -> GraphEdgeOut:
    edge = await repo.insert_observed_edge(
        session,
        org_id,
        {
            "src_id": src_id,
            "dst_id": dst_id,
            "kind": kind.value,
            "confidence": confidence,
        },
    )
    return GraphEdgeOut.model_validate(edge)


async def get_neighbourhood(
    session: AsyncSession,
    org_id: UUID,
    node_id: UUID,
    *,
    depth: int = 2,
    edge_kinds: list[str] | None = None,
) -> Neighbourhood:
    if await repo.get_node(session, org_id, node_id) is None:
        raise GraphNodeNotFoundError(node_id)
    rows = await repo.fetch_neighbourhood(
        session, org_id, node_id, depth=depth, edge_kinds=edge_kinds
    )
    nodes = [
        NeighbourhoodNode(
            node_id=r.id,
            kind=GraphNodeKind(r.kind),
            node_key=r.node_key,
            label=r.label,
            depth=r.depth,
            via_edge_kind=GraphEdgeKind(r.via_edge_kind),
        )
        for r in rows
    ]
    return Neighbourhood(origin_id=node_id, depth=depth, nodes=nodes)


async def compute_blast_radius(
    session: AsyncSession, org_id: UUID, node_id: UUID, *, max_depth: int = 4
) -> BlastRadius:
    if await repo.get_node(session, org_id, node_id) is None:
        raise GraphNodeNotFoundError(node_id)
    rows = await repo.fetch_blast_radius(session, org_id, node_id, max_depth=max_depth)
    nodes = [
        BlastRadiusNode(
            node_id=r.id,
            kind=GraphNodeKind(r.kind),
            node_key=r.node_key,
            label=r.label,
            depth=r.depth,
        )
        for r in rows
    ]
    return BlastRadius(origin_id=node_id, max_depth=max_depth, nodes=nodes)


async def get_reverse_reachability(
    session: AsyncSession, org_id: UUID, node_id: UUID, *, max_depth: int = 8
) -> BlastRadius:
    if await repo.get_node(session, org_id, node_id) is None:
        raise GraphNodeNotFoundError(node_id)
    rows = await repo.fetch_reverse_reachability(session, org_id, node_id, max_depth=max_depth)
    nodes = [
        BlastRadiusNode(
            node_id=r.id,
            kind=GraphNodeKind(r.kind),
            node_key=r.node_key,
            label=r.label,
            depth=r.depth,
        )
        for r in rows
    ]
    return BlastRadius(origin_id=node_id, max_depth=max_depth, nodes=nodes)


async def get_shortest_path(
    session: AsyncSession, org_id: UUID, src_id: UUID, dst_id: UUID
) -> PathResult:
    rows = await repo.fetch_shortest_path(session, org_id, src_id, dst_id)
    if not rows:
        return PathResult(src_id=src_id, dst_id=dst_id, found=False, hops=[])
    hops = [
        PathHop(
            node_id=r.id,
            kind=GraphNodeKind(r.kind),
            node_key=r.node_key,
            label=r.label,
        )
        for r in rows
    ]
    return PathResult(src_id=src_id, dst_id=dst_id, found=True, hops=hops)


async def reconcile(
    session: AsyncSession, org_id: UUID, *, limit: int = 500, offset: int = 0
) -> ReconciliationSummary:
    rows = await repo.fetch_reconciliation(session, org_id, limit=limit, offset=offset)
    return summarise_reconciliation(rows)


async def list_discovery_findings(
    session: AsyncSession,
    org_id: UUID,
    *,
    states: list[str] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[DiscoveryFindingOut]:
    rows = await repo.list_discovery_findings(
        session, org_id, states=states, limit=limit, offset=offset
    )
    return [DiscoveryFindingOut.model_validate(r) for r in rows]


async def resolve_finding(
    session: AsyncSession,
    org_id: UUID,
    finding_id: UUID,
    payload: DiscoveryFindingResolve,
) -> DiscoveryFindingOut:
    finding = await repo.get_discovery_finding(session, org_id, finding_id)
    if finding is None:
        raise DiscoveryFindingNotFoundError(finding_id)

    action = payload.action.lower()
    now = datetime.now(UTC)
    if action == "confirm":
        state = "confirmed"
        agent_id = finding.agent_id
    elif action == "dismiss":
        state = "dismissed"
        agent_id = None
    elif action == "merge":
        if payload.agent_id is None:
            raise DiscoveryResolveError("agent_id is required when merging a finding")
        state = "merged"
        agent_id = payload.agent_id
    else:
        raise DiscoveryResolveError(f"unknown resolve action {payload.action!r}")

    updated = await repo.update_discovery_finding(
        session,
        org_id,
        finding_id,
        {
            "state": state,
            "agent_id": agent_id,
            "resolved_by": payload.resolved_by,
            "resolved_at": now,
            "resolution_note": payload.note,
        },
    )
    if updated is None:
        raise DiscoveryFindingNotFoundError(finding_id)
    return DiscoveryFindingOut.model_validate(updated)


async def list_graph_nodes(
    session: AsyncSession,
    org_id: UUID,
    *,
    kinds: list[str] | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[GraphNodeOut]:
    rows = await repo.list_nodes(session, org_id, kinds=kinds, limit=limit, offset=offset)
    return [GraphNodeOut.model_validate(r) for r in rows]


async def list_graph_edges(
    session: AsyncSession,
    org_id: UUID,
    *,
    sources: list[str] | None = None,
    kinds: list[str] | None = None,
    limit: int = 500,
    offset: int = 0,
) -> list[GraphEdgeOut]:
    rows = await repo.list_edges(
        session, org_id, sources=sources, kinds=kinds, limit=limit, offset=offset
    )
    return [GraphEdgeOut.model_validate(r) for r in rows]


async def agents_reaching(
    session: AsyncSession, org_id: UUID, *, kind: str, node_key: str
) -> list[GraphNodeOut]:
    rows = await repo.fetch_agents_reaching(session, org_id, kind=kind, node_key=node_key)
    return [
        GraphNodeOut(
            id=r.id,
            kind=GraphNodeKind(r.kind),
            node_key=r.node_key,
            label=r.label,
            entity_id=None,
            attrs={},
            is_declared=True,
            is_observed=False,
            first_seen_at=datetime.now(UTC),
            last_seen_at=datetime.now(UTC),
            retired_at=None,
        )
        for r in rows
    ]
