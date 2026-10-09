"""Assurance boundary models — findings, probes and posture."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FindingSource(StrEnum):
    PROBE = "probe"
    CVE = "cve"
    DRIFT = "drift"
    POLICY = "policy"
    ATTESTATION = "attestation"
    MANUAL = "manual"


class FindingCategory(StrEnum):
    PROMPT_INJECTION = "prompt_injection"
    JAILBREAK = "jailbreak"
    UNSAFE_TOOL = "unsafe_tool"
    EXCESSIVE_AGENCY = "excessive_agency"
    DEPENDENCY = "dependency"
    MODEL_CHANGE = "model_change"
    RESIDENCY_VIOLATION = "residency_violation"
    OVERSIGHT_GAP = "oversight_gap"
    SECRET_EXPOSURE = "secret_exposure"
    OUTPUT_LEAKAGE = "output_leakage"
    DENIAL_OF_WALLET = "denial_of_wallet"
    SLA_BREACH = "sla_breach"
    OWNERSHIP_GAP = "ownership_gap"
    BOM_INCOMPLETE = "bom_incomplete"
    UNDECLARED_CAPABILITY = "undeclared_capability"


class FindingState(StrEnum):
    OPEN = "open"
    TRIAGED = "triaged"
    ACCEPTED = "accepted"
    MITIGATED = "mitigated"
    FIXED = "fixed"
    FALSE_POSITIVE = "false_positive"


class Severity(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


_RESOLVED_STATES = frozenset(
    {FindingState.FIXED, FindingState.FALSE_POSITIVE, FindingState.ACCEPTED}
)


class FindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID | None
    agent_version_id: UUID | None
    source: FindingSource
    category: FindingCategory
    severity: Severity
    title: str
    detail: str | None
    subject_ref: str | None
    fingerprint: str
    state: FindingState
    first_seen_at: datetime
    last_seen_at: datetime
    remediation_due: datetime | None
    triaged_by: str | None
    triaged_at: datetime | None
    resolved_by: str | None
    resolved_at: datetime | None
    resolution_note: str | None


class FindingCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID | None = None
    agent_version_id: UUID | None = None
    source: FindingSource
    category: FindingCategory
    severity: Severity
    title: str = Field(max_length=512)
    detail: str | None = Field(default=None, max_length=4096)
    subject_ref: str | None = Field(default=None, max_length=512)
    remediation_due: datetime | None = None
    cve_id: str | None = None
    probe_run_id: UUID | None = None
    release_id: UUID | None = None


class FindingTriage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    triaged_by: str = Field(max_length=256)
    remediation_due: datetime | None = None


class FindingResolve(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: FindingState
    resolved_by: str = Field(max_length=256)
    resolution_note: str | None = Field(default=None, max_length=2048)


class FindingPage(BaseModel):
    items: list[FindingOut]
    total: int
    limit: int
    offset: int


class SeverityCounts(BaseModel):
    critical: int = 0
    high: int = 0
    medium: int = 0
    low: int = 0
    info: int = 0


class ProbeSuiteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    category: FindingCategory
    probe_count: int
    cadence: str
    is_builtin: bool
    content_digest: str | None = None
    owasp_coverage: list[str] = Field(default_factory=list)


class JudgeAdvisoryOut(BaseModel):
    verdict: str
    disagrees_with_oracle: bool
    recorded: bool = True


class ProbeCaseResultOut(BaseModel):
    """One probe row — oracle and judge counts stay on separate fields."""

    probe_id: str
    expect: str
    oracle_verdict: str
    oracle_passed: bool
    execution_verified: bool
    gate_passed: bool
    judge_advisory: JudgeAdvisoryOut | None = None
    recognition_execution_gap: bool = False
    response_digest: str
    signals: dict[str, object] = Field(default_factory=dict)
    ambiguous: bool = False


class ProbeRunSummaryOut(BaseModel):
    suite_content_digest: str
    valid_rollouts: int
    attempt_budget: int
    execution_verified_pass: int
    execution_verified_fail: int
    judge_advisory_pass: int
    judge_advisory_fail: int
    oracle_needs_review: int
    judge_oracle_disagreements: int
    gate_level: str
    gate_blocks_release: bool


class ProbeRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    suite_id: UUID
    agent_id: UUID
    agent_version_id: UUID
    started_at: datetime
    finished_at: datetime | None
    result: str | None
    probes_run: int
    probes_passed: int
    probes_failed: int
    triggered_by: str


class ProbeRunDetailOut(ProbeRunOut):
    results: list[ProbeCaseResultOut] = Field(default_factory=list)
    summary: ProbeRunSummaryOut | None = None
    suite_slug: str | None = None


class ProbeStatusEntry(BaseModel):
    suite_slug: str
    suite_name: str
    last_run_id: UUID | None
    last_result: str | None
    last_started_at: datetime | None
    stale: bool
    gate_required: bool = False


class AgentProbeStatusOut(BaseModel):
    agent_id: UUID
    agent_version_id: UUID
    suites: list[ProbeStatusEntry]


class PostureContributor(BaseModel):
    factor: str
    points: int
    detail: str


class PostureScoreOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    agent_version_id: UUID | None
    score: int
    band: str
    contributors: list[PostureContributor]
    computed_at: datetime
    ruleset: str


class PostureInputs(BaseModel):
    """Facts fed into posture scoring — kept explicit so arithmetic is unit-testable."""

    model_config = ConfigDict(extra="forbid")

    open_critical_count: int = 0
    open_high_count: int = 0
    accreditation_suspended: bool = False
    accreditation_drift: bool = False
    overdue_remediation_count: int = 0
    unmapped_control_count: int = 0
    missing_ownership: bool = False
    declared_not_observed_edge_count: int = 0
