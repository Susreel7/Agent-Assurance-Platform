"""Release and semantic-change schemas.

The vocabulary here is the product. A source control diff tells you that line 42 of
``config.yaml`` changed. These types let the platform say "the request timeout dropped
from 30s to 5s, which will increase failures under load" — which is the thing a reviewer,
an owner and an approver can actually act on.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChangeCategory(StrEnum):
    """What kind of thing changed. Drives grouping in the release view."""

    MODEL = "model"
    INFERENCE_PARAMS = "inference_params"
    PROMPT = "prompt"
    TOOL = "tool"
    MCP_SERVER = "mcp_server"
    CAPABILITY = "capability"
    DEPENDENCY = "dependency"
    DATA_SOURCE = "data_source"
    DATA_CLASS = "data_class"
    RESIDENCY = "residency"
    GUARDRAIL = "guardrail"
    OVERSIGHT = "oversight"
    RESILIENCE = "resilience"
    DELEGATION = "delegation"
    DEPLOYMENT = "deployment"
    METADATA = "metadata"
    SKILL = "skill"
    SUB_AGENT = "sub_agent"
    CONFIG = "config"
    RULE_OBLIGATION = "rule_obligation"
    RULE_SOURCE = "rule_source"
    MODEL_POLICY = "model_policy"
    MEMORY_RETRIEVAL = "memory_retrieval"


CATEGORY_LABELS: dict[ChangeCategory, str] = {
    ChangeCategory.MODEL: "Model",
    ChangeCategory.INFERENCE_PARAMS: "Inference settings",
    ChangeCategory.PROMPT: "Instructions",
    ChangeCategory.TOOL: "Tools",
    ChangeCategory.MCP_SERVER: "MCP servers",
    ChangeCategory.CAPABILITY: "Capabilities",
    ChangeCategory.DEPENDENCY: "Dependencies",
    ChangeCategory.DATA_SOURCE: "Data sources",
    ChangeCategory.DATA_CLASS: "Data classes",
    ChangeCategory.RESIDENCY: "Data residency",
    ChangeCategory.GUARDRAIL: "Guardrails",
    ChangeCategory.OVERSIGHT: "Human oversight",
    ChangeCategory.RESILIENCE: "Resilience settings",
    ChangeCategory.DELEGATION: "Agent delegation",
    ChangeCategory.DEPLOYMENT: "Deployment",
    ChangeCategory.METADATA: "Metadata",
    ChangeCategory.SKILL: "Skills",
    ChangeCategory.SUB_AGENT: "Sub-agents",
    ChangeCategory.CONFIG: "Configuration",
    ChangeCategory.RULE_OBLIGATION: "Rule obligations",
    ChangeCategory.RULE_SOURCE: "Rule sources",
    ChangeCategory.MODEL_POLICY: "Model policy",
    ChangeCategory.MEMORY_RETRIEVAL: "Memory retrieval",
}


class ChangeOperation(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    MODIFIED = "modified"
    RENAMED = "renamed"


class ImpactDimension(StrEnum):
    """Why a reader should care. A release view shows these as badges, which is what
    lets someone triage twenty releases without reading any of them in full."""

    BEHAVIOUR = "behaviour"
    SECURITY = "security"
    COST = "cost"
    LATENCY = "latency"
    COMPLIANCE = "compliance"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class Materiality(StrEnum):
    MATERIAL = "material"
    IMMATERIAL = "immaterial"
    NEEDS_REVIEW = "needs_review"


class ReleaseState(StrEnum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    APPROVED = "approved"
    ROLLED_OUT = "rolled_out"
    ROLLED_BACK = "rolled_back"
    ABANDONED = "abandoned"


class AccreditationImpact(StrEnum):
    NONE = "none"
    REQUIRES_REVALIDATION = "requires_revalidation"
    SUSPENDS = "suspends"


class EnforcementLevel(StrEnum):
    """How strongly a change blocks rollout — advisory, overrideable, or hard."""

    ADVISORY = "advisory"
    SOFT = "soft"
    HARD = "hard"


def enforcement_for(materiality: Materiality) -> EnforcementLevel:
    if materiality is Materiality.MATERIAL:
        return EnforcementLevel.HARD
    if materiality is Materiality.NEEDS_REVIEW:
        return EnforcementLevel.SOFT
    return EnforcementLevel.ADVISORY


class SemanticChange(BaseModel):
    """One high-level change. Produced by the differ, never written by hand."""

    model_config = ConfigDict(frozen=True)

    category: ChangeCategory
    operation: ChangeOperation

    path: str = Field(description="Machine-addressable location, e.g. models[0].family")
    subject: str = Field(description="Human label, e.g. 'Primary model'")

    before_value: Any | None = None
    after_value: Any | None = None

    summary: str = Field(description="The one-line sentence shown in the release view")
    detail: str | None = Field(
        default=None,
        description="Optional consequence explanation, e.g. why a shorter timeout matters",
    )

    impacts: frozenset[ImpactDimension] = Field(default_factory=frozenset)
    severity: Severity = Severity.INFO
    verdict: Materiality = Materiality.IMMATERIAL
    rules_fired: tuple[str, ...] = ()
    detected_by: str = "descriptor_diff"


class ReleaseDiff(BaseModel):
    """The complete semantic delta between two agent versions."""

    from_semver: str | None
    to_semver: str
    changes: list[SemanticChange]

    @property
    def material_changes(self) -> list[SemanticChange]:
        return [c for c in self.changes if c.verdict is Materiality.MATERIAL]

    @property
    def review_changes(self) -> list[SemanticChange]:
        return [c for c in self.changes if c.verdict is Materiality.NEEDS_REVIEW]

    @property
    def categories(self) -> list[ChangeCategory]:
        seen: dict[ChangeCategory, None] = {}
        for c in self.changes:
            seen.setdefault(c.category, None)
        return list(seen)

    @property
    def impacts(self) -> frozenset[ImpactDimension]:
        if not self.changes:
            return frozenset()
        return frozenset().union(*(c.impacts for c in self.changes))

    @property
    def accreditation_impact(self) -> AccreditationImpact:
        if self.material_changes:
            return AccreditationImpact.SUSPENDS
        if self.review_changes:
            return AccreditationImpact.REQUIRES_REVALIDATION
        return AccreditationImpact.NONE

    def grouped(self) -> dict[ChangeCategory, list[SemanticChange]]:
        """Changes bucketed by category, in the display order of the enum."""
        out: dict[ChangeCategory, list[SemanticChange]] = {}
        for category in ChangeCategory:
            matching = [c for c in self.changes if c.category is category]
            if matching:
                out[category] = matching
        return out

    def headline(self) -> str:
        """One sentence for a notification or a commit status."""
        if not self.changes:
            return "No governed changes"
        parts = [
            f"{len(self.changes)} change{'s' if len(self.changes) != 1 else ''}",
        ]
        if self.material_changes:
            parts.append(f"{len(self.material_changes)} material")
        if self.review_changes:
            parts.append(f"{len(self.review_changes)} needing review")
        cats = ", ".join(CATEGORY_LABELS[c].lower() for c in self.categories[:3])
        return f"{' · '.join(parts)} — {cats}"


# ----------------------------------------------------------------------
# API models
# ----------------------------------------------------------------------


class ReleaseSummary(BaseModel):
    """List-view row. Deliberately flat so the release list needs no joins."""

    id: UUID
    agent_id: UUID
    agent_urn: str
    release_tag: str
    title: str | None
    state: ReleaseState

    from_semver: str | None
    to_semver: str

    change_count: int
    material_count: int
    review_count: int

    impacts: list[ImpactDimension]
    categories: list[ChangeCategory]

    accreditation_impact: AccreditationImpact
    affected_accreditations: int

    vcs_provider: str | None = None
    vcs_repo: str | None = None
    vcs_ref: str | None = None
    vcs_pr_ref: str | None = None

    proposed_by: str | None = None
    created_at: datetime


class ReviewSentence(BaseModel):
    """One deterministic plain-language line in the review brief."""

    model_config = ConfigDict(frozen=True)

    change_path: str
    rule_ids: tuple[str, ...]
    template_id: str
    text: str = Field(max_length=512)
    severity: Severity
    materiality: Materiality
    enforcement: EnforcementLevel


class ReleaseReviewBrief(BaseModel):
    """Structured summary for a non-technical approver — derived on read, never LLM-sourced."""

    release_id: UUID | None = None
    from_semver: str | None = None
    to_semver: str
    descriptor_digest: str
    headline: str
    re_accreditation: list[ReviewSentence] = Field(default_factory=list)
    needs_review: list[ReviewSentence] = Field(default_factory=list)
    informational: list[ReviewSentence] = Field(default_factory=list)
    accreditation_impact: AccreditationImpact
    blocking_rule_ids: list[str] = Field(default_factory=list)
    generated_at: datetime
    generator_label: str = "deterministic-templates"


class ReleaseDetail(ReleaseSummary):
    notes: str | None = None
    changes: list[SemanticChange]
    approved_by: str | None = None
    approved_at: datetime | None = None
    rolled_out_at: datetime | None = None
    to_descriptor_digest: str | None = None
    reviewed_descriptor_digest: str | None = None
    review_brief: ReleaseReviewBrief | None = None


class ReleaseGateVerdict(BaseModel):
    """Returned to CI before a deploy. The reason the platform gets adopted by
    engineering rather than only by governance."""

    allowed: bool
    headline: str
    material_count: int
    review_count: int
    accreditation_impact: AccreditationImpact
    enforcement: EnforcementLevel = EnforcementLevel.ADVISORY
    affected_accreditations: list[str] = Field(
        default_factory=list,
        description="Accreditation references that this release would suspend",
    )
    blocking_changes: list[SemanticChange] = Field(default_factory=list)
    advisory: list[str] = Field(default_factory=list)
    review_brief: ReleaseReviewBrief | None = None


class ReleaseCreate(BaseModel):
    agent_id: UUID
    from_version_id: UUID | None = None
    to_version_id: UUID
    release_tag: str = Field(min_length=1, max_length=128)
    title: str | None = Field(default=None, max_length=256)
    notes: str | None = Field(default=None, max_length=8000)
    vcs_provider: str | None = Field(default=None, max_length=64)
    vcs_repo: str | None = Field(default=None, max_length=512)
    vcs_ref: str | None = Field(default=None, max_length=256)
    vcs_pr_ref: str | None = Field(default=None, max_length=256)
    proposed_by: str | None = Field(default=None, max_length=320)


class ReleasePreviewRequest(BaseModel):
    """CI gate input — no persisted agent required."""

    before_descriptor: dict[str, Any] | None = None
    after_descriptor: dict[str, Any]


class ReleaseTransitionRequest(BaseModel):
    target_state: ReleaseState
    actor: str = Field(min_length=1, max_length=320)
    reviewed_descriptor_digest: str | None = Field(
        default=None,
        description="Required when approving; must match the target version digest reviewed",
    )


class ChangeAdjudicateRequest(BaseModel):
    verdict: Materiality
    adjudicated_by: str = Field(min_length=1, max_length=320)
    adjudication_reason: str = Field(min_length=1, max_length=2000)


class ReleaseChangeOut(SemanticChange):
    """Persisted change row, including its identifier for adjudication."""

    id: UUID


class ReleasePage(BaseModel):
    items: list[ReleaseSummary]
    total: int
    limit: int
    offset: int
