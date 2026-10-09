"""Accreditation boundary models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AccreditationState(StrEnum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    SUSPENDED = "suspended"
    EXPIRED = "expired"
    WITHDRAWN = "withdrawn"


class ControlAnswerState(StrEnum):
    ANSWERED = "answered"
    PARTIAL = "partial"
    NARRATIVE = "narrative"
    UNANSWERABLE = "unanswerable"
    WAIVED = "waived"


class AccreditationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_version_id: UUID
    framework_id: UUID
    engagement_id: UUID | None = None
    reference: str | None = Field(default=None, max_length=128)


class AccreditationSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    reference: str
    agent_id: UUID
    agent_version_id: UUID
    framework_id: UUID
    engagement_id: UUID | None
    customer_id: UUID | None
    state: AccreditationState
    control_total: int
    control_answered: int
    control_gaps: int
    expires_at: datetime | None
    next_attestation_due: datetime | None
    updated_at: datetime


class AccreditationDetail(AccreditationSummary):
    submitted_by: str | None
    submitted_at: datetime | None
    approved_by: str | None
    approved_at: datetime | None
    suspended_at: datetime | None
    suspension_reason: str | None
    created_at: datetime


class AccreditationControlOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    control_id: UUID
    state: ControlAnswerState
    narrative: str | None
    evidence_kinds: list[str]
    evidence_count: int
    gap_reason: str | None


class AccreditationPackOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    format: str
    pack_uri: str
    pack_digest: str
    byte_size: int
    checkpoint_id: UUID | None
    signature: str | None
    signed_at: datetime | None
    rendered_at: datetime
    is_current: bool


class TransitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str = Field(max_length=256)
    reason: str | None = Field(default=None, max_length=2048)


class TransitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    accreditation_id: UUID
    from_state: AccreditationState | None
    to_state: AccreditationState
    actor: str
    reason: str | None
    triggered_by: str
    release_id: UUID | None
    created_at: datetime


class ReadinessGap(BaseModel):
    framework_id: UUID
    framework_slug: str
    control_ref: str
    title: str
    gap_reason: str


class PackRenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    format: str = Field(pattern="^(pdf|html|json)$")
    rendered_by: str = "person:api"


class ReadinessOut(BaseModel):
    customer_id: UUID
    frameworks: list[dict[str, object]]
    gaps: list[ReadinessGap]
