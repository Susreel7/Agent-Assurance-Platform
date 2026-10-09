"""Registry schemas — stable agent identity, immutable versions, ownership windows.

An agent's URN is what the estate knows it by; semver versions hang off that identity
without replacing it. Ownership uses validity windows so a past approval still names the
person who gave it after they change roles.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

_URN_PATTERN = r"^urn:aap:[a-z0-9-]+:[a-z0-9-]+:[a-z0-9-]+$"


class LifecycleState(StrEnum):
    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"
    RETIRED = "retired"


class OwnershipRole(StrEnum):
    ACCOUNTABLE = "accountable"
    APPROVER_OF_RECORD = "approver_of_record"
    TECHNICAL = "technical"
    CHANGE_AUTHORITY = "change_authority"
    BUSINESS = "business"


class DriftStatus(StrEnum):
    """Whether what is running matches what was signed off as the baseline."""

    ALIGNED = "aligned"
    DRIFTED = "drifted"
    UNKNOWN = "unknown"


class AgentCreate(BaseModel):
    urn: str = Field(min_length=10, max_length=256, pattern=_URN_PATTERN)
    display_name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=4000)
    owning_team: str | None = Field(default=None, max_length=128)
    lifecycle_state: LifecycleState = LifecycleState.DEV
    first_seen_source: str = Field(default="declared", max_length=32)


class AgentUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=4000)
    owning_team: str | None = Field(default=None, max_length=128)
    lifecycle_state: LifecycleState | None = None


class OwnershipOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: OwnershipRole
    principal_id: str
    source: str
    valid_from: datetime


class AgentSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    urn: str
    display_name: str
    lifecycle_state: LifecycleState
    owning_team: str | None
    current_version_id: UUID | None
    baseline_version_id: UUID | None

    # From the current version, via an outer join. Optional with a default so an agent
    # that has never published one is still a valid summary rather than an error.
    runtime_framework: str | None = None
    current_semver: str | None = None
    created_at: datetime
    updated_at: datetime


class AgentDetail(AgentSummary):
    description: str | None = None
    discovered_at: datetime | None = None
    first_seen_source: str
    ownership: list[OwnershipOut] = Field(default_factory=list)
    current_semver: str | None = None
    baseline_semver: str | None = None


class AgentPage(BaseModel):
    items: list[AgentSummary]
    total: int
    limit: int
    offset: int


class VersionPublish(BaseModel):
    semver: str = Field(min_length=1, max_length=64)
    descriptor: dict[str, Any]
    published_by: str = Field(min_length=1, max_length=320)
    environment: LifecycleState = LifecycleState.DEV
    vcs_provider: str | None = Field(default=None, max_length=64)
    vcs_repo: str | None = Field(default=None, max_length=512)
    vcs_ref: str | None = Field(default=None, max_length=256)

    @field_validator("descriptor")
    @classmethod
    def _descriptor_must_be_object(cls, v: dict[str, Any]) -> dict[str, Any]:
        if not v:
            raise ValueError("descriptor must not be empty")
        return v


class AgentVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    semver: str
    descriptor_digest: str
    runtime_framework: str | None
    runtime_language: str | None
    environment: LifecycleState
    autonomy: str | None
    vcs_provider: str | None
    vcs_repo: str | None
    vcs_ref: str | None
    published_at: datetime
    published_by: str


class OwnershipUpsert(BaseModel):
    role: OwnershipRole
    principal_id: str = Field(min_length=3, max_length=320)
    source: str = Field(default="declared", max_length=32)


class DriftReport(BaseModel):
    agent_id: UUID
    urn: str
    status: DriftStatus
    baseline_version_id: UUID | None
    current_version_id: UUID | None
    baseline_semver: str | None = None
    current_semver: str | None = None
