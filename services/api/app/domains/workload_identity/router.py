"""Workload credential administration — human-authenticated only."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import (
    CollectorAuth,
    CurrentPrincipal,
    PermissionGuard,
    Session,
    VerifiedOrg,
    WorkloadSession,
    WriteEnabled,
)
from app.api.route import TransactionalRoute
from app.domains.workload_identity import service
from app.domains.workload_identity.schemas import (
    ProjectCreate,
    ProjectOut,
    ProjectPage,
    ProjectUpdate,
    WorkloadCredentialCreate,
    WorkloadCredentialCreated,
    WorkloadCredentialOut,
    WorkloadCredentialPage,
    WorkloadIntrospectionOut,
)

router = APIRouter(route_class=TransactionalRoute)

_STATUS_FOR: dict[type[Exception], int] = {
    service.ProjectNotFoundError: status.HTTP_404_NOT_FOUND,
    service.CredentialNotFoundError: status.HTTP_404_NOT_FOUND,
    service.InvalidAgentScopeError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    service.InvalidMemberScopeError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    service.CapturePolicyError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    service.ModuleEntitlementError: status.HTTP_403_FORBIDDEN,
    service.CredentialRevokedError: status.HTTP_409_CONFLICT,
}


def _http(exc: service.WorkloadIdentityError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST),
        detail=str(exc),
    )


@router.post(
    "/projects",
    response_model=ProjectOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a tenant-scoped project",
    dependencies=[PermissionGuard("project:write")],
)
async def create_project(
    payload: ProjectCreate,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> ProjectOut:
    return await service.create_project(session, org_id, payload)


@router.get(
    "/projects",
    response_model=ProjectPage,
    summary="List projects",
    dependencies=[PermissionGuard("project:read")],
)
async def list_projects(
    session: Session,
    org_id: VerifiedOrg,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ProjectPage:
    return await service.list_projects(session, org_id, limit=limit, offset=offset)


@router.patch(
    "/projects/{project_id}",
    response_model=ProjectOut,
    summary="Update a project",
    dependencies=[PermissionGuard("project:write")],
)
async def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> ProjectOut:
    try:
        return await service.update_project(session, org_id, project_id, payload)
    except service.ProjectNotFoundError as exc:
        raise _http(exc) from exc


@router.post(
    "",
    response_model=WorkloadCredentialCreated,
    status_code=status.HTTP_201_CREATED,
    summary="Issue a workload credential (secret shown once)",
    dependencies=[PermissionGuard("key:write")],
)
async def create_credential(
    payload: WorkloadCredentialCreate,
    session: Session,
    org_id: VerifiedOrg,
    principal: CurrentPrincipal,
    _: WriteEnabled,
) -> WorkloadCredentialCreated:
    try:
        return await service.create_credential(
            session, org_id, payload, created_by=principal.actor_ref
        )
    except service.WorkloadIdentityError as exc:
        raise _http(exc) from exc


@router.post(
    "/-/introspect",
    response_model=WorkloadIntrospectionOut,
    summary="Resolve the presented workload credential for an internal data service",
)
async def introspect_credential(
    session: WorkloadSession,
    collector: CollectorAuth,
) -> WorkloadIntrospectionOut:
    try:
        return await service.introspection_for_workload(session, collector.workload)
    except service.ProjectNotFoundError as exc:
        raise _http(exc) from exc


@router.get(
    "",
    response_model=WorkloadCredentialPage,
    summary="List workload credentials",
    dependencies=[PermissionGuard("key:read")],
)
async def list_credentials(
    session: Session,
    org_id: VerifiedOrg,
    project_id: Annotated[UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> WorkloadCredentialPage:
    return await service.list_credentials(
        session, org_id, project_id=project_id, limit=limit, offset=offset
    )


@router.get(
    "/{credential_id}",
    response_model=WorkloadCredentialOut,
    summary="Credential metadata (never includes the secret)",
    dependencies=[PermissionGuard("key:read")],
)
async def get_credential(
    credential_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> WorkloadCredentialOut:
    try:
        return await service.get_credential(session, org_id, credential_id)
    except service.CredentialNotFoundError as exc:
        raise _http(exc) from exc


@router.post(
    "/{credential_id}/rotate",
    response_model=WorkloadCredentialCreated,
    summary="Rotate secret — previous generation stops working immediately",
    dependencies=[PermissionGuard("key:write")],
)
async def rotate_credential(
    credential_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> WorkloadCredentialCreated:
    try:
        return await service.rotate_credential(session, org_id, credential_id)
    except service.WorkloadIdentityError as exc:
        raise _http(exc) from exc


@router.post(
    "/{credential_id}/revoke",
    response_model=WorkloadCredentialOut,
    summary="Revoke a credential",
    dependencies=[PermissionGuard("key:revoke")],
)
async def revoke_credential(
    credential_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> WorkloadCredentialOut:
    try:
        return await service.revoke_credential(session, org_id, credential_id)
    except service.CredentialNotFoundError as exc:
        raise _http(exc) from exc
