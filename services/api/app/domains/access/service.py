"""Authorization decisions, role grants and time-bound access requests.

The decision this module produces is the answer to "may this member do this to this
resource". Three properties matter more than anything else here:

1. **It is scoped.** A permission is held *at* a scope. Holding ``agent:publish`` on one
   project must not publish in another, which is the entire difference between this and
   the OIDC-claim check it replaces (Q-014).
2. **It is deny-by-default.** An unknown permission, an unknown role, an expired grant
   and a member with no grants all produce the same answer: no.
3. **It is cached per request, never across requests.** Authorization that lags a
   revocation is the failure mode that matters, so the cache lifetime is exactly one
   request. `Q-013`/`Q-014` call for revocation to take effect on the next call, and a
   cross-request cache would break that for its TTL.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.access import repository as repo
from app.domains.access.schemas import (
    PERMISSIONS,
    AccessRequestCreate,
    AccessRequestDecision,
    AccessRequestOut,
    AccessRequestPage,
    EffectiveAccess,
    GrantCreate,
    GrantOut,
    GrantPage,
    GrantSummary,
    RequestState,
    RiskTier,
    RoleCreate,
    RoleOut,
    ScopeKind,
    SubjectKind,
)

ACCOUNT_SCOPE = "account"

# Roles whose grant is itself a governance act. Requesting one of these is high risk by
# definition, so the request never defaults to a low-friction path.
_ELEVATED_ROLES: frozenset[str] = frozenset(
    {"security_admin", "identity_admin", "account_admin", "approver"}
)


class AccessError(Exception):
    """Base class so the router can map one exception family."""


class RoleNotFoundError(AccessError):
    pass


class DuplicateRoleError(AccessError):
    pass


class GrantNotFoundError(AccessError):
    pass


class DuplicateGrantError(AccessError):
    pass


class ScopeNotAssignableError(AccessError):
    pass


class RequestNotFoundError(AccessError):
    pass


class RequestAlreadyDecidedError(AccessError):
    pass


class SelfApprovalError(AccessError):
    """An approver may not decide their own request."""


def scope_key(scope_kind: str, scope_id: UUID | None) -> str:
    """The string form used in :attr:`EffectiveAccess.scoped`.

        Account scope has no id, so it is the bare word. Everything else is ``kind:uuid``,
    which is unambiguous and cheap to compare — the enforcement path does this per call.
    """
    if scope_kind == ACCOUNT_SCOPE:
        return ACCOUNT_SCOPE
    return f"{scope_kind}:{scope_id}"


async def list_roles(session: AsyncSession, org_id: UUID) -> list[RoleOut]:
    rows = await repo.list_roles(session, org_id)
    return [RoleOut.model_validate(row) for row in rows]


async def create_role(session: AsyncSession, org_id: UUID, payload: RoleCreate) -> RoleOut:
    """Define a tenant role.

    A built-in of the same key is not replaced — it is shadowed, and `repository.get_role`
    resolves the tenant one first. Overwriting a seeded row would make the built-in set
    differ per customer, which is exactly the kind of drift that makes support hard.
    """
    try:
        role = await repo.insert_role(
            session,
            org_id,
            {
                "key": payload.key,
                "name": payload.name,
                "description": payload.description,
                "permissions": payload.permissions,
                "assignable_scopes": [scope.value for scope in payload.assignable_scopes],
                "separation_of_duty": payload.separation_of_duty,
            },
        )
    except IntegrityError as exc:
        raise DuplicateRoleError(f"role {payload.key!r} already exists in this account") from exc

    return RoleOut.model_validate(role)


async def grant_role(
    session: AsyncSession,
    org_id: UUID,
    *,
    subject_kind: str,
    subject_id: UUID,
    role_key: str,
    scope_kind: str,
    scope_id: UUID | None,
    granted_by: str,
    reason: str | None = None,
    expires_at: datetime | None = None,
    request_id: UUID | None = None,
) -> GrantOut:
    """Create one scoped grant.

    Checks the role exists and permits the scope before writing. The database enforces
    uniqueness over live grants, so a repeat grant of the same tuple is a conflict rather
    than a second row — otherwise revoking access would mean finding every duplicate.
    """
    role = await repo.get_role(session, org_id, role_key)
    if role is None:
        raise RoleNotFoundError(f"role {role_key!r} does not exist")

    if scope_kind not in set(role.assignable_scopes):
        raise ScopeNotAssignableError(
            f"role {role_key!r} cannot be granted at {scope_kind} scope; "
            f"allowed: {', '.join(sorted(role.assignable_scopes))}"
        )

    try:
        grant = await repo.insert_grant(
            session,
            org_id,
            {
                "subject_kind": subject_kind,
                "subject_id": subject_id,
                "role_key": role_key,
                "scope_kind": scope_kind,
                "scope_id": scope_id,
                "granted_by": granted_by,
                "reason": reason,
                "expires_at": expires_at,
                "request_id": request_id,
            },
        )
    except IntegrityError as exc:
        raise DuplicateGrantError(
            f"{subject_kind} {subject_id} already holds {role_key} at this scope"
        ) from exc

    return GrantOut.model_validate(grant)


OWNER_ROLE_KEY = "account_owner"


async def bootstrap_account_owner(
    session: AsyncSession,
    org_id: UUID,
    member_id: UUID,
    *,
    granted_by: str,
) -> bool:
    """Make ``member_id`` the owner when the account has nobody who can grant access.

    Provisioning a tenant and enrolling its first employee are the same event, and until
    that employee holds something every guarded route answers 403 with no way out: the
    only person who could fix it is the person who is locked out.

    Idempotent and self-limiting. Once any live grant carries ``access:write`` this does
    nothing, so the second employee through the door is an ordinary member and a later
    re-activation cannot silently re-escalate somebody.

    Returns whether the grant was made, so callers can record it.
    """
    if await repo.account_is_administered(session, org_id, now=datetime.now(UTC)):
        return False

    try:
        await grant_role(
            session,
            org_id,
            subject_kind="member",
            subject_id=member_id,
            role_key=OWNER_ROLE_KEY,
            scope_kind="account",
            scope_id=None,
            granted_by=granted_by,
            reason="first member of an unadministered account",
        )
    except DuplicateGrantError:
        return False
    return True


async def create_grant(
    session: AsyncSession,
    org_id: UUID,
    payload: GrantCreate,
    *,
    granted_by: str,
) -> GrantOut:
    return await grant_role(
        session,
        org_id,
        subject_kind=payload.subject_kind.value,
        subject_id=payload.subject_id,
        role_key=payload.role_key,
        scope_kind=payload.scope_kind.value,
        scope_id=payload.scope_id,
        granted_by=granted_by,
        reason=payload.reason,
        expires_at=payload.expires_at,
    )


async def revoke_grant(
    session: AsyncSession,
    org_id: UUID,
    grant_id: UUID,
    *,
    revoked_by: str,
) -> GrantOut:
    revoked = await repo.revoke_grant(session, org_id, grant_id, revoked_by=revoked_by)
    if revoked is None:
        raise GrantNotFoundError(f"grant {grant_id} is not live")
    return GrantOut.model_validate(revoked)


async def list_grants(
    session: AsyncSession,
    org_id: UUID,
    *,
    limit: int,
    offset: int,
    subject_kind: SubjectKind | None = None,
    subject_id: UUID | None = None,
    include_revoked: bool = False,
) -> GrantPage:
    rows, total = await repo.list_grants(
        session,
        org_id,
        limit=limit,
        offset=offset,
        subject_kind=subject_kind.value if subject_kind else None,
        subject_id=subject_id,
        include_revoked=include_revoked,
    )
    return GrantPage(
        items=[
            GrantSummary(
                grant=GrantOut.model_validate(grant),
                subject_label=subject_label,
                role_name=role_name,
                permissions=permissions,
                scope_label=scope_key(grant.scope_kind, grant.scope_id),
            )
            for grant, subject_label, role_name, permissions, _ in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


async def effective_access(
    session: AsyncSession,
    org_id: UUID,
    member_id: UUID,
) -> EffectiveAccess:
    """Flatten every live grant into the permission set and its scopes.

        One query, then an in-memory fold. The fold builds ``permission -> {scope keys}``
    because that is the shape the enforcement question has: "``mcp:invoke`` on server X?"
        is a dict lookup and a set membership test, not a scan of the grant list.

        Unknown permissions in a role are dropped rather than carried. A role that names a
        permission this build does not implement is a deployment skew, and silently honouring
        it would be the wrong side of that error.
    """
    rows = await repo.resolve_grants(session, org_id, member_id, now=datetime.now(UTC))

    role_keys: set[str] = set()
    scoped: dict[str, set[str]] = {}

    for role_key, kind, scope_id, permissions in rows:
        role_keys.add(role_key)
        key = scope_key(kind, scope_id)
        for permission in permissions:
            if permission not in PERMISSIONS:
                continue
            scoped.setdefault(permission, set()).add(key)

    return EffectiveAccess(
        member_id=member_id,
        role_keys=sorted(role_keys),
        permissions=sorted(scoped),
        scoped={permission: sorted(keys) for permission, keys in scoped.items()},
    )


def _risk_of(role_key: str, duration_minutes: int) -> RiskTier:
    """Classify a request so the console can route it without a human triaging first.

    Long-lived elevation is the pattern that turns into a standing privilege nobody
        remembers granting, so duration weighs as heavily as the role.
    """
    if role_key in _ELEVATED_ROLES:
        return RiskTier.CRITICAL if duration_minutes > 1440 else RiskTier.HIGH
    return RiskTier.MEDIUM if duration_minutes > 10080 else RiskTier.LOW


async def create_request(
    session: AsyncSession,
    org_id: UUID,
    payload: AccessRequestCreate,
    *,
    requester_member_id: UUID,
) -> AccessRequestOut:
    """Raise a time-bound elevation request.

    The role and scope are validated now rather than at approval. An approver should
    never be shown a request that cannot be granted — deciding it would fail after they
    had already accepted responsibility for it.
    """
    role = await repo.get_role(session, org_id, payload.role_key)
    if role is None:
        raise RoleNotFoundError(f"role {payload.role_key!r} does not exist")
    if payload.scope_kind.value not in set(role.assignable_scopes):
        raise ScopeNotAssignableError(
            f"role {payload.role_key!r} cannot be granted at {payload.scope_kind.value} scope"
        )

    request = await repo.insert_request(
        session,
        org_id,
        {
            "requester_member_id": requester_member_id,
            "role_key": payload.role_key,
            "scope_kind": payload.scope_kind.value,
            "scope_id": payload.scope_id,
            "duration_minutes": payload.duration_minutes,
            "reason": payload.reason,
            "ticket_ref": payload.ticket_ref,
            "risk": _risk_of(payload.role_key, payload.duration_minutes).value,
            "state": RequestState.PENDING.value,
        },
    )
    return AccessRequestOut.model_validate(request)


async def decide_request(
    session: AsyncSession,
    org_id: UUID,
    request_id: UUID,
    payload: AccessRequestDecision,
    *,
    decided_by: str,
    decider_member_id: UUID,
) -> AccessRequestOut:
    """Approve or deny, creating the grant as part of the same transaction.

        Approval and grant creation cannot be two requests. If they were, an approval that
        succeeded while the grant write failed would leave a request marked approved with no
    access behind it, and the reverse would leave access with no recorded approval.
    """
    request = await repo.get_request(session, org_id, request_id)
    if request is None:
        raise RequestNotFoundError(f"access request {request_id} does not exist")
    if request.state != RequestState.PENDING.value:
        raise RequestAlreadyDecidedError(f"request {request_id} is already {request.state}")
    if request.requester_member_id == decider_member_id:
        raise SelfApprovalError("an access request cannot be decided by its requester")

    if not payload.approve:
        denied = await repo.decide_request(
            session,
            org_id,
            request_id,
            {
                "state": RequestState.DENIED.value,
                "decided_by": decided_by,
                "decision_note": payload.note,
            },
        )
        if denied is None:
            raise RequestAlreadyDecidedError(f"request {request_id} was decided concurrently")
        return AccessRequestOut.model_validate(denied)

    # An approver may shorten but never lengthen: the requester stated a window and that
    # is the ceiling for what they consented to be accountable for.
    minutes = min(payload.granted_minutes or request.duration_minutes, request.duration_minutes)
    expires_at = datetime.now(UTC) + timedelta(minutes=minutes)

    grant = await grant_role(
        session,
        org_id,
        subject_kind=SubjectKind.MEMBER.value,
        subject_id=request.requester_member_id,
        role_key=request.role_key,
        scope_kind=request.scope_kind,
        scope_id=request.scope_id,
        granted_by=decided_by,
        reason=f"access request {request_id}",
        expires_at=expires_at,
        request_id=request_id,
    )

    approved = await repo.decide_request(
        session,
        org_id,
        request_id,
        {
            "state": RequestState.APPROVED.value,
            "decided_by": decided_by,
            "decision_note": payload.note,
            "granted_grant_id": grant.id,
        },
    )
    if approved is None:
        raise RequestAlreadyDecidedError(f"request {request_id} was decided concurrently")

    return AccessRequestOut.model_validate(approved)


async def list_requests(
    session: AsyncSession,
    org_id: UUID,
    *,
    limit: int,
    offset: int,
    state: RequestState | None = None,
    requester_member_id: UUID | None = None,
) -> AccessRequestPage:
    rows, total = await repo.list_requests(
        session,
        org_id,
        limit=limit,
        offset=offset,
        state=state.value if state else None,
        requester_member_id=requester_member_id,
    )
    return AccessRequestPage(
        items=[AccessRequestOut.model_validate(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


async def sweep_expiries(session: AsyncSession, *, batch: int = 5000) -> tuple[int, int]:
    """Revoke lapsed grants and close undecided requests. Called by the worker.

        Bounded per pass so one sweep cannot hold a long transaction over the hottest table
    in the system. Returning the counts lets the worker keep calling until both are zero.
    """
    now = datetime.now(UTC)
    grants = await repo.expire_lapsed_grants(session, now=now, limit=batch)
    requests = await repo.expire_stale_requests(session, now=now, limit=batch)
    return grants, requests


def scope_key_for(kind: ScopeKind, scope_id: UUID | None) -> str:
    """Typed convenience for callers outside this domain."""
    return scope_key(kind.value, scope_id)
