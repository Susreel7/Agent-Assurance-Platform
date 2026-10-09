"""Internal service bearer for typed human/console APIs."""

from __future__ import annotations

from uuid import UUID

from fastapi import Header

from evaluate.auth.schemas import InternalPrincipal
from evaluate.config import Settings, get_settings
from evaluate.errors import AuthenticationError


def require_internal_principal(
    authorization: str | None = Header(default=None, alias="Authorization"),
    header_organization_id: UUID | None = Header(default=None, alias="X-Organization-Id"),
    header_project_id: UUID | None = Header(default=None, alias="X-Project-Id"),
    header_actor: str | None = Header(default=None, alias="X-Actor"),
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
    if not header_actor or not header_actor.strip():
        raise AuthenticationError("X-Actor is required")
    return InternalPrincipal(
        actor=header_actor.strip(),
        organization_id=header_organization_id,
        project_id=header_project_id,
    )


def assert_path_scope(principal: InternalPrincipal, org_id: UUID, project_id: UUID) -> None:
    if principal.organization_id != org_id or principal.project_id != project_id:
        raise AuthenticationError("org/project headers must match path scope")
