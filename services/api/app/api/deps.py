"""Shared request dependencies: authentication, tenant resolution, sessions, write guard.

Tenant resolution is the security boundary of the whole application, so it lives in one
short file that can be read in full during a review.

There are exactly two ways to be somebody here, and no third:

* **A console session cookie.** Opaque, ``HttpOnly``, resolved against ``auth_sessions``
  on every request by `app/domains/auth`. Revoking the row ends the session on the next
  click rather than whenever a token happens to expire.
* **A bearer token**, for machine callers and for any client that is not the console.
  `app/auth` owns the cryptography and the claim-to-organisation mapping.

The third way used to be ``Bearer dev.<email>`` behind ``AAP_DEV_AUTH_BYPASS``, and it is
gone. It short-circuited verification, org resolution *and* permission checks, which made
it impossible to tell by reading this file whether a permission was ever really enforced
— and the console grew to depend on it, so a local install exercised almost none of the
real path. Development now uses a ``development`` row in ``auth_providers``: a real
session for a real member, through the same code, refused outside
``AAP_ENVIRONMENT=development``.

Every refusal below raises :class:`ApiError`, never a bare ``HTTPException``, so the
console can render a reason instead of "Something went wrong".
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Any
from uuid import UUID

from fastapi import Depends, Header, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError, NextAction, Reason
from app.api.route import attach_session
from app.auth import (
    IdentityProviderUnreachableError,
    OrgResolutionError,
    Principal,
    TokenError,
    bearer_from_header,
    resolve_from_claims,
    verify,
)
from app.config import get_settings
from app.db.session import admin_session, tenant_session
from app.domains.access import service as access_service
from app.domains.access.schemas import PERMISSIONS, EffectiveAccess
from app.domains.auth import service as auth_service
from app.domains.auth.service import ActiveSession
from app.domains.members import service as members_service
from app.domains.workload_identity import service as workload_identity_service
from app.domains.workload_identity.schemas import VerifiedWorkload
from app.domains.workload_identity.service import SECRET_PREFIX
from app.licensing import EntitlementStatus, check_entitlement

log = logging.getLogger(__name__)

# Resolved once. In single-tenant modes the organisation cannot change without a
# restart, so re-querying it on every request would buy nothing.
_single_tenant_org: UUID | None = None

# Entitlement is a startup-and-periodic evaluation, not a per-request one: deciding it
# per request would mean counting agents on every write. Refreshed by
# ``refresh_entitlement`` from the lifespan hook and the worker's hourly sweep.
_entitlement: EntitlementStatus | None = None


async def resolve_single_tenant_org() -> UUID:
    """Look up the configured organisation by slug in `byoc` and `airgap` installs.

    Uses an admin session deliberately: this runs before any tenant is known, so a
    tenant-scoped session would have nothing to scope to.
    """
    global _single_tenant_org
    if _single_tenant_org is not None:
        return _single_tenant_org

    slug = get_settings().default_org_slug
    async with admin_session() as session:
        row = await session.execute(
            text("SELECT id FROM organizations WHERE slug = :slug"), {"slug": slug}
        )
        found = row.scalar_one_or_none()

    if found is None:
        # Migration 0001 seeds 'default', so this means a misconfigured slug rather
        # than a fresh install. Failing loudly beats serving an empty estate.
        raise ApiError(
            Reason.INTERNAL_ERROR,
            message=(
                f"This install is configured for an organisation ({slug!r}) that does not exist."
            ),
            detail={"slug": slug},
            next_action=NextAction.CONTACT_OWNER,
        )

    _single_tenant_org = UUID(str(found))
    return _single_tenant_org


@dataclass(frozen=True, slots=True)
class Authenticated:
    """One verified caller. The principal, the claims, and the session if there is one.

    These travel together because they come from a single verification. FastAPI caches a
    dependency per request, so `authenticate` runs once however many dependents ask for
    it, and the credential is never checked twice. Passing them through this object
    rather than module state matters: anything module-level here would be shared between
    concurrent requests.

    ``console`` is set only for a cookie session. Its presence is what tells the rest of
    the pipeline that the tenant and the member are already decided and need not be
    re-derived from claims.
    """

    principal: Principal
    claims: dict[str, object]
    console: ActiveSession | None = None


async def authenticate(
    request: Request,
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> Authenticated:
    """Identify the caller from a session cookie, or failing that a bearer token.

    Cookie first, because the console is the overwhelming majority of traffic and a
    browser that has one should never fall through to the token path — a stale
    ``Authorization`` header left behind by an older build would otherwise take
    precedence over a session the user just created.
    """
    cookie = request.cookies.get(get_settings().session_cookie_name)
    if cookie:
        # `resolve` raises `ApiError(session_expired)` for expired, revoked and
        # never-existed alike, which is the answer the console knows how to recover from.
        active = await auth_service.resolve(cookie)
        return Authenticated(principal=active.principal, claims={}, console=active)

    try:
        principal, claims = await verify(bearer_from_header(authorization))
    except TokenError as exc:
        # The reason is logged inside `verify`, not returned. Telling an unauthenticated
        # caller which check failed maps out the configuration for them.
        raise ApiError(Reason.NOT_AUTHENTICATED) from exc
    except IdentityProviderUnreachableError as exc:
        # 503, not 401. The credentials may be perfectly good; we cannot check them.
        # Returning 401 would make every client discard a valid session over our outage.
        raise ApiError(Reason.IDENTITY_PROVIDER_UNAVAILABLE) from exc

    return Authenticated(principal=principal, claims=claims)


Auth = Annotated[Authenticated, Depends(authenticate)]


async def require_console_session(auth: Auth) -> ActiveSession:
    """For the three endpoints that act on the session itself rather than through it.

    A bearer token cannot refresh, revoke or list console sessions: it has none. Saying
    so explicitly beats letting those handlers dereference a ``None``.
    """
    if auth.console is None:
        raise ApiError(
            Reason.NOT_AUTHENTICATED,
            message="This action needs a console session, not an API token.",
        )
    return auth.console


ConsoleSession = Annotated[ActiveSession, Depends(require_console_session)]


def require_permission(permission: str) -> Callable[..., Awaitable[None]]:
    """Require an explicit OIDC permission/role for sensitive read or policy actions.

    Superseded by :func:`require_platform_permission` for anything the platform's own
    role model governs. This one reads the token's claims, which means the customer's IdP
    decides, the grant is not scoped to a resource, and revocation waits for the token to
    expire. It survives for endpoints whose authority genuinely is the IdP's to assert.
    """

    async def dependency(auth: Auth) -> None:
        claims = auth.claims
        values: set[str] = set(auth.console.directory_groups) if auth.console else set()
        for key in ("permissions", "roles", "groups"):
            raw = claims.get(key)
            if isinstance(raw, str):
                values.update(part for part in raw.replace(",", " ").split() if part)
            elif isinstance(raw, list):
                values.update(str(part) for part in raw)
        scope = claims.get("scope") or claims.get("scp")
        if isinstance(scope, str):
            values.update(scope.split())
        realm_access = claims.get("realm_access")
        if isinstance(realm_access, dict):
            roles = realm_access.get("roles")
            if isinstance(roles, list):
                values.update(str(role) for role in roles)
        accepted = {permission, "admin", "platform_admin", "observe_admin"}
        if values.isdisjoint(accepted):
            raise ApiError(
                Reason.MODULE_FORBIDDEN,
                message="Your directory account does not carry the group this needs.",
                detail={"permission": permission},
            )

    return dependency


async def current_principal(auth: Auth) -> Principal:
    return auth.principal


CurrentPrincipal = Annotated[Principal, Depends(current_principal)]


async def resolve_org(auth: Auth) -> UUID:
    """Determine which organisation this request acts on behalf of.

    Three sources, in a fixed order, and no header among them. ``X-Org-Id`` used to be
    the whole of this function, which meant any caller could read any tenant by guessing
    a UUID; `tests/unit/test_api_auth.py` keeps that from coming back.

    A console session names its account explicitly, because that was decided when the
    session was created and cannot be influenced by anything the browser sends now. In
    single-tenant modes the claims are ignored entirely, which removes any possibility of
    a claim selecting a different tenant in a deployment where only one may exist.
    """
    if auth.console is not None:
        return auth.console.org_id

    if get_settings().is_single_tenant:
        return await resolve_single_tenant_org()

    try:
        return await resolve_from_claims(auth.claims)
    except OrgResolutionError as exc:
        # 403, not 401: the caller proved who they are, and we are refusing them. A 401
        # would send a correctly authenticated user back to the login screen forever.
        raise ApiError(
            Reason.NOT_PROVISIONED,
            message="Your credentials are valid but do not name an account here.",
            detail={"problem": str(exc)},
        ) from exc


CurrentOrg = Annotated[UUID, Depends(resolve_org)]


async def get_session(request: Request, org_id: CurrentOrg) -> AsyncIterator[AsyncSession]:
    """A transaction scoped to the resolved organisation.

    One transaction per request. A handler that needs to commit partway through wants
    two endpoints, not a nested transaction.

    The session is parked on ``request.state`` so ``TransactionalRoute`` can commit it
    while the response is still being assembled. Teardown here cannot do that job: it
    resumes after the response has been sent, which is the whole of Q-016.
    """
    async with tenant_session(org_id) as session:
        attach_session(request, session)
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]


# ----------------------------------------------------------------------------------
# Platform authorization.
#
# `require_permission` above asks the token. This asks the database: which member is
# this, which roles are granted to them or to their teams, at which scopes, and are
# those grants still live. That is the difference Q-014 is about — a claim cannot be
# scoped to one project and cannot be revoked before the token expires.
#
# The member and their permissions are resolved once per request by FastAPI's dependency
# cache and never cached beyond it. A revocation therefore takes effect on the caller's
# next request, which is the property the whole design exists to provide.
# ----------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MemberContext:
    """The signed-in member, and everything they may do.

    ``label`` is what lands in ``granted_by``, ``created_by`` and the audit log. It pairs
    the email with the member id so an audit row stays readable after somebody changes
    their display name, and stays resolvable after they leave.
    """

    member_id: UUID
    org_id: UUID
    email: str
    display_name: str
    access: EffectiveAccess

    @property
    def label(self) -> str:
        return f"{self.email} ({self.member_id})"

    def allows(self, permission: str, scope_key: str = "account") -> bool:
        return self.access.allows(permission, scope_key)

    def require(self, permission: str, scope_key: str = "account") -> None:
        """Assert a permission at a specific resource scope.

        Services call this for the narrow question a route guard cannot ask: the guard
        knows the caller holds ``agent:publish`` somewhere, this knows whether they hold
        it on *this* agent.
        """
        if not self.allows(permission, scope_key):
            raise ApiError(
                Reason.MODULE_FORBIDDEN,
                detail={"permission": permission, "scope": scope_key},
            )


async def resolve_member(
    auth: Auth,
    session: Session,
    org_id: CurrentOrg,
) -> MemberContext:
    """Map the caller to an account member and load their permissions.

    A verified caller with no member binding is 403, not 401. The credentials are good;
    the person simply has no membership in this account, and sending them back to the
    login screen would loop them forever against an IdP that is happy to sign them in.

    A console session already knows the member — it was resolved when the session was
    created — so it reads by id. The *status* is still read on every request either way,
    which is what makes suspending somebody take effect on their next click rather than
    whenever their session happens to end.
    """
    if auth.console is not None:
        member = await members_service.member_by_id(session, org_id, auth.console.member_id)
    else:
        member = await members_service.member_for_identity(
            session, org_id, auth.principal.issuer, auth.principal.subject
        )

    if member is None:
        raise ApiError(
            Reason.NOT_PROVISIONED,
            message="You are signed in, but you are not a member of this account.",
        )
    if member.status in ("disabled", "suspended"):
        # Distinct from "no membership": the operator disabled this person on purpose and
        # the message should say so rather than reading like a misconfiguration.
        raise ApiError(
            Reason.MEMBERSHIP_SUSPENDED,
            message=f"Your membership of this account is {member.status}.",
            detail={"status": member.status},
        )

    access = await access_service.effective_access(session, org_id, member.id)

    return MemberContext(
        member_id=member.id,
        org_id=org_id,
        email=member.email,
        display_name=member.display_name,
        access=access,
    )


CurrentMember = Annotated[MemberContext, Depends(resolve_member)]


def require_platform_permission(permission: str) -> Callable[..., Awaitable[MemberContext]]:
    """Require a platform permission held at *some* scope.

    A route guard cannot know which resource the request is about — the id is in the path
    or the body, and dependencies run before the handler. So this asserts the caller holds
    the permission somewhere and returns the context; the handler or service then narrows
    it with ``member.require(permission, scope_key)`` once the resource is known.

    Splitting it this way means an unauthorized caller is refused before any query runs,
    while a caller authorized on the wrong project is still refused.
    """
    if permission not in PERMISSIONS:
        # A guard naming a permission no role can hold would deny every caller forever
        # and look like a data problem. Fail at import instead.
        raise ValueError(f"unknown permission {permission!r}")

    async def dependency(member: CurrentMember) -> MemberContext:
        if permission not in member.access.permissions:
            raise ApiError(Reason.MODULE_FORBIDDEN, detail={"permission": permission})
        return member

    return dependency


def PermissionGuard(permission: str) -> Any:  # noqa: N802
    """Decorator form: ``dependencies=[PermissionGuard("access:read")]``.

    Named like a class because that is how it reads at the call site, and because
    ``WriteGuard`` beside it already established the convention.
    """
    return Depends(require_platform_permission(permission))


async def refresh_entitlement(agent_count: int) -> EntitlementStatus:
    """Re-evaluate the licence. Called from the lifespan hook and the worker."""
    global _entitlement
    _entitlement = check_entitlement(agent_count)
    return _entitlement


def current_entitlement() -> EntitlementStatus | None:
    return _entitlement


async def require_write_enabled() -> None:
    """Reject mutations when the licence has lapsed or the agent limit is exceeded.

    Reads and evidence ingest are never guarded by this: a gap in an audit trail
    outlives the billing dispute that caused it, which makes losing telemetry the worse
    of the two outcomes. Enforcement is therefore degradation to read-only, not refusal.

    An unevaluated entitlement permits writes. Failing closed here would mean a licence
    file that is briefly unreadable takes the product down, which is a larger outage
    than the one it prevents.
    """
    entitlement = _entitlement
    if entitlement is not None and entitlement.read_only:
        raise ApiError(
            Reason.LICENCE_READ_ONLY,
            message="; ".join(entitlement.reasons) or "The licence does not permit changes.",
            detail={"reasons": list(entitlement.reasons)},
        )


WriteEnabled = Annotated[None, Depends(require_write_enabled)]
"""Handler-parameter form: ``_: WriteEnabled``."""

WriteGuard = Depends(require_write_enabled)
"""Decorator form: ``dependencies=[WriteGuard]``.

