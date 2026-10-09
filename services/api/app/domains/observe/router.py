"""Entitlement-aware human API for Observe queries."""

from __future__ import annotations

from typing import Annotated, Literal, Never
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentPrincipal, Session, VerifiedOrg, require_permission
from app.api.route import TransactionalRoute
from app.domains.modules.schemas import ModuleCapability, SuiteModuleId
from app.domains.modules.service import require_module_capability
from app.domains.observe import service
from app.domains.observe.schemas import (
    ExecutionAnalytics,
    ExecutionDetail,
    ExecutionEvents,
    ExecutionLink,
    ExecutionObservations,
    ExecutionPage,
    ExecutionTimeline,
    ObservedUser,
    ObservedUserPage,
    ObserveFreshness,
    PayloadContent,
    PayloadLegalHold,
    PayloadLegalHoldUpdate,
    PayloadReference,
    SamplingPolicy,
    SamplingPolicyUpdate,
    SessionDetail,
    SessionPage,
    TraceDetail,
    TraceFacets,
    TraceGraph,
    TraceMetrics,
    TracePage,
    UserActivity,
    UserIdentityBinding,
    UserIdentityBindingCreate,
)
from app.domains.workload_identity import service as workload_service

router = APIRouter(route_class=TransactionalRoute)

ObserveRead = Annotated[
    None,
    Depends(require_module_capability(SuiteModuleId.OBSERVE, ModuleCapability.READ)),
]
ObserveConfigure = Annotated[
    None,
    Depends(require_module_capability(SuiteModuleId.OBSERVE, ModuleCapability.CONFIGURE)),
]
ObserveContentRead = Annotated[
    None,
    Depends(require_permission("observe:content:read")),
]
ObserveRetentionManage = Annotated[
    None,
    Depends(require_permission("observe:retention:manage")),
]


async def _project_exists(session: Session, org_id: UUID, project_id: UUID) -> None:
    try:
        await workload_service.get_project(session, org_id, project_id)
    except workload_service.ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


