"""Accreditation HTTP handlers."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import Session, VerifiedOrg, WriteGuard
from app.api.route import TransactionalRoute
from app.domains.accreditation import service
from app.domains.accreditation.schemas import (
    AccreditationControlOut,
    AccreditationCreate,
    AccreditationDetail,
    AccreditationPackOut,
    AccreditationSummary,
    PackRenderRequest,
    ReadinessOut,
    TransitionOut,
    TransitionRequest,
)

router = APIRouter(route_class=TransactionalRoute)

_STATUS_FOR: dict[type[Exception], int] = {
    service.AccreditationNotFoundError: status.HTTP_404_NOT_FOUND,
    service.InvalidTransitionError: status.HTTP_409_CONFLICT,
    service.SelfApprovalError: status.HTTP_403_FORBIDDEN,
    service.PackRenderError: status.HTTP_501_NOT_IMPLEMENTED,
}


def _http(exc: service.AccreditationError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST),
        detail=str(exc),
    )


class AccreditationPage(BaseModel):
    items: list[AccreditationSummary]
    total: int
    limit: int
    offset: int


@router.get("", response_model=AccreditationPage)
async def list_accreditations(
    session: Session,
    org_id: VerifiedOrg,
    engagement_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AccreditationPage:
    items, total = await service.list_accreditation_summaries(
        session, org_id, engagement_id=engagement_id, limit=limit, offset=offset
    )
    return AccreditationPage(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "",
    response_model=AccreditationDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[WriteGuard],
)
async def create_accreditation(
    payload: AccreditationCreate,
    session: Session,
    org_id: VerifiedOrg,
) -> AccreditationDetail:
    try:
        return await service.create_accreditation(session, org_id, payload)
    except service.AccreditationError as exc:
        raise _http(exc) from exc


@router.get("/-/readiness", response_model=ReadinessOut)
async def get_readiness(
    session: Session,
    org_id: VerifiedOrg,
    customer_id: Annotated[UUID, Query()],
) -> ReadinessOut:
    return await service.compute_readiness(session, org_id, customer_id)


@router.get("/{accreditation_id}", response_model=AccreditationDetail)
async def get_accreditation(
    accreditation_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> AccreditationDetail:
    try:
        return await service.get_accreditation_detail(session, org_id, accreditation_id)
    except service.AccreditationError as exc:
        raise _http(exc) from exc


@router.post("/{accreditation_id}/submit", response_model=TransitionOut, dependencies=[WriteGuard])
async def submit(
    accreditation_id: UUID,
    payload: TransitionRequest,
    session: Session,
    org_id: VerifiedOrg,
) -> TransitionOut:
    try:
        return await service.submit_accreditation(session, org_id, accreditation_id, payload)
    except service.AccreditationError as exc:
        raise _http(exc) from exc


@router.post("/{accreditation_id}/approve", response_model=TransitionOut, dependencies=[WriteGuard])
async def approve(
    accreditation_id: UUID,
    payload: TransitionRequest,
    session: Session,
    org_id: VerifiedOrg,
) -> TransitionOut:
    try:
        return await service.approve_accreditation(session, org_id, accreditation_id, payload)
    except service.AccreditationError as exc:
        raise _http(exc) from exc


@router.post("/{accreditation_id}/reject", response_model=TransitionOut, dependencies=[WriteGuard])
async def reject(
    accreditation_id: UUID,
    payload: TransitionRequest,
    session: Session,
    org_id: VerifiedOrg,
) -> TransitionOut:
    try:
        return await service.reject_accreditation(session, org_id, accreditation_id, payload)
    except service.AccreditationError as exc:
        raise _http(exc) from exc


@router.post("/{accreditation_id}/suspend", response_model=TransitionOut, dependencies=[WriteGuard])
async def suspend(
    accreditation_id: UUID,
    payload: TransitionRequest,
    session: Session,
    org_id: VerifiedOrg,
) -> TransitionOut:
    try:
        return await service.suspend_accreditation(session, org_id, accreditation_id, payload)
    except service.AccreditationError as exc:
        raise _http(exc) from exc


@router.post(
    "/{accreditation_id}/withdraw", response_model=TransitionOut, dependencies=[WriteGuard]
)
async def withdraw(
    accreditation_id: UUID,
    payload: TransitionRequest,
    session: Session,
    org_id: VerifiedOrg,
) -> TransitionOut:
    try:
        return await service.withdraw_accreditation(session, org_id, accreditation_id, payload)
    except service.AccreditationError as exc:
        raise _http(exc) from exc


@router.post(
    "/{accreditation_id}/assemble",
    response_model=list[AccreditationControlOut],
    dependencies=[WriteGuard],
)
async def assemble(
    accreditation_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> list[AccreditationControlOut]:
    try:
        return await service.assemble_controls(session, org_id, accreditation_id)
    except service.AccreditationError as exc:
        raise _http(exc) from exc


@router.get("/{accreditation_id}/controls", response_model=list[AccreditationControlOut])
async def list_controls(
    accreditation_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> list[AccreditationControlOut]:
    return await service.list_controls(session, org_id, accreditation_id)


@router.post(
    "/{accreditation_id}/packs", response_model=AccreditationPackOut, dependencies=[WriteGuard]
)
async def render_pack(
    accreditation_id: UUID,
    payload: PackRenderRequest,
    session: Session,
    org_id: VerifiedOrg,
) -> AccreditationPackOut:
    try:
        return await service.render_pack(session, org_id, accreditation_id, payload)
    except service.AccreditationError as exc:
        raise _http(exc) from exc


@router.get("/{accreditation_id}/packs", response_model=list[AccreditationPackOut])
async def list_packs(
    accreditation_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> list[AccreditationPackOut]:
    return await service.list_packs(session, org_id, accreditation_id)


@router.get("/{accreditation_id}/transitions", response_model=list[TransitionOut])
async def list_transitions(
    accreditation_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> list[TransitionOut]:
    return await service.list_transition_history(session, org_id, accreditation_id)
