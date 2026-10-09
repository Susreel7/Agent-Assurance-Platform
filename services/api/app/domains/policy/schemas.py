"""Policy schemas — versioned rules and evaluation results."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class PolicyDomain(StrEnum):
    RESIDENCY = "residency"
    TOOL_PERMISSION = "tool_permission"
    OVERSIGHT = "oversight"
    RETENTION = "retention"
    MODEL_USE = "model_use"


class DecisionOutcome(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    REDACT = "redact"
    REROUTE = "reroute"
    REQUIRE_APPROVAL = "require_approval"


class PolicySummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    domain: PolicyDomain
    is_enabled: bool


class PolicyVersionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    policy_id: UUID
    semver: str
    rules_digest: str
    effective_from: datetime
    effective_to: datetime | None
    signature: str | None
    signing_key_ref: str | None
    published_at: datetime
    published_by: str


class PolicyPublish(BaseModel):
    semver: str = Field(min_length=1, max_length=32)
    rules_yaml: str = Field(min_length=1)
    published_by: str = Field(min_length=1, max_length=320)


class PolicyDecisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    policy_version_id: UUID
    agent_id: UUID | None
    agent_version_id: UUID | None
    engagement_id: UUID | None
    outcome: DecisionOutcome
    reason_code: str
    rule_id: str
    subject_ref: str | None
    data_classes: list[str]
    requested_region: str | None
    effective_region: str | None
    evidence_event_id: UUID | None
    occurred_at: datetime


class EvaluationRequest(BaseModel):
    agent_id: UUID | None = None
    agent_version_id: UUID | None = None
    engagement_id: UUID | None = None
    data_classes: list[str] = Field(default_factory=list)
    requested_region: str | None = Field(default=None, max_length=64)
    tool_name: str | None = Field(default=None, max_length=128)
    action_class: str | None = Field(default=None, max_length=64)
    lawful_basis: dict[str, str] = Field(
        default_factory=dict,
        description="data_class -> lawful basis label, required for special-category classes",
    )
    subject_ref: str | None = Field(default=None, max_length=256)


class EvaluationResult(BaseModel):
    outcome: DecisionOutcome
    reason_code: str
    rule_id: str
    effective_region: str | None = None


class ResidencyRule(BaseModel):
    id: str
    data_classes: list[str]
    permitted_regions: list[str]
    special_category: bool = False


class ToolAllowRule(BaseModel):
    id: str
    allowed_tools: list[str]


class OversightRule(BaseModel):
    id: str
    action_classes: list[str]


class RuleSet(BaseModel):
    """Parsed YAML shape the evaluator consumes."""

    residency: list[ResidencyRule] = Field(default_factory=list)
    tool_allowlist: ToolAllowRule | None = None
    oversight: OversightRule | None = None
