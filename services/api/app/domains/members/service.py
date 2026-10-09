"""Member, identity and team behaviour.

This domain owns *who exists*. It deliberately owns none of *what they may do*: that is
`app/domains/access`, and keeping the split means a directory sync cannot quietly widen
anybody's permissions as a side effect of updating a display name.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.access import service as access_service
from app.domains.members import repository as repo
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
    TeamSummary,
    TeamUpdate,
)


class MembersError(Exception):
    """Base class so the router can map one exception family."""


class MemberNotFoundError(MembersError):
    pass


class DuplicateMemberError(MembersError):
    pass


class TeamNotFoundError(MembersError):
    pass


class DuplicateTeamError(MembersError):
    pass


class IdentityConflictError(MembersError):
    pass


class InviteNotFoundError(MembersError):
    pass


class InviteNotClaimableError(MembersError):
    pass


class NotProvisionedError(MembersError):
    """A verified person with no member row, no invitation and no JIT permission.

    Distinct from :class:`InviteNotFoundError`, which is about one specific claim
    attempt. This is the ``not_provisioned`` reason in `design/02`: the credentials are
    good and there is simply nowhere for this person to land.
    """


class MembershipInactiveError(MembersError):
    """The person exists and was deliberately suspended or disabled.

    Kept apart from "no membership" because the two want opposite messages: one is an
    operator's decision and the other looks like a misconfiguration.
    """

    def __init__(self, status: str) -> None:
        self.status = status
        super().__init__(f"account membership is {status}")


class UnknownMemberReferenceError(MembersError):
    pass


async def invite_member(
    session: AsyncSession,
    org_id: UUID,
    payload: MemberInvite,
    *,
    invited_by: str,
) -> MemberSummary:
    """Create a member in ``invited`` state, optionally seeding teams and roles.

    An invite is not an identity. The member cannot act until an IdP subject binds to
        them, which is what makes the invite safe to hand to an account admin rather than
        reserving it for an identity admin.
    """
    existing = await repo.get_member_by_email(session, org_id, payload.email)
    if existing is not None:
        raise DuplicateMemberError(f"{payload.email} is already a member of this account")

    if (
        payload.primary_team_id is not None
        and await repo.get_team(session, org_id, payload.primary_team_id) is None
    ):
        raise TeamNotFoundError(f"team {payload.primary_team_id} does not exist")

    try:
        member = await repo.insert_member(
            session,
            org_id,
            {
                "email": payload.email,
                "display_name": payload.display_name,
                "status": MemberStatus.INVITED.value,
                "job_title": payload.job_title,
                "timezone": payload.timezone,
                "avatar_tone": payload.avatar_tone.value,
                "primary_team_id": payload.primary_team_id,
                "invited_by": invited_by,
            },
        )
    except IntegrityError as exc:
        raise DuplicateMemberError(f"{payload.email} is already a member") from exc

    for team_id in payload.team_ids:
        if await repo.get_team(session, org_id, team_id) is None:
            raise TeamNotFoundError(f"team {team_id} does not exist")
        await repo.add_team_members(
            session, org_id, team_id, [member.id], is_lead=False, added_by=invited_by
        )

    for role_key in payload.role_keys:
        await access_service.grant_role(
            session,
            org_id,
            subject_kind="member",
            subject_id=member.id,
            role_key=role_key,
            scope_kind="account",
            scope_id=None,
            granted_by=invited_by,
            reason="seeded at invite",
        )

    return MemberSummary(
        member=MemberOut.model_validate(member),
        team_names=[],
        role_keys=sorted(payload.role_keys),
        identity_count=0,
        mfa_verified=False,
    )


async def get_member(session: AsyncSession, org_id: UUID, member_id: UUID) -> MemberOut:
    member = await repo.get_member(session, org_id, member_id)
    if member is None:
        raise MemberNotFoundError(f"member {member_id} does not exist")
    return MemberOut.model_validate(member)


async def update_member(
    session: AsyncSession,
    org_id: UUID,
    member_id: UUID,
    payload: MemberUpdate,
) -> MemberOut:
    values = payload.model_dump(exclude_unset=True)
    if not values:
        return await get_member(session, org_id, member_id)

    if "avatar_tone" in values and values["avatar_tone"] is not None:
        values["avatar_tone"] = values["avatar_tone"].value

    # `disabled_at` is not a field the caller sets. The check constraint requires it to
    # track `status`, and the repository stamps it from the database clock so two API
    # processes with skewed clocks cannot disagree about when somebody lost access.
    if "status" in values and values["status"] is not None:
        status = values["status"]
        values["status"] = status.value if isinstance(status, MemberStatus) else str(status)

    if (
        values.get("primary_team_id") is not None
        and await repo.get_team(session, org_id, values["primary_team_id"]) is None
    ):
        raise TeamNotFoundError(f"team {values['primary_team_id']} does not exist")

    updated = await repo.update_member(session, org_id, member_id, values)
    if updated is None:
        raise MemberNotFoundError(f"member {member_id} does not exist")
    return MemberOut.model_validate(updated)


async def list_members(
    session: AsyncSession,
    org_id: UUID,
    *,
    limit: int,
    offset: int,
    query: str | None = None,
    status: MemberStatus | None = None,
    team_id: UUID | None = None,
) -> MemberPage:
    rows, total = await repo.list_members(
        session,
        org_id,
        limit=limit,
        offset=offset,
        query=query,
        status=status.value if status else None,
        team_id=team_id,
    )
    return MemberPage(
        items=[
            MemberSummary(
                member=MemberOut.model_validate(member),
                team_names=team_names,
                role_keys=role_keys,
                identity_count=identity_count,
                mfa_verified=mfa,
            )
            for member, team_names, role_keys, identity_count, mfa in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


async def bind_identity(
    session: AsyncSession,
    org_id: UUID,
    member_id: UUID,
    payload: IdentityBind,
) -> IdentityOut:
    """Bind a verified IdP subject to a member.

    The uniqueness index is partial on live rows, so a revoked binding does not block a
    re-bind, and a subject already live somewhere else raises rather than silently
    moving. Which member an audit row points at must not depend on write ordering.
    """
    if await repo.get_member(session, org_id, member_id) is None:
        raise MemberNotFoundError(f"member {member_id} does not exist")

    try:
        identity = await repo.insert_identity(
            session,
            org_id,
            {
                "member_id": member_id,
                "issuer": payload.issuer,
                "subject": payload.subject,
                "email_verified": payload.email_verified,
                "mfa_verified": payload.mfa_verified,
                "directory_groups": list(dict.fromkeys(payload.directory_groups)),
            },
        )
    except IntegrityError as exc:
        raise IdentityConflictError(
            "that identity is already bound; revoke the existing binding first"
        ) from exc

    return IdentityOut.model_validate(identity)


async def list_identities(
    session: AsyncSession,
    org_id: UUID,
    member_id: UUID,
) -> list[IdentityOut]:
    if await repo.get_member(session, org_id, member_id) is None:
        raise MemberNotFoundError(f"member {member_id} does not exist")
    rows = await repo.list_identities(session, org_id, member_id)
    return [IdentityOut.model_validate(row) for row in rows]


async def revoke_identity(session: AsyncSession, org_id: UUID, identity_id: UUID) -> None:
    if not await repo.revoke_identity(session, org_id, identity_id):
        raise MemberNotFoundError(f"identity {identity_id} is not bound")


async def create_team(
    session: AsyncSession,
    org_id: UUID,
    payload: TeamCreate,
) -> TeamOut:
    if (
        payload.parent_team_id is not None
        and await repo.get_team(session, org_id, payload.parent_team_id) is None
    ):
        raise TeamNotFoundError(f"team {payload.parent_team_id} does not exist")

    try:
        team = await repo.insert_team(
            session,
            org_id,
            {
                "slug": payload.slug,
                "name": payload.name,
                "description": payload.description,
                "parent_team_id": payload.parent_team_id,
                "source": payload.source.value,
                "directory_group_id": payload.directory_group_id,
            },
        )
    except IntegrityError as exc:
        raise DuplicateTeamError(f"team slug {payload.slug!r} is already used") from exc

    return TeamOut.model_validate(team)


async def update_team(
    session: AsyncSession,
    org_id: UUID,
    team_id: UUID,
    payload: TeamUpdate,
) -> TeamOut:
    values = payload.model_dump(exclude_unset=True)
    if not values:
        team = await repo.get_team(session, org_id, team_id)
        if team is None:
            raise TeamNotFoundError(f"team {team_id} does not exist")
        return TeamOut.model_validate(team)

    if values.get("parent_team_id") is not None:
        if values["parent_team_id"] == team_id:
            raise UnknownMemberReferenceError("a team cannot be its own parent")
        if await repo.get_team(session, org_id, values["parent_team_id"]) is None:
            raise TeamNotFoundError(f"team {values['parent_team_id']} does not exist")

    updated = await repo.update_team(session, org_id, team_id, values)
    if updated is None:
        raise TeamNotFoundError(f"team {team_id} does not exist")
    return TeamOut.model_validate(updated)


async def list_teams(
    session: AsyncSession,
    org_id: UUID,
    *,
    limit: int,
    offset: int,
) -> TeamPage:
    rows, total = await repo.list_teams(session, org_id, limit=limit, offset=offset)
    return TeamPage(
        items=[
            TeamSummary(
                team=TeamOut.model_validate(team),
                member_count=member_count,
                lead_names=lead_names,
            )
            for team, member_count, lead_names in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


async def add_team_members(
    session: AsyncSession,
    org_id: UUID,
    team_id: UUID,
    payload: TeamMembershipChange,
    *,
    added_by: str,
) -> int:
    if await repo.get_team(session, org_id, team_id) is None:
        raise TeamNotFoundError(f"team {team_id} does not exist")
    if not await repo.members_exist(session, org_id, payload.member_ids):
        raise UnknownMemberReferenceError("one or more members do not exist in this account")

    return await repo.add_team_members(
        session,
        org_id,
        team_id,
        payload.member_ids,
        is_lead=payload.is_lead,
        added_by=added_by,
    )


async def remove_team_members(
    session: AsyncSession,
    org_id: UUID,
    team_id: UUID,
    payload: TeamMembershipChange,
) -> int:
    if await repo.get_team(session, org_id, team_id) is None:
        raise TeamNotFoundError(f"team {team_id} does not exist")
    return await repo.remove_team_members(session, org_id, team_id, payload.member_ids)


async def profile(session: AsyncSession, org_id: UUID, member_id: UUID) -> MemberProfile:
    """The signed-in person's own page, assembled server-side in one round trip."""
    member = await repo.get_member(session, org_id, member_id)
    if member is None:
        raise MemberNotFoundError(f"member {member_id} does not exist")

    identities = await repo.list_identities(session, org_id, member_id)
    teams = await repo.teams_for_member(session, org_id, member_id)
    decision = await access_service.effective_access(session, org_id, member_id)
    account_name = await repo.get_account_name(session, org_id)
    if account_name is None:
        raise MemberNotFoundError("account does not exist")

    return MemberProfile(
        account_name=account_name,
        member=MemberOut.model_validate(member),
        identities=[IdentityOut.model_validate(row) for row in identities],
        teams=[TeamOut.model_validate(team) for team in teams],
        role_keys=decision.role_keys,
        permissions=decision.permissions,
    )


