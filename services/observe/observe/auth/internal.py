"""Internal service token for query APIs."""

from __future__ import annotations

from observe.config import Settings
from observe.errors import AuthenticationError


def verify_internal_token(settings: Settings, authorization: str | None) -> None:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationError("missing internal bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if token != settings.internal_service_token:
        raise AuthenticationError("invalid internal service token")
