"""Authentication boundary models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class IntrospectionResponse(BaseModel):
    active: bool = True
    credential_id: UUID
    generation_id: UUID
    organization_id: UUID
    project_id: UUID
    agent_id: UUID | None = None
    environment: str | None = None
    modules: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    allowed_model_patterns: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None


class WorkloadPrincipal(BaseModel):
    subject: str
    organization_id: UUID
    project_id: UUID
    agent_id: UUID | None = None
    environment: str | None = None
    modules: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    credential_id: UUID | None = None
    generation_id: UUID | None = None

    @classmethod
    def from_introspection(cls, data: IntrospectionResponse) -> WorkloadPrincipal:
        return cls(
            subject=str(data.credential_id),
            organization_id=data.organization_id,
            project_id=data.project_id,
            agent_id=data.agent_id,
            environment=data.environment,
            modules=data.modules,
            scopes=data.scopes,
            credential_id=data.credential_id,
            generation_id=data.generation_id,
        )


class InternalPrincipal(BaseModel):
    actor: str
    organization_id: UUID
    project_id: UUID
    roles: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
