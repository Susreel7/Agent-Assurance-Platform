"""SLO HTTP handlers."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import Session, VerifiedOrg, WriteGuard
from app.api.route import TransactionalRoute
from app.domains.sla import service
from app.domains.sla.schemas import (
    BreachOut,
    EngagementSummaryOut,
    MeasurementCreate,
    MeasurementOut,
    SloCreate,
    SloOut,
)

router = APIRouter(route_class=TransactionalRoute)

_STATUS_FOR: dict[type[Exception], int] = {
    service.SloNotFoundError: status.HTTP_404_NOT_FOUND,
    service.EngagementNotFoundError: status.HTTP_404_NOT_FOUND,
}


def _http(exc: service.SloError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST),
        detail=str(exc),
    )


@router.post(
    "", response_model=SloOut, status_code=status.HTTP_201_CREATED, dependencies=[WriteGuard]
)
async def create_slo(
    payload: SloCreate,
    session: Session,
    org_id: VerifiedOrg,
) -> SloOut:
    try:
        return await service.define_slo(session, org_id, payload)
    except service.SloError as exc:
        raise _http(exc) from exc


@router.get("", response_model=list[SloOut])
async def list_slos(
    session: Session,
    org_id: VerifiedOrg,
    engagement_id: UUID | None = Query(default=None),
) -> list[SloOut]:
    return await service.list_slos(session, org_id, engagement_id=engagement_id)


@router.get("/{slo_id}", response_model=SloOut)
async def get_slo(
    slo_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> SloOut:
    try:
        return await service.get_slo(session, org_id, slo_id)
    except service.SloError as exc:
        raise _http(exc) from exc


@router.post(
    "/{slo_id}/measurements",
    response_model=MeasurementOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[WriteGuard],
)
async def record_measurement(
    slo_id: UUID,
    payload: MeasurementCreate,
    session: Session,
    org_id: VerifiedOrg,
) -> MeasurementOut:
    try:
        return await service.record_measurement(session, org_id, slo_id, payload)
    except service.SloError as exc:
        raise _http(exc) from exc


@router.get("/{slo_id}/breaches", response_model=list[BreachOut])
async def list_breaches(
    slo_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> list[BreachOut]:
    return await service.list_breaches(session, org_id, slo_id)


@router.post("/{slo_id}/detect-breaches", dependencies=[WriteGuard])
async def detect_breaches(
    slo_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> BreachOut | None:
    try:
        return await service.detect_breaches(session, org_id, slo_id)
    except service.SloError as exc:
        raise _http(exc) from exc


@router.get("/-/engagements/{engagement_id}/summary", response_model=EngagementSummaryOut)
async def engagement_summary(
    engagement_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> EngagementSummaryOut:
    try:
        return await service.summarise_engagement(session, org_id, engagement_id)
    except service.SloError as exc:
        raise _http(exc) from exc
