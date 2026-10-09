"""Authentication: token verification, claim mapping and tenant resolution.

Split so each piece can be reviewed for one thing:

* ``jwks`` fetches and caches verification keys, per issuer;
* ``tokens`` verifies a machine bearer token into a ``Principal``;
* ``claims`` reads one provider's claim names into a provider-neutral shape;
* ``providers`` runs the console sign-in exchange, one path per provider kind;
* ``orgs`` maps verified claims to an organisation.

Nothing here decides *what* a caller may do, and nothing here writes to the database.
Who a person is, and whether they may be admitted, is ``domains/auth/service.py``.
"""

from __future__ import annotations

from app.auth.claims import (
    ClaimMappingError,
    ResolvedClaims,
    normalise_email,
    resolve_claims,
)
from app.auth.orgs import OrgResolutionError, resolve_from_claims
from app.auth.principal import Principal
from app.auth.providers import (
    DEVELOPMENT_ISSUER,
    ProviderError,
    ProviderRecord,
    development_mode_enabled,
)
from app.auth.tokens import (
    IdentityProviderUnreachableError,
    TokenError,
    bearer_from_header,
    verify,
)

__all__ = [
    "DEVELOPMENT_ISSUER",
    "ClaimMappingError",
    "IdentityProviderUnreachableError",
    "OrgResolutionError",
    "Principal",
    "ProviderError",
    "ProviderRecord",
    "ResolvedClaims",
    "TokenError",
    "bearer_from_header",
    "development_mode_enabled",
    "normalise_email",
    "resolve_claims",
    "resolve_from_claims",
    "verify",
]
