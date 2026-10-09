"""Internal service bearer for typed human/console APIs."""

from __future__ import annotations

from uuid import UUID

from fastapi import Header

from prompt.auth.schemas import InternalPrincipal
from prompt.config import Settings, get_settings
from prompt.errors import AuthenticationError


def require_internal_principal(
    authorization: str | None = Header(default=None, alias="Authorization"),
    header_organization_id: UUID | None = Header(default=None, alias="X-Organization-Id"),
    header_project_id: UUID | None = Header(default=None, alias="X-Project-Id"),
    actor: str | None = Header(default=None, alias="X-Actor"),
    internal_roles: str | None = Header(default=None, alias="X-Internal-Roles"),
    internal_scopes: str | None = Header(default=None, alias="X-Internal-Scopes"),
    settings: Settings | None = None,
) -> InternalPrincipal:
    s = settings or get_settings()
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthenticationError("missing internal bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if token != s.internal_service_token:
        raise AuthenticationError("invalid internal bearer token")
    if header_organization_id is None or header_project_id is None:
        raise AuthenticationError("X-Organization-Id and X-Project-Id are required")
    if not actor or not actor.strip():
        raise AuthenticationError("X-Actor is required")
    roles = [r.strip() for r in (internal_roles or "").split(",") if r.strip()]
    scopes = [s.strip() for s in (internal_scopes or "").split(",") if s.strip()]
    return InternalPrincipal(
        actor=actor.strip(),
        organization_id=header_organization_id,
        project_id=header_project_id,
        roles=roles,
        scopes=scopes,
    )


def assert_path_scope(principal: InternalPrincipal, org_id: UUID, project_id: UUID) -> None:
    if principal.organization_id != org_id or principal.project_id != project_id:
        raise AuthenticationError("org/project headers must match path scope")
