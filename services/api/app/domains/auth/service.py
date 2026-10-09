"""Console sign-in, session lifetime, session revocation.

Three things used to live in the browser and now live here, and the reason is the same
for all three: the browser is not a place a security decision can be kept.

* **Which providers exist.** It was `VITE_OIDC_*`, baked into the bundle at build time,
  which meant a deployment could not add a provider without a rebuild and a login screen
  could render a button for a provider that was never configured. Now
  :func:`config_for` answers it per request, from the database.
* **The token exchange.** It was `fetch` to the IdP's token endpoint from the page, with
  the id token decoded by `atob` — a decode, not a verification. Now `app/auth/providers`
  does it server side and checks the signature.
* **The session.** It was a token in `sessionStorage`, which cannot be revoked, cannot be
  listed, and survives a logout in any other tab. Now it is a row: revocable, listable,
  and gone the moment an operator says so.

Every refusal here raises :class:`ApiError` with a reason from `design/02`. That is what
makes ``inv_every_error_has_reason`` a property of the code rather than of the tests.
"""

from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import ApiError, NextAction, Reason
from app.auth import providers as auth_providers
from app.auth.claims import ClaimMappingError, ResolvedClaims, normalise_email
from app.auth.principal import Principal
from app.auth.providers import ProviderError, ProviderRecord
from app.config import get_settings
from app.db.models.auth import AuthProvider, AuthSession
from app.db.session import admin_session, tenant_session
from app.domains.auth import repository as repo
from app.domains.auth.schemas import (
    AuthConfigOut,
    AuthProviderOut,
    SessionListOut,
    SessionOut,
    SessionStart,
    SessionSummary,
)
from app.domains.members import service as members_service

log = logging.getLogger(__name__)

TOKEN_BYTES = 32
"""256 bits of entropy in the cookie. The row is found by digest, so the token itself is
never stored and a dump of ``auth_sessions`` cannot be replayed as anybody."""

_LAST_SEEN_RESOLUTION = timedelta(seconds=60)
"""How stale ``last_seen_at`` may get before a request pays for an UPDATE.

Without this the session row is written on every single request by every tab, which is
the row-contention shape that shows up as lock waits under load long before anything
else does. A minute is far finer than any decision made from this column.
"""


@dataclass(frozen=True, slots=True)
class ActiveSession:
    """A cookie that resolved. What the request pipeline needs and nothing more."""

    id: UUID
    org_id: UUID
    member_id: UUID
    provider_id: UUID | None
    mfa_verified: bool
    expires_at: datetime
    absolute_expires_at: datetime
    principal: Principal
    """Rebuilt from the row rather than from a token, so every consumer of
    ``auth.principal`` reads the same shape whether the caller is a browser or a
    machine."""

    directory_groups: list[str]
    """What the provider asserted at sign-in. The two claim-driven route guards in
    `domains/observe` read these, so a console session has to carry them or those routes
    would refuse every browser while accepting every bearer token."""


@dataclass(frozen=True, slots=True)
class IssuedSession:
    """A new session. ``token`` goes in the cookie and nowhere else — never the body."""

    token: str
    session: SessionOut


# ----------------------------------------------------------------------------------
# What the login screen may know.
# ----------------------------------------------------------------------------------


async def config_for(email_domain: str | None = None) -> AuthConfigOut:
    """Answer "how do I sign in to this deployment?" for an unauthenticated caller.

    Deliberately says *why* when the answer is "you cannot". An empty provider list with
    no explanation is what produced the original report: the screen rendered a button,
    the button did nothing, and nothing anywhere said that no provider was configured.

    Domain-keyed lookup exists for the multi-tenant case, where the person typing their
    address is the only hint available about which account they belong to. It matches an
    exact domain and nothing else: a prefix or fuzzy match would let an unauthenticated
    caller enumerate which customers exist.
    """
    development = auth_providers.development_mode_enabled()

    try:
        async with admin_session() as unscoped:
            if email_domain:
                rows = await repo.find_providers_for_domain(unscoped, email_domain.strip().lower())
            else:
                org_id = await _sole_account(unscoped)
                rows = [] if org_id is None else await repo.list_providers(unscoped, org_id)
            account_hint = await _account_name(unscoped, rows)
    except SQLAlchemyError as exc:
        # The only endpoint the console calls before anybody is signed in, so it is also
        # the only one whose failure a person sees as "the product is down". Saying
        # which part is down is worth the special case: an unreachable database
        # otherwise reaches the login screen as an unexplained 500, and the obvious
        # guess from there is that the identity provider is at fault.
        log.error("auth config could not be read: %s", exc)
        raise ApiError(
            Reason.UPSTREAM_UNAVAILABLE,
            message="Sign-in is temporarily unavailable. The console cannot reach its database.",
        ) from exc

    visible = [row for row in rows if row.kind != "development" or development]

    return AuthConfigOut(
        account_hint=account_hint,
        providers=[_provider_out(row) for row in visible],
        unavailable_reason=_unavailable_reason(rows, visible, email_domain, development),
        development=development,
    )


