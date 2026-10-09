"""Customer schemas — the client an organisation must satisfy.

Naming matters here and is easy to get wrong. ``organization`` is the tenant: the party
that pays us. ``customer`` is *their* client: the party whose security review must be
passed. Accreditation is always produced for a named customer, never in the abstract.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class CustomerStatus(StrEnum):
    PROSPECT = "prospect"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    OFFBOARDING = "offboarding"
    CHURNED = "churned"


class Sector(StrEnum):
    """Constrained because sector selects the default framework set. A bank and a
    hospital ask for different evidence, and free text cannot drive that."""

    FINANCIAL_SERVICES = "financial_services"
    INSURANCE = "insurance"
    HEALTHCARE = "healthcare"
    LIFE_SCIENCES = "life_sciences"
    PUBLIC_SECTOR = "public_sector"
    DEFENCE = "defence"
    TELECOM = "telecom"
    ENERGY = "energy"
    UTILITIES = "utilities"
    RETAIL = "retail"
    MANUFACTURING = "manufacturing"
    TRANSPORT = "transport"
    TECHNOLOGY = "technology"
    EDUCATION = "education"
    OTHER = "other"


class CriticalityTier(StrEnum):
    """How much rigour this client's review demands.

    Drives default frameworks, probe frequency, and whether a conditional accreditation
    is acceptable at all. Tier 1 is a client whose own regulator will eventually read
    the pack.
    """

    TIER_1 = "tier_1"
    TIER_2 = "tier_2"
    TIER_3 = "tier_3"


class ContactRole(StrEnum):
    SECURITY_REVIEWER = "security_reviewer"
    DATA_PROTECTION = "data_protection"
    BUSINESS_OWNER = "business_owner"
    PROCUREMENT = "procurement"
    TECHNICAL = "technical"
    EXECUTIVE_SPONSOR = "executive_sponsor"


class RequirementLevel(StrEnum):
    MANDATORY = "mandatory"
    EXPECTED = "expected"
    INFORMATIONAL = "informational"


class FrameworkKind(StrEnum):
    STANDARD = "standard"
    REGULATION = "regulation"
    CERTIFICATION = "certification"
    QUESTIONNAIRE = "questionnaire"
    INTERNAL_POLICY = "internal_policy"


class AnswerMode(StrEnum):
    EVIDENCE = "evidence"
    NARRATIVE = "narrative"
    HYBRID = "hybrid"
    NOT_APPLICABLE = "not_applicable"


# ----------------------------------------------------------------------
# Write models
# ----------------------------------------------------------------------

_JURISDICTION = r"^[A-Z]{2}$"


class CustomerCreate(BaseModel):
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")
    legal_name: str = Field(min_length=1, max_length=256)
    display_name: str | None = Field(default=None, max_length=128)

    status: CustomerStatus = CustomerStatus.PROSPECT
    sector: Sector | None = None
    criticality: CriticalityTier = CriticalityTier.TIER_2

    home_jurisdiction: str | None = Field(default=None, pattern=_JURISDICTION)
    operating_jurisdictions: list[str] = Field(default_factory=list)

    external_ref: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("operating_jurisdictions")
    @classmethod
    def _validate_jurisdictions(cls, v: list[str]) -> list[str]:
        import re

        for code in v:
            if not re.fullmatch(_JURISDICTION, code):
                raise ValueError(f"{code!r} is not an ISO 3166-1 alpha-2 code")
        # Deduplicate while preserving order so the stored array is stable.
        return list(dict.fromkeys(v))


class CustomerUpdate(BaseModel):
    """Every field optional. Slug is absent deliberately: it appears in URLs and in
    generated pack filenames, so renaming one would orphan existing references."""

    legal_name: str | None = Field(default=None, min_length=1, max_length=256)
    display_name: str | None = Field(default=None, max_length=128)
    status: CustomerStatus | None = None
    sector: Sector | None = None
    criticality: CriticalityTier | None = None
    home_jurisdiction: str | None = Field(default=None, pattern=_JURISDICTION)
    operating_jurisdictions: list[str] | None = None
    external_ref: str | None = Field(default=None, max_length=128)
    notes: str | None = Field(default=None, max_length=4000)


class ContactUpsert(BaseModel):
    role: ContactRole
    principal_id: str = Field(min_length=3, max_length=320)
    display_name: str | None = Field(default=None, max_length=128)


class FrameworkRequirementCreate(BaseModel):
    framework_id: UUID
    level: RequirementLevel = RequirementLevel.MANDATORY
    scoped_controls: list[str] = Field(
        default_factory=list,
        description="Empty means the whole framework. Clients often scope to a subset.",
    )
    required_since: date | None = None
    notes: str | None = Field(default=None, max_length=2000)


# ----------------------------------------------------------------------
# Read models
# ----------------------------------------------------------------------


class ContactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: ContactRole
    principal_id: str
    display_name: str | None
    valid_from: datetime


class FrameworkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    kind: FrameworkKind
    publisher: str | None
    version: str | None
    is_builtin: bool = Field(description="False when this tenant authored it")
    control_count: int


class FrameworkRequirementOut(BaseModel):
    id: UUID
    framework: FrameworkOut
    level: RequirementLevel
    scoped_controls: list[str]
    required_since: date | None
    notes: str | None


class FrameworkSuggestion(BaseModel):
    """Offered on customer creation so nobody picks from a list of forty."""

    framework: FrameworkOut
    reason: str = Field(description="Why this was suggested, shown next to the checkbox")
    confidence: str = Field(description="strong when sector and jurisdiction both match")


class CustomerSummary(BaseModel):
    """List-view row. Flat, and every count is a roll-up so the list needs no joins
    per row."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    legal_name: str
    display_name: str
    status: CustomerStatus
    sector: Sector | None
    criticality: CriticalityTier
    home_jurisdiction: str | None

    engagement_count: int = 0
    agent_count: int = 0
    framework_count: int = 0

    # The number that matters: agents delivered at a version this client never approved.
    drift_count: int = 0

    created_at: datetime


