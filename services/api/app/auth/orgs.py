"""From verified claims to an organisation.

This is the tenant boundary. A mistake here is a cross-tenant data leak, so the rules are
narrow on purpose:

* only claims listed in ``oidc_org_claims`` are consulted, in order;
* the first claim *present in the token* decides — if it has no binding the request
  fails, rather than falling through to the next claim. Falling through would let a
  caller whose `org_id` is unbound be resolved by their `hd` instead, which is a
  different customer's answer to a different question;
* a binding must be live (`disabled_at IS NULL`) and its organisation must exist.

In single-tenant installs none of this runs: there is one organisation and the token only
has to be valid.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import text

from app.config import get_settings
from app.db.session import admin_session

log = logging.getLogger(__name__)


class OrgResolutionError(Exception):
    """The caller is authenticated but we cannot say which organisation they act for."""


def _claim_as_str(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    # A numeric tenant id is legal JSON and some providers send one. Booleans are
    # excluded because `True` would stringify to a value that could match a binding.
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return None


async def resolve_from_claims(claims: dict[str, object]) -> UUID:
    """Look up the organisation bound to this token's tenant claim."""
    settings = get_settings()

    for claim_name in settings.oidc_org_claims:
        raw = _claim_as_str(claims.get(claim_name))
        if raw is None:
            continue

        # `iss` is the one claim that is also the binding's scope, and it is stored
        # without a trailing slash; normalise both sides the same way.
        value = raw.rstrip("/") if claim_name == "iss" else raw
        issuer = str(claims.get("iss", "")).rstrip("/")

        async with admin_session() as session:
            found = await session.execute(
                text("""
                    SELECT org_id
                      FROM identity_bindings
                     WHERE issuer = :issuer
                       AND claim_name = :claim_name
                       AND claim_value = :claim_value
                       AND disabled_at IS NULL
                """),
                {"issuer": issuer, "claim_name": claim_name, "claim_value": value},
            )
            org_id = found.scalar_one_or_none()

        if org_id is None:
            # Deliberately terminal. See the module docstring: trying the next claim
            # would resolve this caller by a weaker assertion than the one they made.
            log.warning("No live identity binding for issuer=%s claim=%s", issuer, claim_name)
            raise OrgResolutionError(
                f"no organisation is bound to the {claim_name!r} claim from this issuer"
            )

        return UUID(str(org_id))

    raise OrgResolutionError(
        "token carries none of the claims this deployment maps to an organisation "
        f"({', '.join(settings.oidc_org_claims)})"
    )