def _unavailable_reason(
    rows: list[AuthProvider],
    visible: list[AuthProvider],
    email_domain: str | None,
    development: bool,
) -> str | None:
    """A sentence an operator can act on, or ``None`` when there is nothing to explain."""
    if visible:
        return None
    if rows and not development:
        return (
            "The only sign-in method configured for this account is the development "
            "provider, which this deployment does not permit."
        )
    if email_domain:
        return (
            f"No sign-in method is configured for {email_domain}. An account owner adds "
            "one in Settings, or you may be signing in to the wrong deployment."
        )
    return (
        "No sign-in method is configured for this deployment. Add a row to "
        "auth_providers with the issuer, client id and authorize URL of your identity "
        "provider."
    )


def _provider_out(row: AuthProvider) -> AuthProviderOut:
    return AuthProviderOut(
        id=row.id,
        kind=row.kind,  # type: ignore[arg-type]
        label=row.label,
        authorize_url=row.authorize_url,
        client_id=row.client_id,
        scopes=row.scopes,
        pkce=row.client_secret_ref is None,
        onboarding_mode=row.onboarding_mode,
    )


async def _sole_account(unscoped: AsyncSession) -> UUID | None:
    """The account whose providers an undirected request is about.

    Only answered when there is exactly one, which is every single-tenant install. With
    two or more the caller must say which domain they are, because guessing would show
    one customer's sign-in buttons to another's employee.
    """
    rows = await repo.distinct_provider_accounts(unscoped, limit=2)
    return rows[0] if len(rows) == 1 else None


async def _account_name(unscoped: AsyncSession, rows: list[AuthProvider]) -> str | None:
    if not rows:
        return None
    org_ids = {row.org_id for row in rows}
    if len(org_ids) != 1:
        # Several accounts share this domain. Naming one of them would be a guess, and
        # the login screen is better with no subtitle than with the wrong company's name.
        return None
    return await repo.account_name(unscoped, org_ids.pop())


# ----------------------------------------------------------------------------------
# Starting a session.
# ----------------------------------------------------------------------------------


async def start(
    payload: SessionStart,
    *,
    user_agent: str | None,
    client_ip: str | None,
) -> IssuedSession:
    """Verify one sign-in attempt and, only if all of it succeeded, create a session.

    The ordering is the invariant. Verification happens outside any transaction, member
    resolution and the session insert happen inside one, and the session row is the last
    write in it. A failure at any point leaves the transaction rolled back, so
    ``inv_no_session_without_member`` holds because there is no ordering of these
    statements that could produce a session row without a member.
    """
    record = await _provider_record(payload.provider_id)

    try:
        claims = await auth_providers.verify(
            record,
            code=payload.code,
            code_verifier=payload.code_verifier,
            redirect_uri=payload.redirect_uri,
            nonce=payload.nonce,
            development_email=normalise_email(payload.email),
        )
    except ProviderError as exc:
        raise ApiError(exc.reason, message=exc.message, detail=exc.detail) from exc
    except ClaimMappingError as exc:
        # Not a credentials problem: the token verified. The provider's `claim_map` is
        # wrong, and saying "invalid credential" would send an operator to look at the
        # user's account instead of at the configuration.
        raise ApiError(
            Reason.PROVIDER_NOT_CONFIGURED,
            message=f"{record.label} did not return the claims it is configured to return.",
            detail={"provider": record.label, "problem": str(exc)},
            next_action=NextAction.CONFIGURE_PROVIDER,
        ) from exc

    async with tenant_session(record.org_id) as session:
        profile = await _resolve_member(session, record, claims)
        token, row = await _issue(
            session,
            record,
            claims,
            member_id=profile.member.id,
            user_agent=user_agent,
            client_ip=client_ip,
        )
        out = SessionOut(
            session_id=row.id,
            member_id=profile.member.id,
            account_id=record.org_id,
            email=profile.member.email,
            display_name=profile.member.display_name,
            issued_at=row.issued_at,
            expires_at=row.expires_at,
            absolute_expires_at=row.absolute_expires_at,
        )

    log.info(
        "console session started",
        extra={"member_id": str(profile.member.id), "provider": record.label},
    )
    return IssuedSession(token=token, session=out)


