"""Control-plane workload token introspection."""

from __future__ import annotations

import httpx

from observe.auth.schemas import IntrospectionResponse, WorkloadPrincipal
from observe.config import Settings
from observe.errors import AuthenticationError, AuthorizationError


async def introspect_bearer(settings: Settings, authorization: str | None) -> WorkloadPrincipal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationError("missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise AuthenticationError("empty bearer token")

    url = settings.introspection_url
    async with httpx.AsyncClient(timeout=settings.introspection_timeout_seconds) as client:
        resp = await client.post(url, headers={"Authorization": f"Bearer {token}"})
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
    if "observe" not in principal.modules:
        raise AuthorizationError("observe module not entitled")
    if settings.required_ingest_scope not in principal.scopes:
        raise AuthorizationError("missing observe ingest scope")
    return principal


def assert_agent_binding(principal: WorkloadPrincipal, span_agent_id: str | None) -> None:
    if principal.agent_id is None or span_agent_id is None:
        return
    if str(principal.agent_id) != span_agent_id:
        raise AuthorizationError("agent identity mismatch for bound workload")