async def claim_invite(
    session: AsyncSession,
    org_id: UUID,
    *,
    issuer: str,
    subject: str,
    email: str,
    email_verified: bool,
    mfa_verified: bool,
    directory_groups: list[str],
) -> MemberProfile:
    """Activate an invited employee after their first verified directory sign-in.

    The tenant was already resolved from the token's Entra ``tid`` binding. Within that
    tenant, the email must exactly match a pending invitation; an arbitrary authenticated
    employee is never auto-enrolled. The immutable issuer/subject pair becomes the identity
    used on every later request, so email changes do not change who audit records name.
    """
    existing = await repo.find_identity(session, issuer, subject)
    if existing is not None:
        if existing.org_id != org_id:
            raise IdentityConflictError("that directory identity belongs to another account")
        # Re-activation is also the repair path for an account whose owner was never
        # granted anything: signing in again is the one action a locked-out first
        # employee can still take.
        await access_service.bootstrap_account_owner(
            session, org_id, existing.member_id, granted_by=f"activation:{issuer}"
        )
        return await profile(session, org_id, existing.member_id)

    member = await repo.get_member_by_email(session, org_id, email)
    if member is None:
        raise InviteNotFoundError("no pending invitation matches this directory account")
    if member.status != MemberStatus.INVITED.value:
        raise InviteNotClaimableError("this member is not awaiting directory activation")

    try:
        identity = await repo.insert_identity(
            session,
            org_id,
            {
                "member_id": member.id,
                "issuer": issuer,
                "subject": subject,
                "email_verified": email_verified,
                "mfa_verified": mfa_verified,
                "directory_groups": list(dict.fromkeys(directory_groups)),
            },
        )
    except IntegrityError as exc:
        raise IdentityConflictError("that directory identity is already bound") from exc

    activated = await repo.update_member(
        session,
        org_id,
        member.id,
        {"status": MemberStatus.ACTIVE.value},
    )
    if activated is None:
        raise MemberNotFoundError(f"member {member.id} does not exist")
    await access_service.bootstrap_account_owner(
        session, org_id, member.id, granted_by=f"activation:{issuer}"
    )
    await repo.record_login(session, org_id, identity.id)
    await repo.touch_last_seen(session, org_id, member.id)
    return await profile(session, org_id, member.id)