class CustomerDetail(CustomerSummary):
    operating_jurisdictions: list[str] = Field(default_factory=list)
    external_ref: str | None = None
    notes: str | None = None
    updated_at: datetime

    contacts: list[ContactOut] = Field(default_factory=list)
    frameworks: list[FrameworkRequirementOut] = Field(default_factory=list)


# ----------------------------------------------------------------------
# Readiness — the reason this module is more than CRUD
# ----------------------------------------------------------------------


class ControlGap(BaseModel):
    """A control this client demands that no evidence kind currently answers."""

    framework_slug: str
    framework_name: str
    control_ref: str
    title: str
    answer_mode: AnswerMode
    reason: str


class ReadinessByFramework(BaseModel):
    framework: FrameworkOut
    level: RequirementLevel

    controls_in_scope: int
    answerable: int = Field(description="At least one control mapping exists")
    partial: int = Field(description="Mapped, but no mapping claims full satisfaction")
    narrative_only: int = Field(description="Requires written narrative, not evidence")
    unmapped: int = Field(description="Nothing in the platform answers this yet")

    @property
    def coverage_pct(self) -> float:
        if self.controls_in_scope == 0:
            return 0.0
        return round(100.0 * self.answerable / self.controls_in_scope, 1)


class CustomerReadiness(BaseModel):
    """Can we even attempt this client's review, and where will we fall short?

    Computable from the company model alone, before a single evidence event exists,
    which makes it the first genuinely useful screen in the product: it turns "we will
    find out during the review" into a number known at onboarding.
    """

    customer_id: UUID
    customer_display_name: str

    frameworks: list[ReadinessByFramework]
    gaps: list[ControlGap] = Field(
        default_factory=list,
        description="Unmapped mandatory controls, worst first. The work queue.",
    )

    @property
    def total_controls(self) -> int:
        return sum(f.controls_in_scope for f in self.frameworks)

    @property
    def total_answerable(self) -> int:
        return sum(f.answerable for f in self.frameworks)

    @property
    def coverage_pct(self) -> float:
        if self.total_controls == 0:
            return 0.0
        return round(100.0 * self.total_answerable / self.total_controls, 1)

    def headline(self) -> str:
        if not self.frameworks:
            return "No frameworks required yet"
        blocking = sum(1 for g in self.gaps if g.answer_mode is not AnswerMode.NARRATIVE)
        base = (
            f"{self.total_answerable} of {self.total_controls} controls answerable "
            f"({self.coverage_pct}%)"
        )
        return f"{base} — {blocking} evidence gaps" if blocking else base
