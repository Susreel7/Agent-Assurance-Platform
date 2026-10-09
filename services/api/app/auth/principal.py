"""Who is making a request.

A `Principal` is the verified result of a token, and the only thing downstream code is
allowed to believe about the caller. It is deliberately not the raw claim set: handlers
that reach into arbitrary claims end up depending on one provider's dialect, which is
what generic OIDC support exists to avoid.

`actor_ref` is the field that matters most in practice. Audit columns across the schema
(`published_by`, `triaged_by`, `resolved_by`, `submitted_by`) are free text today and are
filled from the request body, which means the record of who did something is whatever the
caller typed. Those call sites move to this value — a string derived from a verified
token, in the `person:` form NAMING.md section 4 fixes for human actors.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Principal:
    subject: str
    """The `sub` claim: stable, opaque, unique within the issuer. Never an email."""

    issuer: str
    email: str | None = None
    name: str | None = None
    scopes: frozenset[str] = frozenset()
    roles: frozenset[str] = frozenset()

    @property
    def actor_ref(self) -> str:
        """The canonical audit string for this caller.

        Email when the token carries one because a human reading an audit trail needs to
        recognise the name, falling back to the subject, which is always present. Both
        are prefixed so the form stays parseable and so a subject that happens to look
        like an email cannot be mistaken for a verified one.
        """
        if self.email:
            return f"person:{self.email}"
        return f"subject:{self.issuer}#{self.subject}"

    @classmethod
    def from_claims(cls, claims: dict[str, Any]) -> Principal:
        return cls(
            subject=str(claims["sub"]),
            issuer=str(claims.get("iss", "")),
            email=_optional_str(claims.get("email")),
            name=_optional_str(claims.get("name"))
            or _optional_str(claims.get("preferred_username")),
            scopes=_as_set(claims.get("scope") or claims.get("scp")),
            roles=_as_set(claims.get("roles") or claims.get("groups")),
        )


def _optional_str(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _as_set(value: object) -> frozenset[str]:
    """Normalise a claim that providers render three different ways.

    `scope` is a space-delimited string in the OAuth spec, Entra sends `scp` the same
    way, and `roles`/`groups` arrive as arrays. Treating any of them as the wrong shape
    silently yields an empty set, which for an authorisation input fails open on the
    "does the caller have this role" question.
    """
    if isinstance(value, str):
        return frozenset(part for part in value.split() if part)
    if isinstance(value, (list, tuple)):
        return frozenset(str(part) for part in value if isinstance(part, (str, int)))
    return frozenset()