async def resolve_directory_login(
    session: AsyncSession,
    org_id: UUID,
    *,
    issuer: str,
    subject: str,
    email: str | None,
    email_verified: bool,
    mfa_verified: bool,
    directory_groups: list[str],
    onboarding_mode: str,
    allow_first_owner_bootstrap: bool = False,
) -> MemberProfile:
    """Turn a verified set of provider claims into a member of this account.

    The resolver from `design/02`, and the only path console sign-in takes. It is
    idempotent by construction: the second login of the same person finds the identity
    row written by the first and returns without inserting anything.

    The order matters. Subject first, because that is the stable key and an email change
    must not create a second member. Email second, and only when the provider said it is
    verified — an unverified email is an attacker-chosen string, and matching one against
    a pending invitation would hand the invitation to whoever asked for it. Provisioning
    last, and only when the provider is configured to allow it.

    Raises rather than returning a sentinel, because every failure here is a different
    message on the login screen and collapsing them into ``None`` would lose that.
    """
    identity = await repo.find_identity(session, issuer, subject)
    if identity is not None:
        if identity.org_id != org_id:
            raise IdentityConflictError("that directory identity belongs to another account")
        member = await repo.get_member(session, org_id, identity.member_id)
        if member is None:
            raise MemberNotFoundError(f"member {identity.member_id} does not exist")
        _refuse_inactive(member.status)
        # Also the repair path for an account whose owner was never granted anything:
        # signing in again is the one action a locked-out first employee can take.
        await access_service.bootstrap_account_owner(
            session, org_id, member.id, granted_by=f"login:{issuer}"
        )
        await repo.record_login(session, org_id, identity.id)
        await repo.touch_last_seen(session, org_id, member.id)
        return await profile(session, org_id, member.id)

    if email is None or not email_verified:
        raise NotProvisionedError("the provider did not confirm an email address for this sign-in")

    member = await repo.get_member_by_email(session, org_id, email)
    if member is not None:
        _refuse_inactive(member.status)
        return await _bind_identity(
            session,
            org_id,
            member_id=member.id,
            was_invited=member.status == MemberStatus.INVITED.value,
            issuer=issuer,
            subject=subject,
            email_verified=email_verified,
            mfa_verified=mfa_verified,
            directory_groups=directory_groups,
        )

    if onboarding_mode == "jit":
        provisioned = await repo.insert_member(
            session,
            org_id,
            _new_member_row(email, invited_by=f"jit:{issuer}", job_title=None),
        )
    elif allow_first_owner_bootstrap and not await repo.has_live_identity(session, org_id):
        # A clean development database has an organisation and intentionally no fixture
        # users. Let the first sign-in become its owner so resets are deterministic and
        # never need an ad-hoc SQL bind. Guarded twice: the provider row must be of kind
        # `development`, and the account must have nobody who can already sign in.
        provisioned = await repo.insert_member(
            session,
            org_id,
            _new_member_row(
                email,
                invited_by=f"development:{issuer}",
                job_title="Development account owner",
            ),
        )
    else:
        raise NotProvisionedError("no membership or invitation exists for this person")

    return await _bind_identity(
        session,
        org_id,
        member_id=provisioned.id,
        was_invited=False,
        issuer=issuer,
        subject=subject,
        email_verified=email_verified,
        mfa_verified=mfa_verified,
        directory_groups=directory_groups,
    )


