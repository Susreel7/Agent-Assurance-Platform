"""People, identities and teams."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, status

from app.api.deps import (
    Auth,
    CurrentMember,
    PermissionGuard,
    Session,
    VerifiedOrg,
    WriteGuard,
)
from app.api.route import TransactionalRoute
from app.domains.members import service
from app.domains.members.schemas import (
    IdentityBind,
    IdentityOut,
    MemberInvite,
    MemberOut,
    MemberPage,
    MemberProfile,
    MemberStatus,
    MemberSummary,
    MemberUpdate,
    TeamCreate,
    TeamMembershipChange,
    TeamOut,
    TeamPage,
    TeamUpdate,
)

router = APIRouter(route_class=TransactionalRoute)

_STATUS_FOR: dict[type[Exception], int] = {
    service.MemberNotFoundError: status.HTTP_404_NOT_FOUND,
    service.TeamNotFoundError: status.HTTP_404_NOT_FOUND,
    service.DuplicateMemberError: status.HTTP_409_CONFLICT,
    service.DuplicateTeamError: status.HTTP_409_CONFLICT,
    service.IdentityConflictError: status.HTTP_409_CONFLICT,
    service.InviteNotFoundError: status.HTTP_404_NOT_FOUND,
    service.InviteNotClaimableError: status.HTTP_409_CONFLICT,
    service.UnknownMemberReferenceError: status.HTTP_422_UNPROCESSABLE_CONTENT,
}


def _http(exc: service.MembersError) -> HTTPException:
    return HTTPException(
        status_code=_STATUS_FOR.get(type(exc), status.HTTP_400_BAD_REQUEST),
        detail=str(exc),
    )


@router.get(
    "",
    response_model=MemberPage,
    summary="List account members",
    dependencies=[PermissionGuard("member:read")],
)
async def list_members(
    session: Session,
    org_id: VerifiedOrg,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    q: Annotated[str | None, Query(max_length=256)] = None,
    member_status: MemberStatus | None = None,
    team_id: UUID | None = None,
) -> MemberPage:
    return await service.list_members(
        session,
        org_id,
        limit=limit,
        offset=offset,
        query=q,
        status=member_status,
        team_id=team_id,
    )


@router.post(
    "",
    response_model=MemberSummary,
    status_code=status.HTTP_201_CREATED,
    summary="Invite a member",
    dependencies=[PermissionGuard("member:write"), WriteGuard],
)
async def invite_member(
    payload: MemberInvite,
    session: Session,
    org_id: VerifiedOrg,
    member: CurrentMember,
) -> MemberSummary:
    try:
        return await service.invite_member(session, org_id, payload, invited_by=member.label)
    except service.MembersError as exc:
        raise _http(exc) from exc


@router.get(
    "/me",
    response_model=MemberProfile,
    summary="The caller's own profile",
)
async def my_profile(
    session: Session,
    org_id: VerifiedOrg,
    member: CurrentMember,
) -> MemberProfile:
    try:
        return await service.profile(session, org_id, member.member_id)
    except service.MembersError as exc:
        raise _http(exc) from exc


@router.post(
    "/me/activate",
    response_model=MemberProfile,
    summary="Claim a pending employee invitation after directory sign-in",
    dependencies=[WriteGuard],
)
async def activate_my_invite(
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
) -> MemberProfile:
    principal = auth.principal
    email = principal.email
    if email is None:
        preferred = auth.claims.get("preferred_username") or auth.claims.get("upn")
        email = preferred if isinstance(preferred, str) else None
    if email is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="directory token does not carry an employee email",
        )
    raw_groups = auth.claims.get("groups")
    groups = [str(value) for value in raw_groups] if isinstance(raw_groups, list) else []
    raw_amr = auth.claims.get("amr")
    methods = {str(value).lower() for value in raw_amr} if isinstance(raw_amr, list) else set()

    try:
        return await service.claim_invite(
            session,
            org_id,
            issuer=principal.issuer,
            subject=principal.subject,
            email=email.strip().lower(),
            email_verified=auth.claims.get("email_verified") is True,
            mfa_verified="mfa" in methods,
            directory_groups=groups,
        )
    except service.MembersError as exc:
        raise _http(exc) from exc


@router.post(
    "/me/session",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Record the start of a console session",
    dependencies=[WriteGuard],
)
async def start_session(
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: CurrentMember,
) -> None:
    """Stamps login and last-seen. Called once by the console after sign-in.

    Separate from the auth dependency deliberately: doing this per request would put one
        UPDATE against the same row on the path of every call the person makes.
    """
    await service.record_session_start(
        session, org_id, auth.principal.issuer, auth.principal.subject
    )


@router.patch(
    "/{member_id}",
    response_model=MemberOut,
    summary="Update a member",
    dependencies=[PermissionGuard("member:write"), WriteGuard],
)
async def update_member(
    member_id: UUID,
    payload: MemberUpdate,
    session: Session,
    org_id: VerifiedOrg,
) -> MemberOut:
    try:
        return await service.update_member(session, org_id, member_id, payload)
    except service.MembersError as exc:
        raise _http(exc) from exc


@router.get(
    "/{member_id}/identities",
    response_model=list[IdentityOut],
    summary="List a member's verified identities",
    dependencies=[PermissionGuard("member:read")],
)
async def list_identities(
    member_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> list[IdentityOut]:
    try:
        return await service.list_identities(session, org_id, member_id)
    except service.MembersError as exc:
        raise _http(exc) from exc


@router.post(
    "/{member_id}/identities",
    response_model=IdentityOut,
    status_code=status.HTTP_201_CREATED,
    summary="Bind an IdP subject to a member",
    dependencies=[PermissionGuard("member:write"), WriteGuard],
)
async def bind_identity(
    member_id: UUID,
    payload: IdentityBind,
    session: Session,
    org_id: VerifiedOrg,
) -> IdentityOut:
    """Requires ``member:write``, which only identity and account admins hold.

        The issuer and subject are supplied rather than taken from the caller's own token,
        because this is how a directory import binds somebody who has not signed in yet. That
    is also why it is one of the narrowest permissions in the model: whoever can call this
        can decide whose actions an audit row is attributed to.
    """
    try:
        return await service.bind_identity(session, org_id, member_id, payload)
    except service.MembersError as exc:
        raise _http(exc) from exc


@router.delete(
    "/identities/{identity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke an identity binding",
    dependencies=[PermissionGuard("member:write"), WriteGuard],
)
async def revoke_identity(
    identity_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> None:
    try:
        await service.revoke_identity(session, org_id, identity_id)
    except service.MembersError as exc:
        raise _http(exc) from exc


@router.get(
    "/teams/all",
    response_model=TeamPage,
    summary="List teams",
    dependencies=[PermissionGuard("team:read")],
)
async def list_teams(
    session: Session,
    org_id: VerifiedOrg,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> TeamPage:
    return await service.list_teams(session, org_id, limit=limit, offset=offset)


@router.post(
    "/teams",
    response_model=TeamOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a team",
    dependencies=[PermissionGuard("team:write"), WriteGuard],
)
async def create_team(
    payload: TeamCreate,
    session: Session,
    org_id: VerifiedOrg,
) -> TeamOut:
    try:
        return await service.create_team(session, org_id, payload)
    except service.MembersError as exc:
        raise _http(exc) from exc


@router.patch(
    "/teams/{team_id}",
    response_model=TeamOut,
    summary="Update a team",
    dependencies=[PermissionGuard("team:write"), WriteGuard],
)
async def update_team(
    team_id: UUID,
    payload: TeamUpdate,
    session: Session,
    org_id: VerifiedOrg,
) -> TeamOut:
    try:
        return await service.update_team(session, org_id, team_id, payload)
    except service.MembersError as exc:
        raise _http(exc) from exc


@router.post(
    "/teams/{team_id}/members",
    response_model=dict[str, int],
    summary="Add members to a team",
    dependencies=[PermissionGuard("team:write"), WriteGuard],
)
async def add_team_members(
    team_id: UUID,
    payload: TeamMembershipChange,
    session: Session,
    org_id: VerifiedOrg,
    member: CurrentMember,
) -> dict[str, int]:
    """Up to 500 members in one call, applied as a single upsert.

    Bulk on purpose: onboarding a department is one request, and a per-member endpoint
    would make the console issue hundreds of writes that can each fail separately.
    """
    try:
        changed = await service.add_team_members(
            session, org_id, team_id, payload, added_by=member.label
        )
    except service.MembersError as exc:
        raise _http(exc) from exc
    return {"changed": changed}


@router.post(
    "/teams/{team_id}/members/remove",
    response_model=dict[str, int],
    summary="Remove members from a team",
    dependencies=[PermissionGuard("team:write"), WriteGuard],
)
async def remove_team_members(
    team_id: UUID,
    payload: TeamMembershipChange,
    session: Session,
    org_id: VerifiedOrg,
) -> dict[str, int]:
    """POST rather than DELETE because it carries a body of up to 500 ids.

    A DELETE with a request body is legal but poorly supported by proxies and client
        libraries, and this is a bulk operation, not the removal of one addressable resource.
    """
    try:
        changed = await service.remove_team_members(session, org_id, team_id, payload)
    except service.MembersError as exc:
        raise _http(exc) from exc
    return {"changed": changed}
