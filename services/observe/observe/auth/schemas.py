"""Authentication boundary models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from observe.config import CaptureMode


class IntrospectionResponse(BaseModel):
    """Flat control-plane introspection payload."""

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
    capture_mode: CaptureMode = CaptureMode.DIGEST
    payload_retention_days: int = Field(default=30, ge=1, le=3650)
    payload_encryption_key_ref: str | None = None
    rpm: int | None = Field(default=None, ge=1)
    tpm: int | None = Field(default=None, ge=1)
    max_concurrency: int | None = Field(default=None, ge=1)
    daily_budget_micros: int | None = Field(default=None, ge=1)

    @field_validator("capture_mode", mode="before")
    @classmethod
    def _capture(cls, v: str | CaptureMode) -> CaptureMode:
        if isinstance(v, CaptureMode):
            return v
        return CaptureMode(str(v).lower())


class WorkloadPrincipal(BaseModel):
    subject: str
    organization_id: UUID
    project_id: UUID
    agent_id: UUID | None = None
    environment: str | None = None
    modules: list[str] = Field(default_factory=list)
    scopes: list[str] = Field(default_factory=list)
    capture_mode: CaptureMode = CaptureMode.DIGEST
    payload_retention_days: int = 30
    payload_encryption_key_ref: str | None = None
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
            capture_mode=data.capture_mode,
            payload_retention_days=data.payload_retention_days,
            payload_encryption_key_ref=data.payload_encryption_key_ref,
            credential_id=data.credential_id,
            generation_id=data.generation_id,
        )
