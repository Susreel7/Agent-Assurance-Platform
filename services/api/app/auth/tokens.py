"""Bearer token verification.

The whole security boundary of the product is this function plus the org resolution that
follows it, so it is written to be read in one sitting.

Every check below corresponds to a known attack rather than to a spec checkbox:

* the algorithm comes from configuration, never from the token header, because an
  attacker who picks the algorithm picks `none` or an HMAC keyed on the public key;
* `aud` is required, or any token the issuer minted for a different relying party is
  accepted here;
* `iss` is required and compared to configuration, or a token from any issuer whose keys
  we happen to have cached is accepted;
* `exp` and `iat`/`nbf` are enforced with bounded leeway, because unbounded clock skew
  makes expiry advisory.
"""

from __future__ import annotations

import logging

import jwt

from app.auth.jwks import JwksUnavailableError, UnknownKeyError, key_for
from app.auth.principal import Principal
from app.config import get_settings

log = logging.getLogger(__name__)


class TokenError(Exception):
    """The token is absent, malformed, expired or not addressed to us."""


class IdentityProviderUnreachableError(Exception):
    """We could not obtain keys to verify with. Not the caller's fault."""


def bearer_from_header(authorization: str | None) -> str:
    if not authorization:
        raise TokenError("missing Authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise TokenError("Authorization header must be 'Bearer <token>'")
    return token.strip()


async def verify(token: str) -> tuple[Principal, dict[str, object]]:
    """Verify a bearer token and return its principal and full claim set.

    The claims come back alongside the principal because org resolution needs claims the
    principal deliberately does not carry — the tenant claim is provider-specific and has
    no business being part of a caller identity.
    """
    settings = get_settings()
    if settings.oidc_issuer is None and settings.oidc_jwks_url is None:
        raise IdentityProviderUnreachableError("no OIDC issuer configured")

    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise TokenError(f"malformed token: {exc}") from exc

    # Read only the key id. Anything else in an unverified header is attacker-controlled;
    # in particular `alg` is passed to `decode` from settings below, not from here.
    kid = header.get("kid")
    if kid is not None and not isinstance(kid, str):
        raise TokenError("token header 'kid' must be a string")

    try:
        key = await key_for(kid)
    except UnknownKeyError as exc:
        raise TokenError(str(exc)) from exc
    except JwksUnavailableError as exc:
        # A 401 here would tell the caller their credentials are bad when the truth is
        # that our dependency is down, and would make every client discard a valid
        # session over our outage.
        log.error("Cannot verify tokens: %s", exc)
        raise IdentityProviderUnreachableError(str(exc)) from exc

    try:
        claims = jwt.decode(
            token,
            key=key.key,
            algorithms=list(settings.oidc_algorithms),
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
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
    except jwt.PyJWTError as exc:
        # The reason is logged, not returned. Telling an unauthenticated caller which
        # check failed maps out the configuration for them.
        log.info("Token rejected: %s", exc)
        raise TokenError("token is not valid for this service") from exc

    return Principal.from_claims(claims), claims
