"""Provider connections: registration, rotation, grants and gateway resolution."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import (
    CollectorAuth,
    CurrentMember,
    PermissionGuard,
    Session,
    VerifiedOrg,
    WorkloadSession,
    WriteGuard,
    enforce_collector,
)
from app.api.route import TransactionalRoute
from app.domains.connections import service
from app.domains.connections.schemas import (
    ConnectionCreate,
    ConnectionGrantCreate,
    ConnectionGrantOut,
    ConnectionOut,
    ConnectionPage,
    ConnectionRotate,
    ConnectionUpdate,
    ProviderKind,
    ResolvedConnection,
    SecretVersionOut,
)

router = APIRouter(route_class=TransactionalRoute)

_STATUS_FOR: dict[type[Exception], int] = {
    service.ConnectionNotFoundError: status.HTTP_404_NOT_FOUND,
    service.GrantNotFoundError: status.HTTP_404_NOT_FOUND,
    service.DuplicateConnectionError: status.HTTP_409_CONFLICT,
    service.DuplicateGrantError: status.HTTP_409_CONFLICT,
    service.EnvironmentNotEnabledError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    service.NoGrantedConnectionError: status.HTTP_403_FORBIDDEN,
}


def _http(exc: service.ConnectionsError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST),
        detail=str(exc),
    )


@router.get(
    "",
    response_model=ConnectionPage,
    summary="List provider connections",
    dependencies=[PermissionGuard("connection:read")],
)
async def list_connections(
    session: Session,
    org_id: VerifiedOrg,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    provider_kind: ProviderKind | None = None,
    include_disabled: bool = False,
) -> ConnectionPage:
    return await service.list_connections(
        session,
        org_id,
        limit=limit,
        offset=offset,
        provider_kind=provider_kind,
        include_disabled=include_disabled,
    )


@router.post(
    "",
    response_model=ConnectionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Register a provider connection",
    dependencies=[PermissionGuard("connection:write"), WriteGuard],
)
async def create_connection(
    payload: ConnectionCreate,
    session: Session,
    org_id: VerifiedOrg,
    member: CurrentMember,
) -> ConnectionOut:
    """Records a reference to the customer's own credential, never the credential.

    ``credential_ref`` names a secret in the customer's provider — a Vault path, a KMS
    key id, or an env var in a local install. Whoever calls this does not need to be able
    to read that secret, which is why ``connection:write`` and ``payload:reveal`` are
    separate permissions.
    """
    try:
        return await service.create_connection(
            session,
            org_id,
            payload,
            created_by=member.label,
            created_by_member_id=member.member_id,
        )
    except service.ConnectionsError as exc:
        raise _http(exc) from exc


@router.get(
    "/{connection_id}",
    response_model=ConnectionOut,
    summary="One connection",
    dependencies=[PermissionGuard("connection:read")],
)
async def get_connection(
    connection_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> ConnectionOut:
    try:
        return await service.get_connection(session, org_id, connection_id)
    except service.ConnectionsError as exc:
        raise _http(exc) from exc


@router.patch(
    "/{connection_id}",
    response_model=ConnectionOut,
    summary="Update a connection",
    dependencies=[PermissionGuard("connection:write"), WriteGuard],
)
async def update_connection(
    connection_id: UUID,
    payload: ConnectionUpdate,
    session: Session,
    org_id: VerifiedOrg,
) -> ConnectionOut:
    try:
        return await service.update_connection(session, org_id, connection_id, payload)
    except service.ConnectionsError as exc:
        raise _http(exc) from exc


@router.post(
    "/{connection_id}/rotate",
    response_model=SecretVersionOut,
    status_code=status.HTTP_201_CREATED,
    summary="Rotate to a new secret version",
    dependencies=[PermissionGuard("connection:rotate"), WriteGuard],
)
async def rotate(
    connection_id: UUID,
    payload: ConnectionRotate,
    session: Session,
    org_id: VerifiedOrg,
    member: CurrentMember,
) -> SecretVersionOut:
    try:
        return await service.rotate(
            session, org_id, connection_id, payload, rotated_by=member.label
        )
    except service.ConnectionsError as exc:
        raise _http(exc) from exc


@router.get(
    "/{connection_id}/versions",
    response_model=list[SecretVersionOut],
    summary="Secret version history",
    dependencies=[PermissionGuard("connection:read")],
)
async def list_versions(
    connection_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> list[SecretVersionOut]:
    try:
        return await service.list_versions(session, org_id, connection_id)
    except service.ConnectionsError as exc:
        raise _http(exc) from exc


@router.get(
    "/{connection_id}/grants",
    response_model=list[ConnectionGrantOut],
    summary="Who may use this connection",
    dependencies=[PermissionGuard("connection:read")],
)
async def list_grants(
    connection_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> list[ConnectionGrantOut]:
    try:
        return await service.list_grants(session, org_id, connection_id)
    except service.ConnectionsError as exc:
        raise _http(exc) from exc


@router.post(
    "/{connection_id}/grants",
    response_model=ConnectionGrantOut,
    status_code=status.HTTP_201_CREATED,
    summary="Grant an agent, team or project use of a connection",
    dependencies=[PermissionGuard("connection:write"), WriteGuard],
)
async def grant_connection(
    connection_id: UUID,
    payload: ConnectionGrantCreate,
    session: Session,
    org_id: VerifiedOrg,
    member: CurrentMember,
) -> ConnectionGrantOut:
    try:
        return await service.grant_connection(
            session, org_id, connection_id, payload, granted_by=member.label
        )
    except service.ConnectionsError as exc:
        raise _http(exc) from exc


@router.delete(
    "/grants/{grant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a connection grant",
    dependencies=[PermissionGuard("connection:write"), WriteGuard],
)
async def revoke_grant(
    grant_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> None:
    try:
        await service.revoke_grant(session, org_id, grant_id)
    except service.ConnectionsError as exc:
        raise _http(exc) from exc


@router.get(
    "/resolve/for-workload",
    response_model=list[ResolvedConnection],
    summary="Connections this workload may use (gateway path)",
)
async def resolve_for_workload(
    collector: CollectorAuth,
    session: WorkloadSession,
    provider_kind: ProviderKind | None = None,
) -> list[ResolvedConnection]:
    """The gateway's pre-flight question, answered for the *presented credential*.

    Every input except the optional provider filter comes from the verified credential:
    org, project, agent and environment. None of them are parameters, because a caller
    that could name its own agent id or environment here could borrow another agent's
    connections, or reach a production key with a development credential.
    """
    workload = enforce_collector(collector, scope="router:invoke", module="router")

    try:
        return await service.resolve(
            session,
            workload.org_id,
            agent_id=workload.agent_id,
            project_id=workload.project_id,
            team_id=None,
            environment=workload.environment.value,
            provider_kind=provider_kind,
        )
    except service.ConnectionsError as exc:
        raise _http(exc) from exc
