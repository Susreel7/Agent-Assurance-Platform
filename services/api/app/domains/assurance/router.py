"""Assurance HTTP handlers — findings, probes and posture."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import Session, VerifiedOrg, WriteGuard
from app.api.route import TransactionalRoute
from app.domains.assurance import service
from app.domains.assurance.schemas import (
    FindingCategory,
    FindingCreate,
    FindingOut,
    FindingPage,
    FindingResolve,
    FindingSource,
    FindingState,
    FindingTriage,
    PostureScoreOut,
    ProbeRunDetailOut,
    ProbeRunOut,
    ProbeSuiteOut,
    Severity,
    SeverityCounts,
)

router = APIRouter(route_class=TransactionalRoute)

_STATUS_FOR: dict[type[Exception], int] = {
    service.FindingNotFoundError: status.HTTP_404_NOT_FOUND,
    service.ProbeSuiteNotFoundError: status.HTTP_404_NOT_FOUND,
    service.ProbeRunNotFoundError: status.HTTP_404_NOT_FOUND,
    service.InvalidResolutionError: status.HTTP_400_BAD_REQUEST,
}


def _http(exc: service.AssuranceError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST),
        detail=str(exc),
    )


class ProbeRunRequest(BaseModel):
    agent_id: UUID
    agent_version_id: UUID
    triggered_by: str = "person:api"


class ProbeRunPage(BaseModel):
    items: list[ProbeRunOut]
    total: int
    limit: int
    offset: int


@router.get("/findings", response_model=FindingPage, summary="List findings")
async def list_findings(
    session: Session,
    org_id: VerifiedOrg,
    severity: Annotated[list[Severity] | None, Query()] = None,
    source: Annotated[list[FindingSource] | None, Query()] = None,
    category: Annotated[list[FindingCategory] | None, Query()] = None,
    state: Annotated[list[FindingState] | None, Query()] = None,
    agent_id: Annotated[UUID | None, Query()] = None,
    overdue: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> FindingPage:
    return await service.list_findings(
        session,
        org_id,
        severity=[s.value for s in severity] if severity else None,
        source=[s.value for s in source] if source else None,
        category=[c.value for c in category] if category else None,
        state=[s.value for s in state] if state else None,
        agent_id=agent_id,
        overdue_only=overdue,
        limit=limit,
        offset=offset,
    )


@router.get("/findings/-/severity-counts", response_model=SeverityCounts)
async def get_severity_counts(
    session: Session,
    org_id: VerifiedOrg,
    agent_id: Annotated[UUID | None, Query()] = None,
) -> SeverityCounts:
    return await service.severity_counts(session, org_id, agent_id=agent_id)


@router.post(
    "/findings",
    response_model=FindingOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[WriteGuard],
)
async def create_finding(
    payload: FindingCreate,
    session: Session,
    org_id: VerifiedOrg,
) -> FindingOut:
    return await service.record_finding(session, org_id, payload)


@router.post(
    "/findings/{finding_id}/triage",
    response_model=FindingOut,
    dependencies=[WriteGuard],
)
async def triage_finding(
    finding_id: UUID,
    payload: FindingTriage,
    session: Session,
    org_id: VerifiedOrg,
) -> FindingOut:
    try:
        return await service.triage_finding(session, org_id, finding_id, payload)
    except service.AssuranceError as exc:
        raise _http(exc) from exc


@router.post(
    "/findings/{finding_id}/resolve",
    response_model=FindingOut,
    dependencies=[WriteGuard],
)
async def resolve_finding(
    finding_id: UUID,
    payload: FindingResolve,
    session: Session,
    org_id: VerifiedOrg,
) -> FindingOut:
    try:
        return await service.resolve_finding(session, org_id, finding_id, payload)
    except service.AssuranceError as exc:
        raise _http(exc) from exc


@router.get("/probe-suites", response_model=list[ProbeSuiteOut])
async def list_probe_suites(session: Session, org_id: VerifiedOrg) -> list[ProbeSuiteOut]:
    return await service.list_probe_suites(session, org_id)


@router.post(
    "/probe-suites/{suite_id}/runs",
    response_model=ProbeRunOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[WriteGuard],
)
async def run_probe_suite(
    suite_id: UUID,
    payload: ProbeRunRequest,
    session: Session,
    org_id: VerifiedOrg,
) -> ProbeRunOut:
    try:
        return await service.run_probe_suite(
            session,
            org_id,
            suite_id,
            payload.agent_id,
            payload.agent_version_id,
            payload.triggered_by,
        )
    except service.AssuranceError as exc:
        raise _http(exc) from exc


@router.get("/probe-runs/{run_id}", response_model=ProbeRunDetailOut)
async def get_probe_run(
    run_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> ProbeRunDetailOut:
    try:
        return await service.get_probe_run_detail(session, org_id, run_id)
    except service.AssuranceError as exc:
        raise _http(exc) from exc


@router.get("/probe-runs", response_model=ProbeRunPage)
async def list_probe_runs(
    session: Session,
    org_id: VerifiedOrg,
    agent_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProbeRunPage:
    items, total = await service.list_probe_runs(
        session, org_id, agent_id=agent_id, limit=limit, offset=offset
    )
    return ProbeRunPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/posture/{agent_id}", response_model=PostureScoreOut | None)
async def get_posture(
    agent_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> PostureScoreOut | None:
    return await service.get_latest_posture(session, org_id, agent_id)


@router.post(
    "/posture/{agent_id}/recompute",
    response_model=PostureScoreOut,
    dependencies=[WriteGuard],
)
async def recompute_posture(
    agent_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> PostureScoreOut:
    return await service.compute_posture(session, org_id, agent_id)
