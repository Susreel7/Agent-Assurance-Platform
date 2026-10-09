"""Shapes for the console's landing page."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field

from app.domains.operations.schemas import OperationsSnapshot
from app.domains.releases.schemas import ReleaseSummary


class AttentionItem(BaseModel):
    """One thing a person has to decide about, phrased as a consequence.

    `consequence` is the field that earns this screen its place. "Northwind is running an
    unapproved version" is a fact; "Northwind has not agreed to what is running for them"
    is why anyone should stop what they are doing. A list of facts gets skimmed.
    """

    id: str
    title: str
    consequence: str
    href: str
    severity: str = "warning"
    occurred_at: datetime


class AgentHealth(StrEnum):
    """One word for whether an agent needs attention.

    Four levels, not five, and no numeric score. A score invites arguing about the
    formula instead of fixing the agent, and a fifth level always turns out to mean
    "somewhere between the two I actually act on".
    """

    HEALTHY = "healthy"
    WARNING = "warning"
    AT_RISK = "at_risk"
    CRITICAL = "critical"


class EstateTotals(BaseModel):
    """Counts for the estate as a whole. Every one of these is a link to a screen."""

    agents_total: int = 0
    agents_in_production: int = 0
    agents_accredited: int = 0
    agents_unaccredited: int = 0
    agents_drifted: int = 0

    open_findings: int = 0
    open_critical_findings: int = 0
    approvals_waiting: int = 0

    # The share of service levels meeting their target, not the mean of their measured
    # values — those are in different units and cannot be averaged. Named for what it
    # counts so nobody reads it as an availability figure.
    slos_meeting_target_pct: float = 100.0


class HealthMix(BaseModel):
    healthy: int = 0
    warning: int = 0
    at_risk: int = 0
    critical: int = 0

    @property
    def total(self) -> int:
        return self.healthy + self.warning + self.at_risk + self.critical


class ComplianceBar(BaseModel):
    """One governance ratio, with the two numbers it came from.

    `covered` and `applicable` travel with the percentage on purpose: "80%" means
    something very different at four agents than at four hundred, and a bar without its
    denominator is the kind of number that gets quoted in a board pack unchallenged.
    """

    id: str
    label: str
    covered: int
    applicable: int
    pct: float
    explain: str


class AgentOpsRow(BaseModel):
    """One agent, with what it is and what it has been doing side by side.

    The join this product exists to make. A runtime dashboard shows cost and latency; a
    governance tool shows approvals and drift. Neither answers "is the expensive one also
    the unapproved one", which is the question that changes what somebody does next.
    """

    id: UUID
    display_name: str
    urn: str
    lifecycle_state: str
    runtime_framework: str | None
    semver: str | None

    health: AgentHealth
    accreditation_state: str | None
    drifted: bool
    open_findings: int
    open_critical_findings: int

    runs: int = 0
    success_rate_pct: float = 100.0
    cost_micros: int = 0
    p95_duration_ms: int = 0
    escalations: int = 0
    running_now: int = 0
    last_run_at: datetime | None = None

    mcp_servers: int = 0
    tools: int = 0


class HomeSummary(BaseModel):
    """Everything the landing page shows, in one request.

    It grew. The previous version answered only "is anything wrong", on the argument
    that every breakdown has a screen of its own — which was right for a console with no
    runtime data in it, and stopped being right once there was. An estate's cost, its
    failure rate and which framework it runs on are not follow-up questions; they are the
    first thing anyone asks, and making each one a separate navigation is how a dashboard
    ends up being opened once and never again.

    Still one request. The alternative is seven, arriving in an order the user can watch,
    which reads as a slow page rather than a rich one.
    """

    window_days: int = 30
    generated_at: datetime

    attention: list[AttentionItem] = Field(default_factory=list)
    estate: EstateTotals = Field(default_factory=EstateTotals)
    health: HealthMix = Field(default_factory=HealthMix)
    compliance: list[ComplianceBar] = Field(default_factory=list)

    operations: OperationsSnapshot

    agents: list[AgentOpsRow] = Field(default_factory=list)
    recent_releases: list[ReleaseSummary] = Field(default_factory=list)


class OrganizationOut(BaseModel):
    """One organisation, for the sign-in picker and the provisioning command."""

    id: UUID
    slug: str
    name: str
