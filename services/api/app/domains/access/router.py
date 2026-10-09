"""Roles, grants and access requests."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import (
    CurrentMember,
    PermissionGuard,
    Session,
    VerifiedOrg,
    WriteGuard,
)
from app.api.route import TransactionalRoute
from app.domains.access import service
from app.domains.access.schemas import (
    AccessRequestCreate,
    AccessRequestDecision,
    AccessRequestOut,
    AccessRequestPage,
    EffectiveAccess,
    GrantCreate,
    GrantOut,
    GrantPage,
    RequestState,
    RoleCreate,
    RoleOut,
    SubjectKind,
)

router = APIRouter(route_class=TransactionalRoute)

_STATUS_FOR: dict[type[Exception], int] = {
    service.RoleNotFoundError: status.HTTP_404_NOT_FOUND,
    service.GrantNotFoundError: status.HTTP_404_NOT_FOUND,
    service.RequestNotFoundError: status.HTTP_404_NOT_FOUND,
    service.DuplicateRoleError: status.HTTP_409_CONFLICT,
    service.DuplicateGrantError: status.HTTP_409_CONFLICT,
    service.RequestAlreadyDecidedError: status.HTTP_409_CONFLICT,
    service.ScopeNotAssignableError: status.HTTP_422_UNPROCESSABLE_CONTENT,
    service.SelfApprovalError: status.HTTP_403_FORBIDDEN,
}


def _http(exc: service.AccessError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST),
        detail=str(exc),
    )


@router.get(
    "/roles",
    response_model=list[RoleOut],
    summary="List built-in and account-defined roles",
    dependencies=[PermissionGuard("access:read")],
)
async def list_roles(session: Session, org_id: VerifiedOrg) -> list[RoleOut]:
    return await service.list_roles(session, org_id)


@router.post(
    "/roles",
    response_model=RoleOut,
    status_code=status.HTTP_201_CREATED,
    summary="Define an account-specific role",
    dependencies=[PermissionGuard("access:write"), WriteGuard],
)
async def create_role(
    payload: RoleCreate,
    session: Session,
    org_id: VerifiedOrg,
) -> RoleOut:
    try:
        return await service.create_role(session, org_id, payload)
    except service.AccessError as exc:
        raise _http(exc) from exc


@router.get(
    "/grants",
    response_model=GrantPage,
    summary="List scoped role grants",
    dependencies=[PermissionGuard("access:read")],
)
async def list_grants(
    session: Session,
    org_id: VerifiedOrg,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    subject_kind: SubjectKind | None = None,
    subject_id: UUID | None = None,
    include_revoked: bool = False,
) -> GrantPage:
    return await service.list_grants(
        session,
        org_id,
        limit=limit,
        offset=offset,
        subject_kind=subject_kind,
        subject_id=subject_id,
        include_revoked=include_revoked,
    )


@router.post(
    "/grants",
    response_model=GrantOut,
    status_code=status.HTTP_201_CREATED,
    summary="Grant a role at a scope",
    dependencies=[PermissionGuard("access:write"), WriteGuard],
)
async def create_grant(
    payload: GrantCreate,
    session: Session,
    org_id: VerifiedOrg,
    member: CurrentMember,
) -> GrantOut:
    try:
        return await service.create_grant(session, org_id, payload, granted_by=member.label)
    except service.AccessError as exc:
        raise _http(exc) from exc


@router.delete(
    "/grants/{grant_id}",
    response_model=GrantOut,
    summary="Revoke a grant",
    dependencies=[PermissionGuard("access:write"), WriteGuard],
)
async def revoke_grant(
    grant_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    member: CurrentMember,
) -> GrantOut:
    try:
        return await service.revoke_grant(session, org_id, grant_id, revoked_by=member.label)
    except service.AccessError as exc:
        raise _http(exc) from exc


@router.get(
    "/effective/{member_id}",
    response_model=EffectiveAccess,
    summary="Flattened permissions for one member",
    dependencies=[PermissionGuard("access:read")],
)
async def effective_access(
    member_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> EffectiveAccess:
    return await service.effective_access(session, org_id, member_id)


@router.get(
    "/me",
    response_model=EffectiveAccess,
    summary="The caller's own permissions",
)
async def my_access(
    session: Session,
    org_id: VerifiedOrg,
    member: CurrentMember,
) -> EffectiveAccess:
    """Deliberately unguarded beyond authentication.

    Anybody may ask what they themselves can do — the console needs it to decide which
    navigation to render, and refusing it would mean showing every user every destination
    and letting them discover the 403s by clicking.
    """
    return await service.effective_access(session, org_id, member.member_id)


@router.get(
    "/requests",
    response_model=AccessRequestPage,
    summary="List access requests",
    dependencies=[PermissionGuard("access:read")],
)
async def list_requests(
    session: Session,
    org_id: VerifiedOrg,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    state: RequestState | None = None,
) -> AccessRequestPage:
    return await service.list_requests(session, org_id, limit=limit, offset=offset, state=state)


@router.get(
    "/requests/mine",
    response_model=AccessRequestPage,
    summary="The caller's own access requests",
)
async def my_requests(
    session: Session,
    org_id: VerifiedOrg,
    member: CurrentMember,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> AccessRequestPage:
    return await service.list_requests(
        session,
        org_id,
        limit=limit,
        offset=offset,
        requester_member_id=member.member_id,
    )


@router.post(
    "/requests",
    response_model=AccessRequestOut,
    status_code=status.HTTP_201_CREATED,
    summary="Request time-bound elevation",
    dependencies=[WriteGuard],
)
async def create_request(
    payload: AccessRequestCreate,
    session: Session,
    org_id: VerifiedOrg,
    member: CurrentMember,
) -> AccessRequestOut:
    """Any authenticated member may ask. Asking is not access.

    Guarded by nothing but authentication on purpose: a request the requester cannot make
    is a request they will make by email instead, and then no record of it exists.
    """
    try:
        return await service.create_request(
            session, org_id, payload, requester_member_id=member.member_id
        )
    except service.AccessError as exc:
        raise _http(exc) from exc


@router.post(
    "/requests/{request_id}/decision",
    response_model=AccessRequestOut,
    summary="Approve or deny an access request",
    dependencies=[PermissionGuard("access:approve"), WriteGuard],
)
async def decide_request(
    request_id: UUID,
    payload: AccessRequestDecision,
    session: Session,
    org_id: VerifiedOrg,
    member: CurrentMember,
) -> AccessRequestOut:
    try:
        return await service.decide_request(
            session,
            org_id,
            request_id,
            payload,
            decided_by=member.label,
            decider_member_id=member.member_id,
        )
    except service.AccessError as exc:
        raise _http(exc) from exc
