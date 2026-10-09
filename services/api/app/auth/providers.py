"""One verification path per provider kind.

The browser used to do this. It read the issuer and client id from its own build-time
environment, called the identity provider's token endpoint directly, decoded the id token
with `atob` and believed what it found. Three things follow from that and all three were
reported as bugs: a redirect-URI mismatch surfaced as a blank screen, clock skew surfaced
as a blank screen, and the decoded token was never actually *verified* — `atob` reads a
signature it cannot check.

Moving the exchange here fixes all three at once, and adds the one that matters most:
every failure below has its own error, so the console can say which.

Each function raises :class:`ProviderError` carrying a :class:`Reason`. Nothing here
touches the database or decides who a person is — it establishes *what the provider
asserted*, and `domains/auth/service.py` decides what that means.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import httpx
import jwt

from app.api.errors import Reason
from app.auth.claims import ResolvedClaims, normalise_email, resolve_claims
from app.auth.jwks import JwksUnavailableError, UnknownKeyError, key_for_issuer
from app.config import get_settings

log = logging.getLogger(__name__)

DEVELOPMENT_ISSUER = "urn:aap:dev"
"""Issuer recorded for a development sign-in. Never a real IdP's issuer value, so an
audit row can always be told apart from a production one."""

_HTTP_TIMEOUT = httpx.Timeout(10.0, connect=3.0)


class ProviderError(Exception):
    """A provider refused, or answered something we will not accept.

    Carries the reason code the console renders. Constructing one without a reason is
    impossible, which is the property that makes ``inv_every_error_has_reason`` hold at
    the source rather than at the edge.
    """

    def __init__(self, reason: Reason, message: str, detail: dict[str, Any] | None = None) -> None:
        self.reason = reason
        self.message = message
        self.detail = detail or {}
        super().__init__(f"{reason}: {message}")


@dataclass(frozen=True, slots=True)
class ProviderRecord:
    """One ``auth_providers`` row, as the verification path needs it.

    A plain dataclass rather than the ORM model: this is read by the exchange, which has
    no session and must not acquire one.
    """

    id: UUID
    org_id: UUID
    kind: str
    label: str
    issuer: str | None
    client_id: str | None
    client_secret_ref: UUID | None
    jwks_uri: str | None
    authorize_url: str | None
    token_url: str | None
    scopes: str
    claim_map: dict[str, Any]
    email_domains: list[str]
    onboarding_mode: str
    require_mfa_claim: bool
    enabled: bool

    @property
    def domain_authoritative(self) -> bool:
        """True when this provider owns every domain it lists.

        A provider with an explicit domain allowlist is asserting that it is the identity
        authority for those domains, which is what makes an address it returns trustable
        even when it omits ``email_verified``. A provider with no allowlist asserts
        nothing of the kind.
        """
        return bool(self.email_domains)


def allows_email(provider: ProviderRecord, email: str | None) -> bool:
    """Whether ``email``'s domain is one this provider is allowed to speak for."""
    if not provider.email_domains:
        return True
    if not email or "@" not in email:
        return False
    domain = email.rsplit("@", 1)[1].lower()
    return any(domain == allowed.strip().lower() for allowed in provider.email_domains)


def assert_redirect_uri_allowed(redirect_uri: str) -> None:
    """The redirect URI is where the authorization code was sent. Bound it.

    We echo this value to the token endpoint, and the provider matches it against its own
    registration — which is the real control. This check is the second one: it keeps a
    caller from using our server as a probe against arbitrary hosts, and it fails with a
    message an operator can act on rather than a provider error nobody can read.
    """
    settings = get_settings()
    allowed_origins = {origin.rstrip("/") for origin in settings.cors_origins}
    parsed = urlparse(redirect_uri)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ProviderError(
            Reason.INVALID_REQUEST,
            "The sign-in redirect address is not a valid URL.",
            {"redirect_uri": redirect_uri},
        )
    origin = f"{parsed.scheme}://{parsed.netloc}"
    if origin not in allowed_origins:
        raise ProviderError(
            Reason.INVALID_REQUEST,
            "That sign-in redirect address is not one this deployment serves.",
            {"origin": origin, "allowed": sorted(allowed_origins)},
        )


async def verify(
    provider: ProviderRecord,
    *,
    code: str | None,
    code_verifier: str | None,
    redirect_uri: str | None,
    nonce: str | None,
    development_email: str | None,
) -> ResolvedClaims:
    """Turn one sign-in attempt into verified claims, or raise with a reason."""
    if not provider.enabled:
        raise ProviderError(
            Reason.PROVIDER_DISABLED,
            f"Sign-in with {provider.label} is turned off for this account.",
            {"provider": provider.label},
        )

    if provider.kind == "development":
        return _verify_development(provider, development_email)
    if provider.kind == "oidc":
        return await _verify_oidc(
            provider,
            code=code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            nonce=nonce,
        )

    # Unreachable while the CHECK constraint in 0022 allows only two kinds. Kept because
    # the next revision widens that constraint, and an unimplemented kind must refuse
    # loudly rather than fall through to whichever branch happens to be last.
    raise ProviderError(
        Reason.PROVIDER_NOT_CONFIGURED,
        f"Sign-in kind {provider.kind!r} is not implemented in this release.",
        {"kind": provider.kind},
    )


