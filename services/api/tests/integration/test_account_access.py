"""Members, roles and grants against real Postgres.

The unit suite can check that `EffectiveAccess.allows` folds a permission set correctly.
It cannot check that the fold is fed by the right rows — that the partial unique index
lets a revoked grant be re-granted, that expiry is honoured without a sweep having run,
or that one account's grants never appear in another's. Those live in the database.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.access import service as access
from app.domains.access.schemas import (
    AccessRequestCreate,
    AccessRequestDecision,
    GrantCreate,
    RoleCreate,
    ScopeKind,
    SubjectKind,
)
from app.domains.members import service as members
from app.domains.members.schemas import (
    IdentityBind,
    MemberInvite,
    MemberStatus,
    TeamCreate,
    TeamMembershipChange,
)

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

ACTOR = "person:it@test.example"


async def _member(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    email: str = "ana@test.example",
    role_keys: list[str] | None = None,
) -> uuid.UUID:
    summary = await members.invite_member(
        session,
        org_id,
        MemberInvite(
            email=email,
            display_name="Ana Tester",
            role_keys=role_keys or [],
        ),
        invited_by=ACTOR,
    )
    return summary.member.id


# ---- members and identities -----------------------------------------------------------


async def test_an_invited_member_can_do_nothing_until_a_role_is_granted(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """The safe default, verified rather than assumed.

    An invite has to be handable to an account admin, which is only true if creating one
    confers nothing by itself.
    """
    member_id = await _member(session, org_id)

    detail = await members.get_member(session, org_id, member_id)
    assert detail.status is MemberStatus.INVITED

    decision = await access.effective_access(session, org_id, member_id)
    assert decision.permissions == []
    assert not decision.allows("agent:read")


async def test_an_invite_can_seed_roles_in_the_same_transaction(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """Otherwise every joiner is a two-step that can half-fail."""
    member_id = await _member(session, org_id, role_keys=["viewer"])

    decision = await access.effective_access(session, org_id, member_id)
    assert "viewer" in decision.role_keys
    assert decision.allows("agent:read")


async def test_the_same_address_twice_in_one_account_is_a_clean_duplicate(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """Cased differently, because the unique index is on `lower(email)`.

    The boundary normalises, so this must surface as the domain's duplicate error and not
    as a raw integrity error from a constraint the caller cannot see.
    """
    await _member(session, org_id, email="ana@test.example")

    with pytest.raises(members.DuplicateMemberError):
        await _member(session, org_id, email="ANA@test.example")


async def test_one_address_can_be_a_member_of_two_accounts(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    """Two customers can employ the same consultant.

    A global unique email would refuse the second account's joiner for a reason nobody in
    that account can see or fix.
    """
    first = await _member(session, org_id, email="consultant@test.example")
    second = await _member(session, other_org_id, email="consultant@test.example")
    assert first != second


async def test_an_idp_subject_binds_to_exactly_one_live_member(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """A subject live in two places makes "who did this" depend on write ordering."""
    first = await _member(session, org_id, email="ana@test.example")
    second = await _member(session, org_id, email="bo@test.example")
    bind = IdentityBind(
        issuer="https://idp.test.example",
        subject="sub-ana",
        email="ana@test.example",
        mfa_verified=True,
    )

    await members.bind_identity(session, org_id, first, bind)

    with pytest.raises(members.IdentityConflictError):
        await members.bind_identity(session, org_id, second, bind)


async def test_a_revoked_binding_frees_the_subject_to_be_rebound(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """The uniqueness index is partial on live rows, which is what makes a mistaken bind
    correctable without deleting the record that it happened."""
    first = await _member(session, org_id, email="ana@test.example")
    second = await _member(session, org_id, email="bo@test.example")
    bind = IdentityBind(
        issuer="https://idp.test.example",
        subject="sub-shared",
        email="ana@test.example",
    )

    identity = await members.bind_identity(session, org_id, first, bind)
    await members.revoke_identity(session, org_id, identity.id)

    rebound = await members.bind_identity(session, org_id, second, bind)
    assert rebound.member_id == second


async def test_a_subject_bound_in_another_account_does_not_resolve_here(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    """The identity lookup spans tenants by design; the org comparison is the boundary.

    This is the one query in the system that is not org-scoped, so the test that it still
    confines its answer matters more than most.
    """
    elsewhere = await _member(session, other_org_id, email="ana@test.example")
    await members.bind_identity(
        session,
        other_org_id,
        elsewhere,
        IdentityBind(
            issuer="https://idp.test.example",
            subject="sub-elsewhere",
            email="ana@test.example",
        ),
    )

    resolved = await members.member_for_identity(
        session, org_id, "https://idp.test.example", "sub-elsewhere"
    )
    assert resolved is None


async def test_invited_employee_claims_membership_on_first_directory_sign_in(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    member_id = await _member(
        session,
        org_id,
        email="employee@test.example",
        role_keys=["viewer"],
    )

    claimed = await members.claim_invite(
        session,
        org_id,
        issuer="https://login.microsoftonline.com/tenant/v2.0",
        subject="entra-subject-1",
        email="employee@test.example",
        email_verified=False,
        mfa_verified=True,
        directory_groups=["group-platform"],
    )

    assert claimed.member.id == member_id
    assert claimed.member.status is MemberStatus.ACTIVE
    assert claimed.account_name
    assert claimed.identities[0].subject == "entra-subject-1"
    assert claimed.identities[0].directory_groups == ["group-platform"]
    assert claimed.identities[0].mfa_verified is True

    repeated = await members.claim_invite(
        session,
        org_id,
        issuer="https://login.microsoftonline.com/tenant/v2.0",
        subject="entra-subject-1",
        email="employee@test.example",
        email_verified=False,
        mfa_verified=True,
        directory_groups=[],
    )
    assert repeated.member.id == member_id


async def test_uninvited_directory_user_is_not_auto_enrolled(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    with pytest.raises(members.InviteNotFoundError):
        await members.claim_invite(
            session,
            org_id,
            issuer="https://login.microsoftonline.com/tenant/v2.0",
            subject="entra-subject-uninvited",
            email="uninvited@test.example",
            email_verified=False,
            mfa_verified=False,
            directory_groups=[],
        )


# ---- grants --------------------------------------------------------------------------


async def test_a_scoped_grant_does_not_leak_to_a_sibling_scope(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    member_id = await _member(session, org_id)
    granted_project = uuid.uuid4()
    other_project = uuid.uuid4()

    await access.create_grant(
        session,
        org_id,
        GrantCreate(
            subject_kind=SubjectKind.MEMBER,
            subject_id=member_id,
            role_key="engineer",
            scope_kind=ScopeKind.PROJECT,
            scope_id=granted_project,
        ),
        granted_by=ACTOR,
    )

    decision = await access.effective_access(session, org_id, member_id)
    assert decision.allows("agent:write", f"project:{granted_project}")
    assert not decision.allows("agent:write", f"project:{other_project}")


async def test_a_team_grant_reaches_the_team_members(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """Otherwise every joiner needs their grants re-issued by hand, which is how accounts
    end up with permissions granted individually and no way to audit them."""
    member_id = await _member(session, org_id)
    team = await members.create_team(session, org_id, TeamCreate(slug="platform", name="Platform"))
    await members.add_team_members(
        session,
        org_id,
        team.id,
        TeamMembershipChange(member_ids=[member_id]),
        added_by=ACTOR,
    )

    await access.create_grant(
        session,
        org_id,
        GrantCreate(
            subject_kind=SubjectKind.TEAM,
            subject_id=team.id,
            role_key="viewer",
            scope_kind=ScopeKind.ACCOUNT,
        ),
        granted_by=ACTOR,
    )

    decision = await access.effective_access(session, org_id, member_id)
    assert decision.allows("agent:read")


async def test_granting_the_same_privilege_twice_is_refused(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """Duplicate live grants make revocation a guessing game: remove one, the other still
    permits, and the trail shows the privilege was taken away."""
    member_id = await _member(session, org_id)
    payload = GrantCreate(
        subject_kind=SubjectKind.MEMBER,
        subject_id=member_id,
        role_key="viewer",
        scope_kind=ScopeKind.ACCOUNT,
    )
    await access.create_grant(session, org_id, payload, granted_by=ACTOR)

    with pytest.raises(access.DuplicateGrantError):
        await access.create_grant(session, org_id, payload, granted_by=ACTOR)


async def test_revoking_removes_the_permission_and_frees_the_slot(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    member_id = await _member(session, org_id)
    payload = GrantCreate(
        subject_kind=SubjectKind.MEMBER,
        subject_id=member_id,
        role_key="viewer",
        scope_kind=ScopeKind.ACCOUNT,
    )
    grant = await access.create_grant(session, org_id, payload, granted_by=ACTOR)

    await access.revoke_grant(session, org_id, grant.id, revoked_by=ACTOR)

    after = await access.effective_access(session, org_id, member_id)
    assert not after.allows("agent:read")

    regranted = await access.create_grant(session, org_id, payload, granted_by=ACTOR)
    assert regranted.id != grant.id


async def test_an_expired_grant_stops_permitting_before_any_sweep_runs(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """The sweep tidies rows; it must not be what enforces expiry.

    If the read path trusted `revoked_at` alone, a lapsed elevation would keep working for
    as long as the worker was behind — which is exactly when nobody is watching.
    """
    member_id = await _member(session, org_id)
    grant = await access.create_grant(
        session,
        org_id,
        GrantCreate(
            subject_kind=SubjectKind.MEMBER,
            subject_id=member_id,
            role_key="viewer",
            scope_kind=ScopeKind.ACCOUNT,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
        ),
        granted_by=ACTOR,
    )
    assert (await access.effective_access(session, org_id, member_id)).allows("agent:read")

    await session.execute(
        text("UPDATE access_grants SET expires_at = :past WHERE id = :id"),
        {"past": datetime.now(UTC) - timedelta(minutes=1), "id": grant.id},
    )
    await session.flush()

    lapsed = await access.effective_access(session, org_id, member_id)
    assert not lapsed.allows("agent:read")


async def test_grants_do_not_cross_the_account_boundary(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    member_id = await _member(session, org_id)
    await access.create_grant(
        session,
        org_id,
        GrantCreate(
            subject_kind=SubjectKind.MEMBER,
            subject_id=member_id,
            role_key="account_admin",
            scope_kind=ScopeKind.ACCOUNT,
        ),
        granted_by=ACTOR,
    )

    seen_elsewhere = await access.effective_access(session, other_org_id, member_id)
    assert seen_elsewhere.permissions == []


# ---- custom roles ---------------------------------------------------------------------


async def test_a_tenant_role_shadows_a_builtin_rather_than_replacing_it(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    """A built-in whose meaning differs per customer is unsupportable.

    So a tenant defining `viewer` gets their own row, resolved first for them, while every
    other account keeps the shipped one.
    """
    await access.create_role(
        session,
        org_id,
        RoleCreate(
            key="viewer",
            name="Viewer (local)",
            description="Narrower than the shipped viewer.",
            permissions=["agent:read"],
            assignable_scopes=[ScopeKind.ACCOUNT],
        ),
    )

    here = {role.key: role for role in await access.list_roles(session, org_id)}
    assert here["viewer"].org_id == org_id
    assert here["viewer"].permissions == ["agent:read"]

    elsewhere = {role.key: role for role in await access.list_roles(session, other_org_id)}
    assert elsewhere["viewer"].org_id is None
    assert "activity:read" in elsewhere["viewer"].permissions


# ---- elevation requests ---------------------------------------------------------------


async def test_approval_creates_the_grant_in_the_same_transaction(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """A request approved without its grant is the worst of both: the requester is told
    yes and still cannot act, and the trail says the privilege was given."""
    requester = await _member(session, org_id, email="ana@test.example")
    approver = await _member(session, org_id, email="bo@test.example")

    request = await access.create_request(
        session,
        org_id,
        AccessRequestCreate(
            role_key="approver",
            scope_kind=ScopeKind.ACCOUNT,
            duration_minutes=120,
            reason="Signing off the payments release.",
        ),
        requester_member_id=requester,
    )

    decided = await access.decide_request(
        session,
        org_id,
        request.id,
        AccessRequestDecision(approve=True),
        decided_by=ACTOR,
        decider_member_id=approver,
    )

    assert decided.granted_grant_id is not None
    assert (await access.effective_access(session, org_id, requester)).allows("release:approve")


async def test_an_approver_cannot_grant_for_longer_than_was_asked_for(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """The requested duration is the ceiling, and a longer decision is clamped to it.

    An approver who can extend is granting something nobody asked for, and the request
    record would no longer describe what was actually given. Clamped rather than refused
    so a fat-fingered week does not make the approver start the request again.
    """
    requester = await _member(session, org_id, email="ana@test.example")
    approver = await _member(session, org_id, email="bo@test.example")
    request = await access.create_request(
        session,
        org_id,
        AccessRequestCreate(
            role_key="approver",
            scope_kind=ScopeKind.ACCOUNT,
            duration_minutes=120,
            reason="Signing off the payments release.",
        ),
        requester_member_id=requester,
    )

    decided = await access.decide_request(
        session,
        org_id,
        request.id,
        AccessRequestDecision(approve=True, granted_minutes=10080),
        decided_by=ACTOR,
        decider_member_id=approver,
    )

    page = await access.list_grants(session, org_id, limit=10, offset=0)
    granted = next(item.grant for item in page.items if item.grant.id == decided.granted_grant_id)
    assert granted.expires_at is not None
    assert granted.expires_at < datetime.now(UTC) + timedelta(minutes=121)


async def test_a_requester_cannot_approve_their_own_elevation(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """Separation of duty, at the only point where it can be enforced cheaply.

    Without this, a member holding `access:approve` can grant themselves anything, and the
    trail records it as a properly approved request.
    """
    requester = await _member(session, org_id, email="ana@test.example")
    request = await access.create_request(
        session,
        org_id,
        AccessRequestCreate(
            role_key="security_admin",
            scope_kind=ScopeKind.ACCOUNT,
            duration_minutes=60,
            reason="Investigating an alert.",
        ),
        requester_member_id=requester,
    )

    with pytest.raises(access.SelfApprovalError):
        await access.decide_request(
            session,
            org_id,
            request.id,
            AccessRequestDecision(approve=True),
            decided_by=ACTOR,
            decider_member_id=requester,
        )


async def test_a_denied_request_grants_nothing(session: AsyncSession, org_id: uuid.UUID) -> None:
    requester = await _member(session, org_id, email="ana@test.example")
    approver = await _member(session, org_id, email="bo@test.example")
    request = await access.create_request(
        session,
        org_id,
        AccessRequestCreate(
            role_key="security_admin",
            scope_kind=ScopeKind.ACCOUNT,
            duration_minutes=60,
            reason="Curiosity.",
        ),
        requester_member_id=requester,
    )

    decided = await access.decide_request(
        session,
        org_id,
        request.id,
        AccessRequestDecision(approve=False, note="No stated incident."),
        decided_by=ACTOR,
        decider_member_id=approver,
    )

    assert decided.granted_grant_id is None
    assert (await access.effective_access(session, org_id, requester)).permissions == []


async def test_a_request_cannot_be_decided_twice(session: AsyncSession, org_id: uuid.UUID) -> None:
    """Two approvers clicking at once must not produce two grants for one request."""
    requester = await _member(session, org_id, email="ana@test.example")
    approver = await _member(session, org_id, email="bo@test.example")
    request = await access.create_request(
        session,
        org_id,
        AccessRequestCreate(
            role_key="approver",
            scope_kind=ScopeKind.ACCOUNT,
            duration_minutes=60,
            reason="Release sign-off.",
        ),
        requester_member_id=requester,
    )
    decision = AccessRequestDecision(approve=True)
    await access.decide_request(
        session,
        org_id,
        request.id,
        decision,
        decided_by=ACTOR,
        decider_member_id=approver,
    )

    with pytest.raises(access.RequestAlreadyDecidedError):
        await access.decide_request(
            session,
            org_id,
            request.id,
            decision,
            decided_by=ACTOR,
            decider_member_id=approver,
        )
