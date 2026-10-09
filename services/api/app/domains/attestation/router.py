"""Attestation HTTP handlers."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from app.api.deps import Session, VerifiedOrg, WriteGuard
from app.api.route import TransactionalRoute
from app.domains.attestation import service
from app.domains.attestation.schemas import AttestationRunOut, AttestationRunRequest

router = APIRouter(route_class=TransactionalRoute)


class AttestationRunPage(BaseModel):
    items: list[AttestationRunOut]
    total: int
    limit: int
    offset: int


@router.get("/runs", response_model=AttestationRunPage)
async def list_runs(
    session: Session,
    org_id: VerifiedOrg,
    accreditation_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AttestationRunPage:
    items, total = await service.list_runs(
        session, org_id, accreditation_id=accreditation_id, limit=limit, offset=offset
    )
    return AttestationRunPage(items=items, total=total, limit=limit, offset=offset)


@router.post(
    "/-/run",
    response_model=AttestationRunOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[WriteGuard],
)
async def run_attestation(
    payload: AttestationRunRequest,
    session: Session,
    org_id: VerifiedOrg,
) -> AttestationRunOut:
    try:
        return await service.run_attestation(
            session,
            org_id,
            payload.accreditation_id,
            payload.trigger,
            payload.triggered_by,
        )
    except service.AttestationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/-/due", response_model=list[AttestationRunOut], dependencies=[WriteGuard])
async def run_due(
    session: Session,
    org_id: VerifiedOrg,
) -> list[AttestationRunOut]:
    return await service.schedule_due(session, org_id)