async def _provider_record(provider_id: UUID) -> ProviderRecord:
    """Load one provider by id, before any tenant is known.

    The id is the only thing the callback screen carries, and it came from
    `/v1/auth/config`, so this lookup is what establishes which account the sign-in is
    for. That is why it is not org-scoped — see the repository's module docstring.
    """
    async with admin_session() as unscoped:
        row = await repo.find_provider(unscoped, provider_id)
        if row is None:
            raise ApiError(
                Reason.PROVIDER_UNKNOWN,
                detail={"provider_id": str(provider_id)},
            )
        return ProviderRecord(
            id=row.id,
            org_id=row.org_id,
            kind=row.kind,
            label=row.label,
            issuer=row.issuer,
            client_id=row.client_id,
            client_secret_ref=row.client_secret_ref,
            jwks_uri=row.jwks_uri,
            authorize_url=row.authorize_url,
            token_url=row.token_url,
            scopes=row.scopes,
            claim_map=dict(row.claim_map or {}),
            email_domains=list(row.email_domains or []),
            onboarding_mode=row.onboarding_mode,
            require_mfa_claim=row.require_mfa_claim,
            enabled=row.enabled,
        )


async def _resolve_member(
    session: AsyncSession,
    record: ProviderRecord,
    claims: ResolvedClaims,
) -> members_service.MemberProfile:
    """Verified claims to a member, translating each failure into its own reason.

    The resolver itself lives in `domains/members` because that domain owns member rows.
    What belongs here is the mapping from its exceptions to reason codes, because the
    login screen is the only place these are rendered and each one wants a different
    sentence and a different button.
    """
    try:
        return await members_service.resolve_directory_login(
            session,
            record.org_id,
            issuer=claims.issuer,
            subject=claims.subject,
            email=claims.email,
            email_verified=claims.email_verified,
            mfa_verified=claims.mfa_verified,
            directory_groups=claims.groups,
            onboarding_mode=record.onboarding_mode,
            allow_first_owner_bootstrap=record.kind == "development",
        )
    except members_service.MembershipInactiveError as exc:
        raise ApiError(
            Reason.MEMBERSHIP_SUSPENDED,
            message=f"Your membership of this account is {exc.status}.",
            detail={"status": exc.status},
        ) from exc
    except members_service.IdentityConflictError as exc:
        raise ApiError(
            Reason.CONFLICT,
            message="That directory account is already linked to a different account here.",
            next_action=NextAction.CONTACT_OWNER,
        ) from exc
    except members_service.NotProvisionedError as exc:
        raise ApiError(
            Reason.NOT_PROVISIONED,
            message=(
                "You signed in successfully, but nobody has invited you to this account "
                "yet. Ask an account owner to send you an invitation."
            ),
            detail={"email": claims.email, "provider": record.label},
        ) from exc
    except members_service.MemberNotFoundError as exc:
        # The identity row survives its member; the FK is ON DELETE CASCADE, so this is
        # a genuine inconsistency rather than an ordinary state.
        log.error("identity resolves to a member that does not exist: %s", exc)
        raise ApiError(Reason.NOT_PROVISIONED) from exc


async def _issue(
    session: AsyncSession,
    record: ProviderRecord,
    claims: ResolvedClaims,
    *,
    member_id: UUID,
    user_agent: str | None,
    client_ip: str | None,
) -> tuple[str, AuthSession]:
    settings = get_settings()
    token = secrets.token_urlsafe(TOKEN_BYTES)
    now = datetime.now(tz=UTC)
    absolute = now + timedelta(hours=settings.session_absolute_hours)
    row = await repo.insert_session(
        session,
        record.org_id,
        {
            "member_id": member_id,
            "provider_id": record.id,
            "token_hash": token_digest(token),
            "identity_issuer": claims.issuer,
            "identity_subject": claims.subject,
            "identity_email": claims.email,
            "identity_groups": list(dict.fromkeys(claims.groups)),
            "issued_at": now,
            "expires_at": min(now + timedelta(minutes=settings.session_idle_minutes), absolute),
            "absolute_expires_at": absolute,
            "last_seen_at": now,
            "mfa_verified": claims.mfa_verified,
            "user_agent": (user_agent or "")[:400] or None,
            "client_ip": client_ip,
        },
    )
    return token, row


def token_digest(token: str) -> bytes:
    """SHA-256 of the cookie value.

    Unsalted on purpose. The token is 256 random bits, so there is no dictionary to
    defend against, and a per-row salt would make the lookup a table scan instead of an
    index probe on every single request.
    """
    return hashlib.sha256(token.encode("utf-8")).digest()


# ----------------------------------------------------------------------------------
# Using and ending a session.
# ----------------------------------------------------------------------------------