def _verify_development(provider: ProviderRecord, email: str | None) -> ResolvedClaims:
    """The local stub. Refused unless this install is a development one.

    This replaces the ``Bearer dev.<email>`` header the API used to accept. The important
    difference is not the shape: it is that the old one was checked by a settings flag on
    a code path that every request went through, and this one is a provider row that only
    the login endpoint can reach, produces a real session row, and is invisible to
    ``/v1/auth/config`` outside development.
    """
    if not development_mode_enabled():
        raise ProviderError(
            Reason.PROVIDER_DISABLED,
            "Development sign-in is not available on this deployment.",
            {"environment": get_settings().environment},
        )

    normalised = normalise_email(email)
    if normalised is None:
        raise ProviderError(
            Reason.INVALID_REQUEST,
            "Development sign-in needs the email address to sign in as.",
        )
    if not allows_email(provider, normalised):
        raise ProviderError(
            Reason.NOT_PROVISIONED,
            "That email domain is not one the development provider may sign in.",
            {"allowed_domains": list(provider.email_domains)},
        )

    return resolve_claims(
        {"sub": f"dev:{normalised}", "email": normalised, "email_verified": True},
        claim_map=provider.claim_map,
        issuer=DEVELOPMENT_ISSUER,
        domain_authoritative=True,
    )


def development_mode_enabled() -> bool:
    """One place answers "may a development provider be used here".

    A function rather than an inline comparison so that every caller — the verification
    path, `/v1/auth/config`, and the invariant test — asks the same question. The old
    bypass was a settings flag read in one place and reasoned about in three.
    """
    return get_settings().environment == "development"


async def _verify_oidc(
    provider: ProviderRecord,
    *,
    code: str | None,
    code_verifier: str | None,
    redirect_uri: str | None,
    nonce: str | None,
) -> ResolvedClaims:
    if not code or not code_verifier or not redirect_uri:
        raise ProviderError(
            Reason.INVALID_REQUEST,
            "The sign-in response was incomplete. Start again from the login screen.",
            {
                "missing": [
                    name
                    for name, value in (
                        ("code", code),
                        ("code_verifier", code_verifier),
                        ("redirect_uri", redirect_uri),
                    )
                    if not value
                ]
            },
        )

    if provider.client_secret_ref is not None:
        # A confidential client needs the secret pulled from the customer's secret
        # provider. That plumbing is not in this release, and quietly attempting a public
        # -client exchange would produce an `invalid_client` from the IdP that reads like
        # a user error rather than our missing feature.
        raise ProviderError(
            Reason.PROVIDER_NOT_CONFIGURED,
            f"{provider.label} is configured as a confidential client, which this "
            "release cannot use. Configure it for PKCE instead.",
            {"provider": provider.label},
        )

    assert_redirect_uri_allowed(redirect_uri)
    assert provider.token_url is not None and provider.client_id is not None

    id_token = await _exchange_code(provider, code, code_verifier, redirect_uri)
    claims = await _verify_id_token(provider, id_token, nonce)

    resolved = resolve_claims(
        claims,
        claim_map=provider.claim_map,
        issuer=str(provider.issuer or "").rstrip("/"),
        domain_authoritative=provider.domain_authoritative,
    )

    if provider.require_mfa_claim and not resolved.mfa_verified:
        raise ProviderError(
            Reason.MFA_REQUIRED,
            "Your organisation requires multi-factor authentication for this console.",
            {"provider": provider.label},
        )
    if not allows_email(provider, resolved.email):
        raise ProviderError(
            Reason.NOT_PROVISIONED,
            "That email domain is not one this sign-in method covers.",
            {"allowed_domains": list(provider.email_domains)},
        )
    return resolved