def _raise_observe(exc: Exception) -> Never:
    if isinstance(exc, service.ObserveRequestError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    raise HTTPException(status_code=503, detail="Observe service unavailable") from exc


@router.get("/projects/{project_id}/traces", response_model=TracePage)
async def list_traces(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveRead,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    session_id: Annotated[str | None, Query(max_length=256)] = None,
    agent_id: Annotated[str | None, Query(max_length=128)] = None,
    initiating_user_id: Annotated[str | None, Query(max_length=256)] = None,
    outcome: Annotated[str | None, Query(max_length=32)] = None,
    model: Annotated[str | None, Query(max_length=256)] = None,
    tool: Annotated[str | None, Query(max_length=256)] = None,
    kind: Annotated[str | None, Query(max_length=64)] = None,
    query: Annotated[str | None, Query(max_length=256)] = None,
    min_latency_ms: Annotated[float | None, Query(ge=0)] = None,
    max_latency_ms: Annotated[float | None, Query(ge=0)] = None,
    min_cost_micros: Annotated[int | None, Query(ge=0)] = None,
    max_cost_micros: Annotated[int | None, Query(ge=0)] = None,
) -> TracePage:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.list_traces(
            org_id,
            project_id,
            limit=limit,
            offset=offset,
            filters={
                "session_id": session_id,
                "agent_id": agent_id,
                "initiating_user_id": initiating_user_id,
                "outcome": outcome,
                "model": model,
                "tool": tool,
                "kind": kind,
                "query": query,
                "min_latency_ms": min_latency_ms,
                "max_latency_ms": max_latency_ms,
                "min_cost_micros": min_cost_micros,
                "max_cost_micros": max_cost_micros,
            },
        )
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.get("/projects/{project_id}/traces/{trace_id}", response_model=TraceDetail)
async def trace_detail(
    project_id: UUID,
    trace_id: str,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveRead,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TraceDetail:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_trace(org_id, project_id, trace_id, limit=limit, offset=offset)
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.get("/projects/{project_id}/traces/{trace_id}/graph", response_model=TraceGraph)
async def trace_graph(
    project_id: UUID,
    trace_id: str,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveRead,
) -> TraceGraph:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_trace_graph(org_id, project_id, trace_id)
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.get(
    "/projects/{project_id}/traces/{trace_id}/payload-refs",
    response_model=list[PayloadReference],
)
async def payload_references(
    project_id: UUID,
    trace_id: str,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveRead,
) -> list[PayloadReference]:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.payload_references(org_id, project_id, trace_id)
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.get("/projects/{project_id}/executions", response_model=ExecutionPage)
async def list_executions(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveRead,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    initiating_user_id: Annotated[str | None, Query(max_length=256)] = None,
    session_id: Annotated[str | None, Query(max_length=256)] = None,
    status: Annotated[str | None, Query(max_length=32)] = None,
) -> ExecutionPage:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.list_executions(
            org_id,
            project_id,
            limit=limit,
            offset=offset,
            initiating_user_id=initiating_user_id,
            session_id=session_id,
            status=status,
        )
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.get("/projects/{project_id}/executions/{execution_id}", response_model=ExecutionDetail)
async def execution_detail(
    project_id: UUID,
    execution_id: str,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveRead,
) -> ExecutionDetail:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_execution(org_id, project_id, execution_id)
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.get(
    "/projects/{project_id}/executions/{execution_id}/tree",
    response_model=TraceGraph,
)
async def execution_tree(
    project_id: UUID,
    execution_id: str,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveRead,
) -> TraceGraph:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_execution_tree(org_id, project_id, execution_id)
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.get(
    "/projects/{project_id}/executions/{execution_id}/observations",
    response_model=ExecutionObservations,
)
async def execution_observations(
    project_id: UUID,
    execution_id: str,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveRead,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ExecutionObservations:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_execution_observations(
            org_id, project_id, execution_id, limit=limit, offset=offset
        )
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.get(
    "/projects/{project_id}/executions/{execution_id}/events",
    response_model=ExecutionEvents,
)
async def execution_events(
    project_id: UUID,
    execution_id: str,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveRead,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
) -> ExecutionEvents:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_execution_events(org_id, project_id, execution_id, limit=limit)
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.get(
    "/projects/{project_id}/executions/{execution_id}/timeline",
    response_model=ExecutionTimeline,
)
async def execution_timeline(
    project_id: UUID,
    execution_id: str,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveRead,
) -> ExecutionTimeline:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_execution_timeline(org_id, project_id, execution_id)
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.get(
    "/projects/{project_id}/executions/{execution_id}/links",
    response_model=list[ExecutionLink],
)
async def execution_links(
    project_id: UUID,
    execution_id: str,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveRead,
) -> list[ExecutionLink]:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_execution_links(org_id, project_id, execution_id)
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.get("/projects/{project_id}/observed-users", response_model=ObservedUserPage)
async def list_observed_users(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveRead,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ObservedUserPage:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.list_users(org_id, project_id, limit=limit, offset=offset)
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.get(
    "/projects/{project_id}/observed-users/{user_id}",
    response_model=ObservedUser,
)
async def observed_user_detail(
    project_id: UUID,
    user_id: str,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveRead,
) -> ObservedUser:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_user(org_id, project_id, user_id)
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.post(
    "/projects/{project_id}/observed-users/bindings",
    response_model=UserIdentityBinding,
)
async def create_observed_user_binding(
    project_id: UUID,
    payload: UserIdentityBindingCreate,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveConfigure,
) -> UserIdentityBinding:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.create_user_binding(org_id, project_id, payload)
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.get(
    "/projects/{project_id}/observed-users/{user_id}/executions",
    response_model=ExecutionPage,
)
async def observed_user_executions(
    project_id: UUID,
    user_id: str,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveRead,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ExecutionPage:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_user_executions(
            org_id, project_id, user_id, limit=limit, offset=offset
        )
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.get(
    "/projects/{project_id}/observed-users/{user_id}/activity",
    response_model=UserActivity,
)
async def observed_user_activity(
    project_id: UUID,
    user_id: str,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveRead,
    dimension: Literal["models", "tools", "mcp-tools", "sdk-operations"] = "models",
) -> UserActivity:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_user_activity(org_id, project_id, user_id, dimension)
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.get(
    "/projects/{project_id}/payloads/{payload_id}/content",
    response_model=PayloadContent,
)
async def payload_content(
    project_id: UUID,
    payload_id: UUID,
    principal: CurrentPrincipal,
    session: Session,
    org_id: VerifiedOrg,
    _module: ObserveRead,
    _content_permission: ObserveContentRead,
) -> PayloadContent:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_payload_content(
            org_id,
            project_id,
            payload_id,
            actor_subject=principal.subject,
        )
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.put(
    "/projects/{project_id}/payloads/{payload_id}/legal-hold",
    response_model=PayloadLegalHold,
)
async def update_payload_legal_hold(
    project_id: UUID,
    payload_id: UUID,
    payload: PayloadLegalHoldUpdate,
    principal: CurrentPrincipal,
    session: Session,
    org_id: VerifiedOrg,
    _module: ObserveConfigure,
    _retention_permission: ObserveRetentionManage,
) -> PayloadLegalHold:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.update_payload_legal_hold(
            org_id,
            project_id,
            payload_id,
            payload,
            actor_subject=principal.subject,
        )
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.get("/projects/{project_id}/sessions", response_model=SessionPage)
async def list_sessions(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveRead,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    initiating_user_id: Annotated[str | None, Query(max_length=256)] = None,
) -> SessionPage:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.list_sessions(
            org_id,
            project_id,
            limit=limit,
            offset=offset,
            initiating_user_id=initiating_user_id,
        )
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.get("/projects/{project_id}/sessions/{session_id}", response_model=SessionDetail)
async def session_detail(
    project_id: UUID,
    session_id: str,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveRead,
) -> SessionDetail:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_session(org_id, project_id, session_id)
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.get("/projects/{project_id}/facets", response_model=TraceFacets)
async def facets(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveRead,
) -> TraceFacets:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.trace_facets(org_id, project_id)
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.get("/projects/{project_id}/metrics", response_model=TraceMetrics)
async def metrics(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveRead,
) -> TraceMetrics:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.trace_metrics(org_id, project_id, filters={})
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.get(
    "/projects/{project_id}/analytics/executions",
    response_model=ExecutionAnalytics,
)
async def execution_analytics(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveRead,
) -> ExecutionAnalytics:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.execution_analytics(org_id, project_id)
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.get(
    "/projects/{project_id}/sampling-policy",
    response_model=SamplingPolicy,
)
async def get_sampling_policy(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveRead,
) -> SamplingPolicy:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_sampling_policy(org_id, project_id)
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.put(
    "/projects/{project_id}/sampling-policy",
    response_model=SamplingPolicy,
)
async def update_sampling_policy(
    project_id: UUID,
    payload: SamplingPolicyUpdate,
    principal: CurrentPrincipal,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveConfigure,
) -> SamplingPolicy:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.update_sampling_policy(
            org_id,
            project_id,
            payload,
            actor_subject=principal.subject,
        )
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.get("/projects/{project_id}/freshness", response_model=ObserveFreshness)
async def freshness(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveRead,
) -> ObserveFreshness:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.freshness(org_id, project_id)
    except (service.ObserveUnavailableError, service.ObserveRequestError) as exc:
        _raise_observe(exc)


@router.get("/projects/{project_id}/live-tail")
async def live_tail(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    _: ObserveRead,
    cursor: Annotated[str | None, Query(max_length=128)] = None,
    trace_id: Annotated[str | None, Query(min_length=1, max_length=128)] = None,
) -> StreamingResponse:
    await _project_exists(session, org_id, project_id)
    return StreamingResponse(
        service.live_tail(org_id, project_id, cursor=cursor, trace_id=trace_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
