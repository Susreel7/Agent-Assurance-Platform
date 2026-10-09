"""Engagement wire contracts.

An engagement is one delivery to one client, and it carries the terms that every
downstream evaluation is judged against: which regions data may touch, which data
classes are permitted, which agents are in scope, and at which version the client
signed off.

The drift models near the bottom of this file are the commercially important ones.
Everything above them exists so that drift can be computed.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ----------------------------------------------------------------------
# Enumerations. Values match the Postgres enums in migration 0002 exactly; a
# divergence here surfaces as an unreadable database error at insert time.
# ----------------------------------------------------------------------


class EngagementState(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


class CrossBorderTransfer(StrEnum):
    """Ordered least to most permissive, matching ``_CROSS_BORDER_LADDER``.

    Safeguards and consent are separate rungs because they are separate bases under
    GDPR Chapter V: Article 46 safeguards persist with the data, Article 49 consent
    authorises the transfer and then protects nothing. See D-020.
    """

    PROHIBITED = "prohibited"
    PERMITTED_WITH_SAFEGUARDS = "permitted_with_safeguards"
    PERMITTED_WITH_CONSENT = "permitted_with_consent"
    PERMITTED = "permitted"


class VersionUptake(StrEnum):
    """Whether a client accepts new agent versions without a fresh review.

    ``pinned`` is the default everywhere. A client who has not said otherwise has not
    consented to receiving a version they have not seen.
    """

    PINNED = "pinned"
    AUTO_PATCH = "auto_patch"
    AUTO_MINOR = "auto_minor"
    AUTO_ALL = "auto_all"


class ServiceLevelKind(StrEnum):
    AVAILABILITY = "availability"
    LATENCY_P95 = "latency_p95"
    LATENCY_P99 = "latency_p99"
    ERROR_RATE = "error_rate"
    RESOLUTION_P1 = "resolution_p1"
    RESOLUTION_P2 = "resolution_p2"
    FRESHNESS = "freshness"
    THROUGHPUT = "throughput"


class ServiceLevelWindow(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    ANNUAL = "annual"


class PenaltyBasis(StrEnum):
    NONE = "none"
    SERVICE_CREDIT = "service_credit"
    FEE_REDUCTION = "fee_reduction"
    TERMINATION_RIGHT = "termination_right"


class DriftSeverity(StrEnum):
    """How bad it is that a client is being served an unapproved version.

    ``none`` still appears in responses rather than being filtered out, so the console
    can show a green row instead of an absence and leave no doubt it was checked.
    """

    NONE = "none"
    INFORMATIONAL = "informational"
    MATERIAL = "material"
    CRITICAL = "critical"


# ----------------------------------------------------------------------
# Engagements
# ----------------------------------------------------------------------

_SLUG = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
_REGION = Field(max_length=32)


class EngagementBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)

    permitted_regions: list[str] = Field(default_factory=list)
    prohibited_regions: list[str] = Field(default_factory=list)
    cross_border_transfer: CrossBorderTransfer = CrossBorderTransfer.PROHIBITED
    permitted_data_classes: list[str] = Field(default_factory=list)

    contract_ref: str | None = Field(default=None, max_length=128)
    starts_on: date | None = None
    ends_on: date | None = None

    delivery_lead: str | None = Field(default=None, max_length=200)
    customer_approver: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def check_terms(self) -> EngagementBase:
        """Reject contradictory terms before they reach the database.

        Postgres enforces both of these too, but a check constraint violation reaches
        the operator as an opaque error naming a constraint. The residency rules are
        the terms of a contract, so a mistake in them deserves a sentence that says
        which region is the problem.
        """
        overlap = sorted(set(self.permitted_regions) & set(self.prohibited_regions))
        if overlap:
            raise ValueError(f"region(s) {', '.join(overlap)} are both permitted and prohibited")
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValueError("ends_on falls before starts_on")
        return self


class EngagementCreate(EngagementBase):
    customer_id: UUID
    slug: str = _SLUG
    state: EngagementState = EngagementState.DRAFT


class EngagementUpdate(BaseModel):
    """Every field optional. ``exclude_unset`` in the service distinguishes "set to
    null" from "not mentioned", which a PATCH must not conflate."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2000)
    state: EngagementState | None = None

    permitted_regions: list[str] | None = None
    prohibited_regions: list[str] | None = None
    cross_border_transfer: CrossBorderTransfer | None = None
    permitted_data_classes: list[str] | None = None

    contract_ref: str | None = Field(default=None, max_length=128)
    starts_on: date | None = None
    ends_on: date | None = None

    delivery_lead: str | None = Field(default=None, max_length=200)
    customer_approver: str | None = Field(default=None, max_length=200)


