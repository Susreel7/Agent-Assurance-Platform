"""Boundary models for console sign-in and session management.

Everything here is read by an unauthenticated caller or by a caller whose session is the
thing under discussion, so the rule is stricter than elsewhere: **no field may carry a
secret**. ``client_secret_ref``, ``token_url``, ``jwks_uri`` and ``claim_map`` are
deliberately absent from :class:`AuthProviderOut` — the login screen needs a button, not
the configuration behind it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

ProviderKind = Literal["oidc", "development"]

MAX_CODE_LENGTH = 4096
MAX_VERIFIER_LENGTH = 256


class AuthProviderOut(BaseModel):
    """One sign-in button, as the login screen needs it.

    ``authorize_url``, ``client_id`` and ``scopes`` are public by construction — they
    appear in the address bar of every sign-in. What is *not* here is everything the
    browser used to read from its own build environment and get wrong.
    """

    id: UUID
    kind: ProviderKind
    label: str
    authorize_url: str | None = None
    client_id: str | None = None
    scopes: str = "openid profile email"
    pkce: bool = True
    onboarding_mode: str


class AuthConfigOut(BaseModel):
    """The whole answer to "how do I sign in to this deployment?"."""

    account_hint: str | None = None
    """The account this set of providers belongs to, for the login screen's subtitle."""

    providers: list[AuthProviderOut] = Field(default_factory=list)

    unavailable_reason: str | None = None
    """Why the list is empty, in a sentence an operator can act on.

    An empty list with no explanation is what produced "unable to login with Entra ID":
    the screen rendered a button, the button did nothing, and nothing anywhere said that
    no provider was configured.
    """

    development: bool = False
    """Whether this deployment permits the ``development`` provider kind at all."""


class SessionStart(BaseModel):
    """What the callback screen posts. One shape for every provider kind.

    Validation is per kind rather than "all fields optional": a development sign-in that
    silently ignored a missing ``code`` would be indistinguishable from an OIDC one that
    lost it, and those want opposite fixes.
    """

    provider_id: UUID
    code: str | None = Field(default=None, max_length=MAX_CODE_LENGTH)
    code_verifier: str | None = Field(default=None, max_length=MAX_VERIFIER_LENGTH)
    redirect_uri: str | None = Field(default=None, max_length=2048)
    nonce: str | None = Field(default=None, max_length=MAX_VERIFIER_LENGTH)
    email: str | None = Field(default=None, max_length=320)
    """Development provider only: the local identity being claimed. Ignored otherwise."""

    @model_validator(mode="after")
    def _one_of_the_two_shapes(self) -> SessionStart:
        has_code = bool(self.code)
        if not has_code and not self.email:
            raise ValueError(
                "a sign-in needs either an authorization code or, for the development "
                "provider, an email address"
            )
        if has_code and not self.code_verifier:
            raise ValueError("an authorization code must be accompanied by its PKCE verifier")
        return self


class SessionOut(BaseModel):
    """Confirmation that a session now exists. The token itself is only ever a cookie."""

    session_id: UUID
    member_id: UUID
    account_id: UUID
    email: str
    display_name: str
    issued_at: datetime
    expires_at: datetime
    absolute_expires_at: datetime


class SessionSummary(BaseModel):
    """One row in "your sessions" on the profile page."""

    id: UUID
    issued_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    absolute_expires_at: datetime
    user_agent: str | None = None
    client_ip: str | None = None
    provider_label: str | None = None
    current: bool = False
    """The session making this request. The console refuses to let you revoke it by
    accident, and offers sign-out instead."""


class SessionListOut(BaseModel):
    items: list[SessionSummary]
