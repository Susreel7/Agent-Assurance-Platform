"""Graph HTTP handlers. Thin by rule — every one delegates immediately."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import Session, VerifiedOrg, WriteEnabled
from app.api.route import TransactionalRoute
from app.domains.graph import service
from app.domains.graph.schemas import (
    BlastRadius,
    DiscoveryFindingOut,
    DiscoveryFindingResolve,
    GraphEdgeKind,
    GraphEdgeOut,
    GraphNodeKind,
    GraphNodeOut,
    Neighbourhood,
    PathResult,
    ReconciliationSummary,
)

router = APIRouter(route_class=TransactionalRoute)

_STATUS_FOR: dict[type[Exception], int] = {
    service.GraphNodeNotFoundError: status.HTTP_404_NOT_FOUND,
    service.DiscoveryFindingNotFoundError: status.HTTP_404_NOT_FOUND,
    service.DiscoveryResolveError: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def _http(exc: service.GraphError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST),
        detail=str(exc),
    )


@router.get("/nodes", response_model=list[GraphNodeOut], summary="List graph nodes")
async def list_nodes(
    session: Session,
    org_id: VerifiedOrg,
    kind: Annotated[list[GraphNodeKind] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[GraphNodeOut]:
    kinds = [k.value for k in kind] if kind else None
    return await service.list_graph_nodes(session, org_id, kinds=kinds, limit=limit, offset=offset)


@router.get("/edges", response_model=list[GraphEdgeOut], summary="List graph edges")
async def list_edges(
    session: Session,
    org_id: VerifiedOrg,
    source: Annotated[list[str] | None, Query()] = None,
    kind: Annotated[list[GraphEdgeKind] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=1000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[GraphEdgeOut]:
    kinds = [k.value for k in kind] if kind else None
    return await service.list_graph_edges(
        session, org_id, sources=source, kinds=kinds, limit=limit, offset=offset
    )


@router.get(
    "/nodes/{node_id}/neighbourhood",
    response_model=Neighbourhood,
    summary="Outward neighbourhood to bounded depth",
)
async def get_neighbourhood(
    node_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    depth: Annotated[int, Query(ge=1, le=4)] = 2,
    edge_kind: Annotated[list[GraphEdgeKind] | None, Query(alias="edge_kind")] = None,
) -> Neighbourhood:
    try:
        return await service.get_neighbourhood(
            session,
            org_id,
            node_id,
            depth=depth,
            edge_kinds=[k.value for k in edge_kind] if edge_kind else None,
        )
    except service.GraphError as exc:
        raise _http(exc) from exc


@router.get(
    "/nodes/{node_id}/blast-radius",
    response_model=BlastRadius,
    summary="Everything reachable forward from a node",
)
async def get_blast_radius(
    node_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    max_depth: Annotated[int, Query(ge=1, le=8)] = 4,
) -> BlastRadius:
    try:
        return await service.compute_blast_radius(session, org_id, node_id, max_depth=max_depth)
    except service.GraphError as exc:
        raise _http(exc) from exc


@router.get(
    "/nodes/{node_id}/reachable-by",
    response_model=BlastRadius,
    summary="Everything that can reach this node",
)
async def get_reachable_by(
    node_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    max_depth: Annotated[int, Query(ge=1, le=8)] = 8,
) -> BlastRadius:
    try:
        return await service.get_reverse_reachability(session, org_id, node_id, max_depth=max_depth)
    except service.GraphError as exc:
        raise _http(exc) from exc


@router.get("/-/path", response_model=PathResult, summary="Shortest path between two nodes")
async def get_path(
    session: Session,
    org_id: VerifiedOrg,
    src: Annotated[UUID, Query()],
    dst: Annotated[UUID, Query()],
) -> PathResult:
    return await service.get_shortest_path(session, org_id, src, dst)


@router.get(
    "/-/reconciliation",
    response_model=ReconciliationSummary,
    summary="Declared versus observed edge gaps",
)
async def get_reconciliation(
    session: Session,
    org_id: VerifiedOrg,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ReconciliationSummary:
    return await service.reconcile(session, org_id, limit=limit, offset=offset)


@router.get(
    "/-/agents-reaching",
    response_model=list[GraphNodeOut],
    summary="Agents that can reach a target node",
)
async def agents_reaching(
    session: Session,
    org_id: VerifiedOrg,
    kind: Annotated[GraphNodeKind, Query()],
    key: Annotated[str, Query(min_length=1, max_length=512)],
) -> list[GraphNodeOut]:
    return await service.agents_reaching(session, org_id, kind=kind.value, node_key=key)


@router.get(
    "/-/discovery/findings",
    response_model=list[DiscoveryFindingOut],
    summary="Discovery triage queue",
)
async def list_findings(
    session: Session,
    org_id: VerifiedOrg,
    state: Annotated[list[str] | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[DiscoveryFindingOut]:
    return await service.list_discovery_findings(
        session, org_id, states=state, limit=limit, offset=offset
    )


@router.post(
    "/-/discovery/findings/{finding_id}/resolve",
    response_model=DiscoveryFindingOut,
    summary="Confirm, dismiss or merge a discovery finding",
)
async def resolve_finding(
    finding_id: UUID,
    payload: DiscoveryFindingResolve,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> DiscoveryFindingOut:
    try:
        return await service.resolve_finding(session, org_id, finding_id, payload)
    except service.GraphError as exc:
        raise _http(exc) from exc
