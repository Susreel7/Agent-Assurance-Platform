"""Authentication boundary models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class InternalPrincipal(BaseModel):
    actor: str
    organization_id: UUID
    project_id: UUID


class IntrospectionResponse(BaseModel):
    active: bool
    subject: str = ""
    organization_id: UUID
    project_id: UUID
    agent_id: UUID | None = None
    environment: str = "dev"
    modules: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    allowed_models: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None


class WorkloadPrincipal(BaseModel):
    subject: str
    organization_id: UUID
    project_id: UUID
    agent_id: UUID | None
    environment: str
    modules: list[str]
    scopes: list[str]
    allowed_models: list[str]

    @classmethod
    def from_introspection(cls, data: IntrospectionResponse) -> WorkloadPrincipal:
        return cls(
            subject=data.subject,
            organization_id=data.organization_id,
            project_id=data.project_id,
            agent_id=data.agent_id,
            environment=data.environment,
            modules=list(data.modules),
            scopes=list(data.scopes),
            allowed_models=list(data.allowed_models),
        )