def _refuse_inactive(status: str) -> None:
    if status in {MemberStatus.SUSPENDED.value, MemberStatus.DISABLED.value}:
        raise MembershipInactiveError(status)


def _new_member_row(email: str, *, invited_by: str, job_title: str | None) -> dict[str, Any]:
    return {
        "email": email,
        "display_name": email.split("@", 1)[0],
        "status": MemberStatus.ACTIVE.value,
        "job_title": job_title,
        "timezone": "UTC",
        "avatar_tone": "default",
        "primary_team_id": None,
        "invited_by": invited_by,
    }


async def _bind_identity(
    session: AsyncSession,
    org_id: UUID,
    *,
    member_id: UUID,
    was_invited: bool,
    issuer: str,
    subject: str,
    email_verified: bool,
    mfa_verified: bool,
    directory_groups: list[str],
) -> MemberProfile:
    """Attach an IdP subject to an existing member and mark the login."""
    try:
        identity = await repo.insert_identity(
            session,
            org_id,
            {
                "member_id": member_id,
                "issuer": issuer,
                "subject": subject,
                "email_verified": email_verified,
                "mfa_verified": mfa_verified,
                "directory_groups": list(dict.fromkeys(directory_groups)),
            },
        )
    except IntegrityError as exc:
        raise IdentityConflictError("that directory identity is already bound") from exc

    if was_invited:
        activated = await repo.update_member(
            session, org_id, member_id, {"status": MemberStatus.ACTIVE.value}
        )
        if activated is None:
            raise MemberNotFoundError(f"member {member_id} does not exist")

    await access_service.bootstrap_account_owner(
        session, org_id, member_id, granted_by=f"activation:{issuer}"
    )
    await repo.record_login(session, org_id, identity.id)
    await repo.touch_last_seen(session, org_id, member_id)
    return await profile(session, org_id, member_id)