async def _exchange_code(
    provider: ProviderRecord,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> str:
    """Authorization code → id token, server side.

    Redirects are not followed: the token endpoint is a fixed URL from the provider row,
    and following a redirect would post an authorization code and a PKCE verifier to a
    host the configuration never named.
    """
    assert provider.token_url is not None and provider.client_id is not None
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "code_verifier": code_verifier,
        "client_id": provider.client_id,
    }

    try:
        async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=False) as client:
            response = await client.post(provider.token_url, data=form)
    except httpx.HTTPError as exc:
        log.warning("token endpoint unreachable at %s: %s", provider.token_url, exc)
        raise ProviderError(
            Reason.IDENTITY_PROVIDER_UNAVAILABLE,
            f"We could not reach {provider.label} to complete sign-in.",
            {"provider": provider.label},
        ) from exc

    if response.status_code >= 400:
        # The provider's own `error` code is the single most useful thing an operator can
        # be told here — `redirect_uri_mismatch` and `invalid_client` are configuration
        # faults with obvious fixes, and both previously surfaced as a blank screen.
        code_name, description = _oauth_error(response)
        log.warning("token exchange refused by %s: %s (%s)", provider.label, code_name, description)
        raise ProviderError(
            Reason.INVALID_CREDENTIAL,
            f"{provider.label} refused the sign-in.",
            {"provider_error": code_name, "provider": provider.label},
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise ProviderError(
            Reason.IDENTITY_PROVIDER_UNAVAILABLE,
            f"{provider.label} returned a response we could not read.",
            {"provider": provider.label},
        ) from exc

    id_token = payload.get("id_token")
    if not isinstance(id_token, str) or not id_token:
        raise ProviderError(
            Reason.INVALID_CREDENTIAL,
            f"{provider.label} did not return an identity token. Check that the "
            "'openid' scope is requested.",
            {"provider": provider.label},
        )
    return id_token


def _oauth_error(response: httpx.Response) -> tuple[str, str]:
    try:
        body = response.json()
    except ValueError:
        return f"http_{response.status_code}", ""
    if not isinstance(body, dict):
        return f"http_{response.status_code}", ""
    error = body.get("error")
    description = body.get("error_description")
    return (
        str(error) if isinstance(error, str) else f"http_{response.status_code}",
        str(description)[:200] if isinstance(description, str) else "",
    )


async def _verify_id_token(
    provider: ProviderRecord,
    id_token: str,
    nonce: str | None,
) -> dict[str, Any]:
    """Verify signature, issuer, audience and expiry. Every check names its own failure."""
    settings = get_settings()
    assert provider.issuer is not None and provider.client_id is not None

    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as exc:
        raise ProviderError(
            Reason.INVALID_CREDENTIAL,
            f"{provider.label} returned a malformed identity token.",
        ) from exc

    # Only the key id is read here. `alg` comes from settings below, never from the
    # token: an attacker who picks the algorithm picks `none`, or an HMAC keyed on a
    # public verification key.
    kid = header.get("kid")
    if kid is not None and not isinstance(kid, str):
        raise ProviderError(
            Reason.INVALID_CREDENTIAL,
            f"{provider.label} returned an identity token with an unusable key id.",
        )

    try:
        key = await key_for_issuer(provider.issuer, provider.jwks_uri, kid)
    except UnknownKeyError as exc:
        raise ProviderError(
            Reason.INVALID_CREDENTIAL,
            f"{provider.label} signed with a key it does not publish.",
        ) from exc
    except JwksUnavailableError as exc:
        # 503, not 401: the token may be perfectly good and we cannot check it. Returning
        # a credentials error would make every console discard a valid session over the
        # provider's outage.
        raise ProviderError(
            Reason.IDENTITY_PROVIDER_UNAVAILABLE,
            f"We could not fetch {provider.label}'s verification keys.",
            {"provider": provider.label},
        ) from exc

    try:
        claims: dict[str, Any] = jwt.decode(
            id_token,
            key=key.key,
            algorithms=list(settings.oidc_algorithms),
            audience=provider.client_id,
            issuer=provider.issuer.rstrip("/"),
            leeway=settings.oidc_leeway_seconds,
            options={
                "require": ["exp", "iat", "sub", "aud", "iss"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_nbf": True,
                "verify_aud": True,
                "verify_iss": True,
            },
        )
    except jwt.ExpiredSignatureError as exc:
        # Distinguished from the rest on purpose: this one is almost always a clock, and
        # an operator told "expired" checks NTP where one told "invalid" checks the app
        # registration for an afternoon.
        raise ProviderError(
            Reason.INVALID_CREDENTIAL,
            "The sign-in took too long, or this server's clock is wrong. Try again.",
            {"leeway_seconds": settings.oidc_leeway_seconds},
        ) from exc
    except jwt.InvalidAudienceError as exc:
        raise ProviderError(
            Reason.PROVIDER_NOT_CONFIGURED,
            f"{provider.label}'s identity token is addressed to a different application.",
            {"expected_audience": provider.client_id},
        ) from exc
    except jwt.InvalidIssuerError as exc:
        raise ProviderError(
            Reason.PROVIDER_NOT_CONFIGURED,
            f"{provider.label} returned a token from an unexpected issuer.",
            {"expected_issuer": provider.issuer},
        ) from exc
    except jwt.PyJWTError as exc:
        log.info("id token rejected for provider %s: %s", provider.label, exc)
        raise ProviderError(
            Reason.INVALID_CREDENTIAL,
            f"{provider.label}'s identity token did not verify.",
        ) from exc

    # The nonce ties this token to the authorize request the browser started. The client
    # only sends one if it generated one, so an absent nonce on both sides is not an
    # error — but a mismatch is a token minted for some other flow.
    if nonce and claims.get("nonce") != nonce:
        raise ProviderError(
            Reason.INVALID_CREDENTIAL,
            "This sign-in response does not belong to the sign-in you started.",
        )

    return claims