FastAPI's ``dependencies=`` list takes ``Depends`` instances, not annotations, so the
two forms cannot share one name. Use this one when the handler has no use for the
result, which is every mutation.
"""


async def assert_org_exists(session: Session, org_id: CurrentOrg) -> UUID:
    """Guard against a valid-looking organisation that does not exist.

    Without this, a forged header yields empty lists and writes that row-level security
    silently discards — which reads as a product bug rather than an authorisation
    failure, and is correspondingly hard to diagnose.
    """
    found = await session.execute(
        text("SELECT 1 FROM organizations WHERE id = :id"), {"id": str(org_id)}
    )
    if found.scalar_one_or_none() is None:
        raise ApiError(
            Reason.NOT_PROVISIONED,
            message="That account does not exist on this deployment.",
            status_code=403,
        )
    return org_id


VerifiedOrg = Annotated[UUID, Depends(assert_org_exists)]


def reset_caches() -> None:
    """Clear resolved state. For tests, and for the worker after a licence reload."""
    global _single_tenant_org, _entitlement
    _single_tenant_org = None
    _entitlement = None


@dataclass(frozen=True, slots=True)
class WorkloadCollector:
    """Verified machine caller for ingest and reporter endpoints."""

    workload: VerifiedWorkload


_WORKLOAD_AUTH_FAILURE = "That workload credential was not accepted."


def _workload_rejected() -> ApiError:
    """One refusal for every way a workload credential can be wrong.

    Four call sites, one message. Distinguishing "not a workload token" from "no such
    credential" would tell an unauthenticated caller how far their guess got, which is
    the first half of finding a real one.
    """
    return ApiError(Reason.INVALID_CREDENTIAL, message=_WORKLOAD_AUTH_FAILURE)


async def authenticate_workload_collector(
    authorization: Annotated[str | None, Header(alias="Authorization")] = None,
) -> WorkloadCollector:
    """Accept only opaque workload keys — never OIDC tokens and never a session cookie.

    Human administration stays on ``authenticate``; this path is deliberately narrow so
    ingest cannot be reached with a browser's credential, and so a person reading the
    audit trail can tell a machine's writes from a human's.
    """
    try:
        token = bearer_from_header(authorization)
    except TokenError:
        log.warning("workload credential rejected: missing or malformed Authorization header")
        raise _workload_rejected() from None

    if not token.startswith(SECRET_PREFIX):
        log.warning("workload credential rejected: not a workload token")
        raise _workload_rejected()

    # Reject malformed ids/secret length before opening a database connection. Besides
    # being cheaper, this keeps unauthenticated garbage from consuming the DB pool.
    if workload_identity_service.parse_credential_token(token) is None:
        log.warning("workload credential rejected: malformed workload token")
        raise _workload_rejected()

    async with admin_session() as session:
        try:
            workload = await workload_identity_service.verify_presented_secret(session, token)
        except workload_identity_service.CredentialInvalidError:
            raise _workload_rejected() from None

    return WorkloadCollector(workload=workload)


CollectorAuth = Annotated[WorkloadCollector, Depends(authenticate_workload_collector)]


async def get_workload_session(
    request: Request,
    collector: CollectorAuth,
) -> AsyncIterator[AsyncSession]:
    """Tenant session bound to the organisation embedded in the verified credential."""
    async with tenant_session(collector.workload.org_id) as session:
        attach_session(request, session)
        yield session


WorkloadSession = Annotated[AsyncSession, Depends(get_workload_session)]


def enforce_collector(
    collector: WorkloadCollector,
    *,
    scope: str,
    module: str,
    agent_id: UUID | None = None,
) -> VerifiedWorkload:
    """Check module, scope and optional agent binding for an ingest handler.

    Operations run ingest should pass ``module='observe'`` (not a separate module).
    """
    workload = collector.workload
    try:
        workload_identity_service.require_module(workload, module)
        workload_identity_service.require_scope(workload, scope)
        if agent_id is not None:
            workload_identity_service.require_agent_binding(workload, agent_id)
    except (
        workload_identity_service.ScopeDeniedError,
        workload_identity_service.AgentBindingError,
    ) as exc:
        raise ApiError(
            Reason.SCOPE_OUTSIDE_GRANT,
            message=str(exc),
            detail={"module": module, "scope": scope},
        ) from exc
    return workload