async def member_by_id(session: AsyncSession, org_id: UUID, member_id: UUID) -> MemberOut | None:
    """The member a console session names.

    A cookie session already knows *which member*, because that was decided when it was
    created — so the request pipeline reads by id rather than re-running the identity
    lookup. Status is still read fresh on every request, which is what makes a suspension
    take effect on the suspended person's next click rather than when their session ends.
    """
    row = await repo.get_member(session, org_id, member_id)
    return MemberOut.model_validate(row) if row is not None else None


async def member_for_identity(
    session: AsyncSession,
    org_id: UUID,
    issuer: str,
    subject: str,
) -> MemberOut | None:
    """The member a verified IdP subject resolves to within this account.

    Two lookups rather than a join, because the identity lookup is intentionally not
    org-scoped — it is the one query that spans tenants, and the ``org_id`` comparison
    below is what confines the answer to the account the request claims to act on. A
    subject bound in a different account resolves to ``None`` here, which the caller
    turns into a 403.

    Reads only. This runs on every authorized request, so stamping ``last_login_at`` here
    would mean one UPDATE per request against the same row for the same person — the
    row-contention shape that shows up as lock waits long before anything else does.
    Session start records that instead, via :func:`record_session_start`.
    """
    identity = await repo.find_identity(session, issuer, subject)
    if identity is None or identity.org_id != org_id:
        return None

    member = await repo.get_member(session, org_id, identity.member_id)
    if member is None:
        return None

    return MemberOut.model_validate(member)


async def record_session_start(
    session: AsyncSession,
    org_id: UUID,
    issuer: str,
    subject: str,
) -> None:
    """Stamp login and last-seen once, at the start of a console session.

    Called from the console's own bootstrap call, not from the auth dependency — see
    :func:`member_for_identity` for why that distinction is load-bearing.
    """
    identity = await repo.find_identity(session, issuer, subject)
    if identity is None or identity.org_id != org_id:
        return
    await repo.record_login(session, org_id, identity.id)
    await repo.touch_last_seen(session, org_id, identity.member_id)


async def resolve_member_for_identity(
    session: AsyncSession,
    issuer: str,
    subject: str,
) -> tuple[UUID, UUID] | None:
    """``(org_id, member_id)`` for a verified subject, or ``None`` if unbound.

    Used by the request pipeline to turn a token into an account member. Needs an admin
    session because it runs before any tenant is known.
    """
    identity = await repo.find_identity(session, issuer, subject)
    if identity is None:
        return None
    return identity.org_id, identity.member_id
