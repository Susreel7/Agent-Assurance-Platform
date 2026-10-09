"""Workload identity boundary models."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.domains.registry.schemas import LifecycleState

ALLOWED_MODULES: frozenset[str] = frozenset({"router", "observe", "prompt", "evaluate"})

MAX_MODULES = 4
MAX_SCOPES = 32
MAX_MODEL_PATTERNS = 64


class WorkloadModule(StrEnum):
    ROUTER = "router"
    OBSERVE = "observe"
    PROMPT = "prompt"
    EVALUATE = "evaluate"


class TraceCaptureMode(StrEnum):
    NONE = "none"
    DIGEST = "digest"
    REDACTED = "redacted"
    FULL = "full"


def _dedupe_strings(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


class ProjectCreate(BaseModel):
    slug: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    trace_capture_mode: TraceCaptureMode = TraceCaptureMode.DIGEST
    payload_retention_days: int = Field(default=30, ge=1, le=3650)
    payload_encryption_key_ref: str | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def _full_capture_has_key(self) -> ProjectCreate:
        if self.trace_capture_mode is TraceCaptureMode.FULL and not self.payload_encryption_key_ref:
            raise ValueError("full capture requires payload_encryption_key_ref")
        return self


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    trace_capture_mode: TraceCaptureMode | None = None
    payload_retention_days: int | None = Field(default=None, ge=1, le=3650)
    payload_encryption_key_ref: str | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def _non_nullable_fields(self) -> ProjectUpdate:
        required = {"name", "trace_capture_mode", "payload_retention_days"}
        nulls = [
            field
            for field in required
            if field in self.model_fields_set and getattr(self, field) is None
        ]
        if nulls:
            raise ValueError(f"{', '.join(sorted(nulls))} cannot be null")
        return self


class ProjectOut(BaseModel):
    id: UUID
    org_id: UUID
    slug: str
    name: str
    trace_capture_mode: TraceCaptureMode
    payload_retention_days: int
    payload_encryption_key_ref: str | None
    created_at: datetime
    updated_at: datetime


class ProjectPage(BaseModel):
    items: list[ProjectOut]
    total: int
    limit: int
    offset: int


class WorkloadCredentialCreate(BaseModel):
    project_id: UUID
    name: str = Field(min_length=1, max_length=128)
    environment: LifecycleState
    agent_id: UUID | None = None
    member_id: UUID | None = None
    modules: list[WorkloadModule] = Field(min_length=1, max_length=MAX_MODULES)
    scopes: list[str] = Field(min_length=1, max_length=MAX_SCOPES)
    allowed_model_patterns: list[str] = Field(default_factory=list, max_length=MAX_MODEL_PATTERNS)
    rpm: int | None = Field(default=None, ge=1)
    tpm: int | None = Field(default=None, ge=1)
    max_concurrency: int | None = Field(default=None, ge=1)
    daily_budget_micros: int | None = Field(default=None, ge=1)
    expires_at: datetime | None = None

    @field_validator("modules")
    @classmethod
    def _dedupe_modules(cls, modules: list[WorkloadModule]) -> list[WorkloadModule]:
        seen: set[str] = set()
        out: list[WorkloadModule] = []
        for module in modules:
            if module.value in seen:
                continue
            seen.add(module.value)
            out.append(module)
        return out

    @field_validator("scopes")
    @classmethod
    def _scopes_bounded(cls, scopes: list[str]) -> list[str]:
        deduped = _dedupe_strings(scopes)
        for scope in deduped:
            if not scope or len(scope) > 128:
                raise ValueError("each scope must be 1-128 characters")
        return deduped

    @field_validator("allowed_model_patterns")
    @classmethod
    def _patterns_bounded(cls, patterns: list[str]) -> list[str]:
        deduped = _dedupe_strings(patterns)
        for pattern in deduped:
            if len(pattern) > 256:
                raise ValueError("each model pattern must be at most 256 characters")
        return deduped

    @field_validator("expires_at")
    @classmethod
    def _expires_in_future(cls, expires_at: datetime | None) -> datetime | None:
        if expires_at is None:
            return None
        if expires_at.tzinfo is None:
            raise ValueError("expires_at must be timezone-aware")
        now = datetime.now(tz=UTC)
        if expires_at.astimezone(UTC) <= now:
            raise ValueError("expires_at must be in the future")
        return expires_at.astimezone(UTC)


class WorkloadCredentialOut(BaseModel):
    id: UUID
    org_id: UUID
    project_id: UUID
    agent_id: UUID | None
    member_id: UUID | None
    name: str
    environment: LifecycleState
    modules: list[str]
    scopes: list[str]
    allowed_model_patterns: list[str]
    rpm: int | None = None
    tpm: int | None = None
    max_concurrency: int | None = None
    daily_budget_micros: int | None = None
    expires_at: datetime | None
    revoked_at: datetime | None
    active_generation_number: int | None
    last_used_at: datetime | None
    created_at: datetime
    created_by: str


class WorkloadCredentialCreated(WorkloadCredentialOut):
    """Returned once on create or rotate — the only time the secret is visible."""

    secret: str


class WorkloadCredentialPage(BaseModel):
    items: list[WorkloadCredentialOut]
    total: int
    limit: int
    offset: int


class WorkloadIntrospectionOut(BaseModel):
    active: bool = True
    credential_id: UUID
    generation_id: UUID
    organization_id: UUID
    project_id: UUID
    agent_id: UUID | None
    member_id: UUID | None
    environment: LifecycleState
    modules: list[str]
    scopes: list[str]
    allowed_model_patterns: list[str]
    expires_at: datetime | None
    capture_mode: TraceCaptureMode
    payload_retention_days: int
    payload_encryption_key_ref: str | None
    rpm: int | None = None
    tpm: int | None = None
    max_concurrency: int | None = None
    daily_budget_micros: int | None = None


class VerifiedWorkload(BaseModel):
    """Resolved machine principal after bearer verification."""

    credential_id: UUID
    generation_id: UUID
    org_id: UUID
    project_id: UUID
    agent_id: UUID | None
    member_id: UUID | None = None
    environment: LifecycleState
    modules: frozenset[str]
    scopes: frozenset[str]
    allowed_model_patterns: tuple[str, ...]
    rpm: int | None = None
    tpm: int | None = None
    max_concurrency: int | None = None
    daily_budget_micros: int | None = None
    expires_at: datetime | None
