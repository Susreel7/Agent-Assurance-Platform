"""Engagement HTTP handlers. Thin by rule — every one delegates immediately.

Domain exceptions are translated here and nowhere else, which is why the mapping is a
single dictionary rather than try/except blocks scattered through the handlers.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel

from app.api.deps import Session, VerifiedOrg, WriteEnabled
from app.api.route import TransactionalRoute
from app.domains.engagements import service
from app.domains.engagements.schemas import (
    DriftReport,
    DriftSeverity,
    EngagementCreate,
    EngagementDetail,
    EngagementState,
    EngagementSummary,
    EngagementUpdate,
    ScopeAgentRequest,
    ScopeAgentUpdate,
    ScopedAgentOut,
    ServiceLevelOut,
    ServiceLevelUpsert,
)

router = APIRouter(route_class=TransactionalRoute)

_STATUS_FOR: dict[type[Exception], int] = {
    service.EngagementNotFoundError: status.HTTP_404_NOT_FOUND,
    service.CustomerNotFoundError: status.HTTP_404_NOT_FOUND,
    service.AgentNotScopedError: status.HTTP_404_NOT_FOUND,
    service.ServiceLevelNotFoundError: status.HTTP_404_NOT_FOUND,
    service.EngagementSlugTakenError: status.HTTP_409_CONFLICT,
    service.AgentAlreadyScopedError: status.HTTP_409_CONFLICT,
    service.IllegalStateChangeError: status.HTTP_409_CONFLICT,
}


def _http(exc: service.EngagementError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST),
        detail=str(exc),
    )


class EngagementPage(BaseModel):
    items: list[EngagementSummary]
    total: int
    limit: int
    offset: int


class DriftResponse(BaseModel):
    """Wraps the report so ``headline`` crosses the wire.

    Pydantic does not serialise ``@property``, and a console that recomputes the
    sentence will eventually word it differently from the accreditation pack.
    """

    report: DriftReport
    headline: str


# ----------------------------------------------------------------------
# Engagements
# ----------------------------------------------------------------------


@router.post(
    "",
    response_model=EngagementDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Open a delivery for a client, with its residency and commercial terms",
)
async def create_engagement(
    payload: EngagementCreate,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> EngagementDetail:
    try:
        return await service.create_engagement(session, org_id, payload)
    except service.EngagementError as exc:
        raise _http(exc) from exc


@router.get("", response_model=EngagementPage, summary="List deliveries")
async def list_engagements(
    session: Session,
    org_id: VerifiedOrg,
    customer_id: Annotated[UUID | None, Query()] = None,
    state: Annotated[list[EngagementState] | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=128)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> EngagementPage:
    items, total = await service.list_engagements(
        session,
        org_id,
        customer_id=customer_id,
        states=[s.value for s in state] if state else None,
        search=search,
        limit=limit,
        offset=offset,
    )
    return EngagementPage(items=items, total=total, limit=limit, offset=offset)


# Declared before /{engagement_id} so the literal segment is not captured as a UUID.
@router.get(
    "/-/drift",
    response_model=DriftResponse,
    summary="Every client being served a version they have not approved",
)
async def estate_drift(
    session: Session,
    org_id: VerifiedOrg,
    customer_id: Annotated[UUID | None, Query()] = None,
    min_severity: Annotated[DriftSeverity | None, Query()] = None,
) -> DriftResponse:
    report = await service.drift_report(
        session, org_id, customer_id=customer_id, min_severity=min_severity
    )
    return DriftResponse(report=report, headline=report.headline)


@router.get("/{engagement_id}", response_model=EngagementDetail, summary="One delivery in full")
async def get_engagement(
    engagement_id: UUID, session: Session, org_id: VerifiedOrg
) -> EngagementDetail:
    try:
        return await service.get_engagement_detail(session, org_id, engagement_id)
    except service.EngagementError as exc:
        raise _http(exc) from exc


@router.patch(
    "/{engagement_id}",
    response_model=EngagementDetail,
    summary="Revise terms or move the delivery's state",
)
async def update_engagement(
    engagement_id: UUID,
    payload: EngagementUpdate,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> EngagementDetail:
    try:
        return await service.update_engagement(session, org_id, engagement_id, payload)
    except service.EngagementError as exc:
        raise _http(exc) from exc


@router.get(
    "/{engagement_id}/drift",
    response_model=DriftResponse,
    summary="Drift for one delivery",
)
async def engagement_drift(
    engagement_id: UUID, session: Session, org_id: VerifiedOrg
) -> DriftResponse:
    report = await service.drift_report(session, org_id, engagement_id=engagement_id)
    return DriftResponse(report=report, headline=report.headline)


# ----------------------------------------------------------------------
# Service levels
# ----------------------------------------------------------------------


@router.put(
    "/{engagement_id}/service-levels",
    response_model=ServiceLevelOut,
    summary="Record or revise a service-level commitment",
)
async def set_service_level(
    engagement_id: UUID,
    payload: ServiceLevelUpsert,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> ServiceLevelOut:
    try:
        return await service.set_service_level(session, org_id, engagement_id, payload)
    except service.EngagementError as exc:
        raise _http(exc) from exc


@router.delete(
    "/{engagement_id}/service-levels/{slo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Withdraw a service-level commitment",
)
async def drop_service_level(
    engagement_id: UUID,
    slo_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> Response:
    try:
        await service.drop_service_level(session, org_id, engagement_id, slo_id)
    except service.EngagementError as exc:
        raise _http(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ----------------------------------------------------------------------
# Scope
# ----------------------------------------------------------------------


@router.post(
    "/{engagement_id}/agents",
    response_model=ScopedAgentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Bring an agent into scope for this client",
)
async def scope_agent(
    engagement_id: UUID,
    payload: ScopeAgentRequest,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> ScopedAgentOut:
    try:
        return await service.scope_agent(session, org_id, engagement_id, payload)
    except service.EngagementError as exc:
        raise _http(exc) from exc


@router.get(
    "/{engagement_id}/agents",
    response_model=list[ScopedAgentOut],
    summary="Agents in scope, with approved and running versions side by side",
)
async def list_scoped_agents(
    engagement_id: UUID, session: Session, org_id: VerifiedOrg
) -> list[ScopedAgentOut]:
    try:
        detail = await service.get_engagement_detail(session, org_id, engagement_id)
    except service.EngagementError as exc:
        raise _http(exc) from exc
    return detail.agents


@router.patch(
    "/{engagement_id}/agents/{agent_id}",
    response_model=ScopedAgentOut,
    summary="Record an approval, a deployment, or a change of uptake policy",
)
async def update_scope(
    engagement_id: UUID,
    agent_id: UUID,
    payload: ScopeAgentUpdate,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> ScopedAgentOut:
    try:
        return await service.update_scope(session, org_id, engagement_id, agent_id, payload)
    except service.EngagementError as exc:
        raise _http(exc) from exc


@router.delete(
    "/{engagement_id}/agents/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Take an agent out of scope for this client",
)
async def unscope_agent(
    engagement_id: UUID,
    agent_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> Response:
    try:
        await service.unscope_agent(session, org_id, engagement_id, agent_id)
    except service.EngagementError as exc:
        raise _http(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
