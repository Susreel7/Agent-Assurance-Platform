"""Registry HTTP handlers. Thin by rule — every one delegates immediately."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.api.deps import Session, VerifiedOrg, WriteEnabled
from app.api.route import TransactionalRoute
from app.domains.registry import service
from app.domains.registry.schemas import (
    AgentCreate,
    AgentDetail,
    AgentPage,
    AgentUpdate,
    AgentVersionOut,
    DriftReport,
    LifecycleState,
    OwnershipOut,
    OwnershipRole,
    OwnershipUpsert,
    VersionPublish,
)

router = APIRouter(route_class=TransactionalRoute)

_STATUS_FOR: dict[type[Exception], int] = {
    service.AgentNotFoundError: status.HTTP_404_NOT_FOUND,
    service.VersionNotFoundError: status.HTTP_404_NOT_FOUND,
    service.AgentUrnTakenError: status.HTTP_409_CONFLICT,
    service.SemverAlreadyPublishedError: status.HTTP_409_CONFLICT,
    service.InvalidDescriptorError: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def _http(exc: service.RegistryError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST),
        detail=str(exc),
    )


@router.post(
    "",
    response_model=AgentDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Register a governed agent identity",
)
async def create_agent(
    payload: AgentCreate,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> AgentDetail:
    try:
        return await service.create_agent(session, org_id, payload)
    except service.RegistryError as exc:
        raise _http(exc) from exc


@router.get("", response_model=AgentPage, summary="List agents")
async def list_agents(
    session: Session,
    org_id: VerifiedOrg,
    lifecycle_state: Annotated[list[LifecycleState] | None, Query(alias="lifecycle_state")] = None,
    search: Annotated[str | None, Query(max_length=128)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AgentPage:
    states = [s.value for s in lifecycle_state] if lifecycle_state else None
    items, total = await service.list_agents(
        session, org_id, lifecycle_states=states, search=search, limit=limit, offset=offset
    )
    return AgentPage(items=items, total=total, limit=limit, offset=offset)


@router.get("/{agent_id}", response_model=AgentDetail, summary="Get one agent")
async def get_agent(agent_id: UUID, session: Session, org_id: VerifiedOrg) -> AgentDetail:
    try:
        return await service.get_agent_detail(session, org_id, agent_id)
    except service.RegistryError as exc:
        raise _http(exc) from exc


@router.patch("/{agent_id}", response_model=AgentDetail, summary="Update agent metadata")
async def update_agent(
    agent_id: UUID,
    payload: AgentUpdate,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> AgentDetail:
    try:
        return await service.update_agent(session, org_id, agent_id, payload)
    except service.RegistryError as exc:
        raise _http(exc) from exc


# No DELETE. An agent that ever held an accredited version cannot vanish without
# orphaning approvals; set lifecycle_state to 'retired' instead.


@router.post(
    "/{agent_id}/versions",
    response_model=AgentVersionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Publish an immutable descriptor version",
)
async def publish_version(
    agent_id: UUID,
    payload: VersionPublish,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> AgentVersionOut:
    try:
        return await service.publish_version(session, org_id, agent_id, payload)
    except service.RegistryError as exc:
        raise _http(exc) from exc


@router.get(
    "/{agent_id}/versions",
    response_model=list[AgentVersionOut],
    summary="List published versions",
)
async def list_versions(
    agent_id: UUID, session: Session, org_id: VerifiedOrg
) -> list[AgentVersionOut]:
    try:
        return await service.list_agent_versions(session, org_id, agent_id)
    except service.RegistryError as exc:
        raise _http(exc) from exc


@router.get(
    "/{agent_id}/versions/{version_id}",
    response_model=AgentVersionOut,
    summary="Get one published version",
)
async def get_version(
    agent_id: UUID,
    version_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> AgentVersionOut:
    try:
        return await service.get_agent_version(session, org_id, agent_id, version_id)
    except service.RegistryError as exc:
        raise _http(exc) from exc


@router.put(
    "/{agent_id}/ownership",
    response_model=OwnershipOut,
    summary="Set the holder of an ownership role",
)
async def set_owner(
    agent_id: UUID,
    payload: OwnershipUpsert,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> OwnershipOut:
    try:
        return await service.set_owner(session, org_id, agent_id, payload)
    except service.RegistryError as exc:
        raise _http(exc) from exc


@router.delete(
    "/{agent_id}/ownership/{role}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="End an ownership role's validity window",
)
async def end_owner(
    agent_id: UUID,
    role: OwnershipRole,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> Response:
    try:
        await service.end_owner(session, org_id, agent_id, role.value)
    except service.RegistryError as exc:
        raise _http(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{agent_id}/drift", response_model=DriftReport, summary="Baseline vs current")
async def get_drift(agent_id: UUID, session: Session, org_id: VerifiedOrg) -> DriftReport:
    try:
        return await service.compute_drift(session, org_id, agent_id)
    except service.RegistryError as exc:
        raise _http(exc) from exc
