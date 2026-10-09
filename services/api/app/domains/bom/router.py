"""BOM HTTP handlers. Thin by rule — every one delegates immediately."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import Session, VerifiedOrg
from app.api.route import TransactionalRoute
from app.domains.bom import service
from app.domains.bom.schemas import BomPage, ComponentKind

router = APIRouter(route_class=TransactionalRoute)

_STATUS_FOR: dict[type[Exception], int] = {
    service.BomAgentNotFoundError: status.HTTP_404_NOT_FOUND,
    service.BomVersionNotFoundError: status.HTTP_404_NOT_FOUND,
}


def _http(exc: service.BomError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST),
        detail=str(exc),
    )


@router.get("/agents/{agent_id}/bom", response_model=BomPage, summary="BOM for current version")
async def get_agent_bom(agent_id: UUID, session: Session, org_id: VerifiedOrg) -> BomPage:
    try:
        return await service.get_bom(session, org_id, agent_id=agent_id)
    except service.BomError as exc:
        raise _http(exc) from exc


@router.get("/versions/{version_id}/bom", response_model=BomPage, summary="BOM for one version")
async def get_version_bom(version_id: UUID, session: Session, org_id: VerifiedOrg) -> BomPage:
    try:
        return await service.get_bom(session, org_id, version_id=version_id)
    except service.BomError as exc:
        raise _http(exc) from exc


@router.get("/-/usage", summary="Which agents depend on a named component")
async def find_usage(
    session: Session,
    org_id: VerifiedOrg,
    kind: Annotated[ComponentKind, Query()],
    name: Annotated[str, Query(min_length=1, max_length=512)],
) -> list[dict[str, object]]:
    return await service.find_agents_using(session, org_id, kind, name)
