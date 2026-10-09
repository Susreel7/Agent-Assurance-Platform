"""Control-plane workload token introspection."""

from __future__ import annotations

import httpx

from evaluate.auth.schemas import IntrospectionResponse, WorkloadPrincipal
from evaluate.config import Settings
from evaluate.errors import AuthenticationError, AuthorizationError


async def introspect_bearer(
    settings: Settings,
    authorization: str | None,
    *,
    required_module: str | None = None,
    required_scope: str | None = None,
) -> WorkloadPrincipal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationError("missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise AuthenticationError("empty bearer token")

    async with httpx.AsyncClient(timeout=settings.introspection_timeout_seconds) as client:
        resp = await client.post(
            settings.introspection_url,
            headers={"Authorization": f"Bearer {token}"},
        )
    if resp.status_code == 401:
        raise AuthenticationError("invalid workload token")
    if resp.status_code >= 500:
        raise AuthenticationError("introspection unavailable")
    if resp.status_code != 200:
        raise AuthenticationError(f"introspection rejected: {resp.status_code}")

    data = IntrospectionResponse.model_validate(resp.json())
    if not data.active:
        raise AuthenticationError("inactive workload token")
    principal = WorkloadPrincipal.from_introspection(data)
    module = required_module if required_module is not None else settings.required_workload_module
    scope = required_scope if required_scope is not None else settings.required_workload_scope
    if module not in principal.modules:
        raise AuthorizationError("evaluate module not entitled")
    if scope not in principal.scopes:
        raise AuthorizationError("missing evaluate scope")
    return principal
