"""One claim reader for every identity provider.

Entra calls the stable subject `oid`, Okta calls it `sub`, Keycloak calls it `sub` and
ADFS may only give you `upn`. Without a mapping this becomes five code paths, and the
fifth one is written in a hurry against a customer's tenant at four in the afternoon.

``claim_map`` on the provider row is that mapping. It is data, so adding a provider whose
claim names nobody has seen before is a configuration change.

Three rules are not configurable, because each of them has been a real incident somewhere:

* **The subject is never derived from an email.** Email addresses are reassigned when
  people leave and renamed when people marry; `oid`/`sub` are not. A subject derived from
  an email means the next holder of that address inherits the previous holder's history.
* **An email is verified only when the provider says so**, or when the provider is marked
  domain-authoritative. An unverified email that is trusted is an account takeover: the
  resolver links an IdP subject to whichever member already holds that address.
* **The first present, non-empty value wins** and the rest are not consulted. Falling
  through on a *present but unmapped* value is how a caller gets resolved by a weaker
  assertion than the one they actually made.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Used when a provider's `claim_map` omits a key. These are the claim names the four
# providers we have actually seen emit, in the order a correct answer is most likely.
DEFAULT_CLAIM_MAP: dict[str, Any] = {
    "subject": ["oid", "sub"],
    "email": ["email", "preferred_username", "upn"],
    "name": ["name", "displayName", "preferred_username"],
    "groups": ["groups", "roles"],
    "employee_ref": ["employeeid", "onprem_sam_account_name"],
    "manager": ["manager_upn"],
    "mfa": {"claim": "amr", "contains": ["mfa", "hwk", "otp", "pwd_mfa", "swk"]},
}

MAX_EMAIL_LENGTH = 320
MAX_GROUPS = 512


class ClaimMappingError(Exception):
    """The token is valid but does not carry what this provider promised it would."""


@dataclass(frozen=True, slots=True)
class ResolvedClaims:
    """What the resolver needs, extracted once and named consistently."""

    subject: str
    issuer: str
    email: str | None
    email_verified: bool
    display_name: str
    groups: list[str] = field(default_factory=list)
    mfa_verified: bool = False
    employee_ref: str | None = None
    manager: str | None = None


def _candidates(claim_map: dict[str, Any], key: str) -> list[str]:
    """The claim names to try for ``key``, in order.

    A mapping may give a string or a list; both mean the same thing, and accepting only
    one of them would make half the examples in `design/02` invalid configuration.
    """
    configured = claim_map.get(key, DEFAULT_CLAIM_MAP.get(key))
    if isinstance(configured, str):
        return [configured]
    if isinstance(configured, list):
        return [name for name in configured if isinstance(name, str) and name]
    return []


def _first_string(claims: dict[str, Any], names: list[str]) -> str | None:
    for name in names:
        value = claims.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
        # A numeric employee number is legal JSON and some directories send one.
        # Booleans are excluded: `True` would stringify into something that could match.
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
    return None


def _string_list(claims: dict[str, Any], names: list[str]) -> list[str]:
    for name in names:
        value = claims.get(name)
        if isinstance(value, list):
            found = [item.strip() for item in value if isinstance(item, str) and item.strip()]
            if found:
                return found[:MAX_GROUPS]
        if isinstance(value, str) and value.strip():
            # Space- or comma-separated is how several providers send a short group list.
            parts = [part for part in value.replace(",", " ").split() if part]
            if parts:
                return parts[:MAX_GROUPS]
    return []


def _mfa(claims: dict[str, Any], claim_map: dict[str, Any]) -> bool:
    rule = claim_map.get("mfa", DEFAULT_CLAIM_MAP["mfa"])
    if not isinstance(rule, dict):
        return False
    name = rule.get("claim")
    wanted = rule.get("contains")
    if not isinstance(name, str) or not isinstance(wanted, list):
        return False
    present = _string_list(claims, [name])
    return any(value in present for value in wanted if isinstance(value, str))


def normalise_email(value: str | None) -> str | None:
    """Lower-cased and bounded, or ``None``.

    Case folding is the whole of it: `members` is uniquely indexed on `lower(email)`, so
    an address that differs only in case must resolve to the same member rather than to a
    duplicate that nobody can tell apart in a list.

    The shape check is deliberately just "a local part, an @, and a domain". It used to
    also require a dot in the domain, which reads like a reasonable sanity check and is
    not one: `someone@localhost` is a valid address and is exactly what the development
    provider signs in, so the rule made that provider incapable of resolving anybody.
    Nothing is gained by guessing harder here — whether an address is *acceptable* is
    decided by the provider's `email_domains` allowlist, which is a list of domains
    somebody configured rather than a pattern.
    """
    if value is None:
        return None
    candidate = value.strip().lower()
    if not candidate or len(candidate) > MAX_EMAIL_LENGTH:
        return None
    local, separator, domain = candidate.partition("@")
    if not separator or not local or not domain or "@" in domain:
        return None
    return candidate


def resolve_claims(
    claims: dict[str, Any],
    *,
    claim_map: dict[str, Any],
    issuer: str,
    domain_authoritative: bool = False,
) -> ResolvedClaims:
    """Read one token's claims through one provider's mapping.

    Raises :class:`ClaimMappingError` when the subject is absent, which is the only
    genuinely fatal case: everything else has a defensible empty value, but a token with
    no stable subject cannot be bound to a person at all.
    """
    subject = _first_string(claims, _candidates(claim_map, "subject"))
    if subject is None:
        raise ClaimMappingError(
            "the token carries none of the claims configured as this provider's subject "
            f"({', '.join(_candidates(claim_map, 'subject')) or 'none configured'})"
        )

    email = normalise_email(_first_string(claims, _candidates(claim_map, "email")))

    # `email_verified` absent is not the same as false — several providers simply do not
    # emit it — but treating absence as verified is how an unverified address gets linked
    # to an existing member. Absence is false unless the provider is domain-authoritative.
    asserted = claims.get("email_verified")
    email_verified = bool(email) and (asserted is True or domain_authoritative)

    display_name = _first_string(claims, _candidates(claim_map, "name")) or email or subject

    return ResolvedClaims(
        subject=subject,
        issuer=issuer,
        email=email,
        email_verified=email_verified,
        display_name=display_name[:200],
        groups=_string_list(claims, _candidates(claim_map, "groups")),
        mfa_verified=_mfa(claims, claim_map),
        employee_ref=_first_string(claims, _candidates(claim_map, "employee_ref")),
        manager=_first_string(claims, _candidates(claim_map, "manager")),
    )
