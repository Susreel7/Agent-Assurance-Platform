"""Materiality schemas.

The verdict types themselves live in ``releases/schemas.py``, because a verdict is a
property of a change and ``release_changes`` is where a change is stored. This module
adds only what the materiality domain itself exposes: the rule catalogue, the
adjudication queue, and the assessment envelope.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domains.releases.schemas import (
    AccreditationImpact,
    ChangeCategory,
    Materiality,
    SemanticChange,
    Severity,
)


class RuleOut(BaseModel):
    """One rule, as the settings screen and the accreditation pack render it.

    A customer asked to accept automated suspension wants to read the rules before
    agreeing, so ``rationale`` is written for them rather than for us.
    """

    id: str
    title: str
    verdict: Materiality
    rationale: str


class RuleCatalogue(BaseModel):
    rules: list[RuleOut]
    material_count: int
    review_count: int
    immaterial_count: int
    #: Rule ids this organisation has overridden, and to what.
    overrides: dict[str, Materiality] = Field(default_factory=dict)


class AssessmentOut(BaseModel):
    """The result of ruling on a whole release."""

    verdict: Materiality
    accreditation_impact: AccreditationImpact
    headline: str

    material_count: int
    review_count: int
    immaterial_count: int

    rules_fired: list[str]
    changes: list[SemanticChange]

    #: Which accreditations this assessment would move, and for which named customers.
    #: Empty when the release is not yet associated with an agent that holds any.
    affected_accreditations: list[AffectedAccreditation] = Field(default_factory=list)


class AffectedAccreditation(BaseModel):
    """An approval this change would move, named so the console can say whose it is.

    A reviewer's first question about a material change is never "which rule fired" —
    it is "who do I have to tell".
    """

    model_config = ConfigDict(from_attributes=True)

    accreditation_id: UUID
    reference: str
    state: str
    framework_name: str
    customer_name: str | None
    engagement_name: str | None
    expires_at: datetime | None


class ReviewQueueItem(BaseModel):
    """A change awaiting human adjudication.

    Ordered by consequence rather than by arrival: a needs-review change on an approved
    accreditation for a tier-one client is not the same as one on a development agent,
    and a queue sorted by timestamp buries the first behind the second.
    """

    change_id: UUID
    release_id: UUID
    agent_id: UUID
    agent_urn: str
    agent_display_name: str

    category: ChangeCategory
    subject: str
    summary: str
    severity: Severity
    rules_fired: list[str]

    accreditation_count: int
    customer_names: list[str]
    created_at: datetime


class ReviewQueue(BaseModel):
    items: list[ReviewQueueItem]
    total: int
    limit: int
    offset: int


class AdjudicationRequest(BaseModel):
    """A human's ruling on a change the engine could not decide.

    ``reason`` is required. An adjudication without one cannot be used to tune the rule
    set, which is the only reason the queue is worth anybody's time.
    """

    model_config = ConfigDict(extra="forbid")

    verdict: Materiality
    reason: str = Field(min_length=8, max_length=2000)

    #: Whether this decision should become a standing override for the rule that fired,
    #: rather than applying to this change alone. This is the mechanism by which a
    #: customer's decisions tune the rule set over time.
    apply_to_rule: bool = False


class AdjudicationOut(BaseModel):
    change_id: UUID
    verdict: Materiality
    previous_verdict: Materiality
    adjudicated_by: str
    adjudicated_at: datetime
    reason: str
    rule_override_created: str | None = None


class OverrideUpsert(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    verdict: Materiality
    reason: str = Field(min_length=8, max_length=2000)


# Deferred so AssessmentOut can reference AffectedAccreditation declared below it.
AssessmentOut.model_rebuild()