class EngagementSummary(BaseModel):
    """List-row shape. The three counts are what makes the list worth reading."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    customer_id: UUID
    slug: str
    name: str
    state: EngagementState
    starts_on: date | None = None
    ends_on: date | None = None
    created_at: datetime

    customer_display_name: str = ""
    # The portal link is `/portal/{customer_slug}/{slug}` — both halves, because an
    # engagement slug is only unique within one customer. See D-035.
    customer_slug: str = ""
    agents_in_scope: int = 0
    agents_drifting: int = 0
    slo_count: int = 0


class ServiceLevelUpsert(BaseModel):
    kind: ServiceLevelKind
    target: Decimal
    unit: str | None = Field(default=None, max_length=32)
    measurement_window: ServiceLevelWindow = ServiceLevelWindow.MONTHLY
    penalty_basis: PenaltyBasis = PenaltyBasis.NONE
    penalty_detail: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def check_penalty(self) -> ServiceLevelUpsert:
        if self.penalty_basis is not PenaltyBasis.NONE and not self.penalty_detail:
            raise ValueError("penalty_detail is required when a penalty basis is set")
        return self


class ServiceLevelOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: ServiceLevelKind
    target: Decimal
    unit: str | None = None
    measurement_window: ServiceLevelWindow
    penalty_basis: PenaltyBasis
    penalty_detail: str | None = None
    created_at: datetime


class ScopeAgentRequest(BaseModel):
    agent_id: UUID
    uptake: VersionUptake = VersionUptake.PINNED
    accredited_version_id: UUID | None = None
    deployed_version_id: UUID | None = None


class ScopeAgentUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    uptake: VersionUptake | None = None
    accredited_version_id: UUID | None = None
    deployed_version_id: UUID | None = None


class ScopedAgentOut(BaseModel):
    """One agent in scope for one engagement, with both versions resolved to labels.

    Carrying the semver strings rather than only the version ids is deliberate: the
    console's whole job on this screen is to let a human see "approved 2.1, running
    2.4" without a second request per row.
    """

    id: UUID
    agent_id: UUID
    agent_urn: str
    agent_display_name: str

    uptake: VersionUptake
    in_scope_since: datetime

    accredited_version_id: UUID | None = None
    accredited_semver: str | None = None
    deployed_version_id: UUID | None = None
    deployed_semver: str | None = None

    drift: DriftSeverity = DriftSeverity.NONE
    drift_reason: str = ""


class EngagementDetail(EngagementBase):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    customer_id: UUID
    customer_display_name: str = ""
    customer_slug: str = ""
    slug: str
    state: EngagementState
    created_at: datetime
    updated_at: datetime

    service_levels: list[ServiceLevelOut] = Field(default_factory=list)
    agents: list[ScopedAgentOut] = Field(default_factory=list)


# ----------------------------------------------------------------------
# Drift. The product's headline number.
# ----------------------------------------------------------------------


class DriftItem(BaseModel):
    """One client being served a version they have not approved."""

    engagement_id: UUID
    engagement_name: str
    customer_id: UUID
    customer_display_name: str
    customer_criticality: str

    agent_id: UUID
    agent_urn: str
    agent_display_name: str

    accredited_semver: str | None = None
    accredited_at: datetime | None = None
    deployed_semver: str | None = None
    deployed_at: datetime | None = None

    versions_behind: int = 0
    uptake: VersionUptake
    severity: DriftSeverity
    reason: str


class DriftReport(BaseModel):
    """Estate-wide drift, worst first.

    ``clean`` is reported alongside the drifting rows because the useful statement to a
    client is "142 of 147 deliveries are serving exactly what you approved", and that
    sentence needs the denominator.
    """

    items: list[DriftItem] = Field(default_factory=list)
    total_in_scope: int = 0
    clean: int = 0

    critical: int = 0
    material: int = 0
    informational: int = 0

    @property
    def headline(self) -> str:
        if not self.items:
            return f"All {self.total_in_scope} scoped deliveries match their approved version"
        return (
            f"{len(self.items)} of {self.total_in_scope} scoped deliveries are running "
            f"a version the client has not approved"
        )