async def resolve(token: str) -> ActiveSession:
    """One cookie to one live session, or a reason why not.

    Runs on every authenticated request, so it does exactly one query in the common case
    and writes only when ``last_seen_at`` has actually gone stale.
    """
    async with admin_session() as unscoped:
        row = await repo.find_live_session(unscoped, token_digest(token))
        if row is None:
            # Deliberately the same answer for expired, revoked and never-existed. The
            # difference is only interesting to somebody holding a cookie they should
            # not have, and the console's recovery is identical in all three cases.
            raise ApiError(Reason.SESSION_EXPIRED)

        now = datetime.now(tz=UTC)
        if now - row.last_seen_at >= _LAST_SEEN_RESOLUTION:
            settings = get_settings()
            await repo.touch_session(
                unscoped,
                row.id,
                seen_at=now,
                expires_at=min(
                    now + timedelta(minutes=settings.session_idle_minutes),
                    row.absolute_expires_at,
                ),
            )

        return ActiveSession(
            id=row.id,
            org_id=row.org_id,
            member_id=row.member_id,
            provider_id=row.provider_id,
            mfa_verified=row.mfa_verified,
            expires_at=row.expires_at,
            absolute_expires_at=row.absolute_expires_at,
            principal=Principal(
                subject=row.identity_subject,
                issuer=row.identity_issuer,
                email=row.identity_email,
                roles=frozenset(row.identity_groups or ()),
            ),
            directory_groups=list(row.identity_groups or ()),
        )


async def renew(active: ActiveSession) -> SessionOut:
    """Extend the sliding window explicitly, for a console that is open but idle.

    Never extends past ``absolute_expires_at``: that ceiling is what bounds how long a
    deprovisioned person keeps working, and a refresh that moved it would remove the
    only upper bound the design has.
    """
    settings = get_settings()
    now = datetime.now(tz=UTC)
    expires_at = min(
        now + timedelta(minutes=settings.session_idle_minutes),
        active.absolute_expires_at,
    )
    async with tenant_session(active.org_id) as session:
        await repo.touch_session(session, active.id, seen_at=now, expires_at=expires_at)
        member = await members_service.member_by_id(session, active.org_id, active.member_id)
    if member is None:
        raise ApiError(Reason.NOT_PROVISIONED)

    return SessionOut(
        session_id=active.id,
        member_id=member.id,
        account_id=active.org_id,
        email=member.email,
        display_name=member.display_name,
        issued_at=now,
        expires_at=expires_at,
        absolute_expires_at=active.absolute_expires_at,
    )


async def end(active: ActiveSession, *, reason: str = "logout") -> None:
    """Revoke server side. The cookie is cleared too, but that is not what ends it.

    Clearing the cookie alone is what `sessionStorage` did, and it meant a copied token
    kept working. The row is the session; deleting the client's copy of the reference is
    housekeeping.
    """
    async with tenant_session(active.org_id) as session:
        await repo.revoke_session(
            session, active.org_id, active.id, reason=reason, revoked_at=datetime.now(tz=UTC)
        )


async def list_for_member(
    session: AsyncSession,
    org_id: UUID,
    member_id: UUID,
    *,
    current_id: UUID | None,
) -> SessionListOut:
    """ "Where you are signed in", for the profile page."""
    rows = await repo.list_sessions_for_member(session, org_id, member_id)
    return SessionListOut(
        items=[
            SessionSummary(
                id=row.id,
                issued_at=row.issued_at,
                last_seen_at=row.last_seen_at,
                expires_at=row.expires_at,
                absolute_expires_at=row.absolute_expires_at,
                user_agent=row.user_agent,
                client_ip=str(row.client_ip) if row.client_ip else None,
                provider_label=label,
                current=row.id == current_id,
            )
            for row, label in rows
        ]
    )


async def revoke_for_member(
    session: AsyncSession,
    org_id: UUID,
    member_id: UUID,
    session_id: UUID,
    *,
    current_id: UUID | None,
) -> None:
    """Revoke one of your own sessions.

    Scoped to ``member_id`` by the repository, not by a permission check: revoking
    somebody else's session is an administrative action with its own audit story, and
    allowing it here by passing a different id would be the kind of quiet privilege
    escalation that is invisible in review.
    """
    if session_id == current_id:
        raise ApiError(
            Reason.INVALID_REQUEST,
            message="That is the session you are using now. Sign out instead.",
            next_action=NextAction.NONE,
        )
    revoked = await repo.revoke_session_for_member(
        session,
        org_id,
        member_id,
        session_id,
        reason="revoked_by_member",
        revoked_at=datetime.now(tz=UTC),
    )
    if not revoked:
        raise ApiError(Reason.NOT_FOUND, message="That session has already ended.")
