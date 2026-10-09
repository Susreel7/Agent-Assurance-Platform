"""Models for migration 0005 — policy, findings, service levels, posture, accreditation.

Mirrors ``0005_assurance.py``. Thin by rule (AGENTS.md).

``Accreditation.state`` is the current value; ``AccreditationTransition`` is why it holds
that value. Never infer history from the column — a reviewer asked to re-approve
something always asks what happened last time, and the column cannot answer.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped

_accreditation_state = ENUM(
    "draft",
    "submitted",
    "approved",
    "suspended",
    "expired",
    "withdrawn",
    name="accreditation_state",
    create_type=False,
)
_control_answer_state = ENUM(
    "answered",
    "partial",
    "narrative",
    "unanswerable",
    "waived",
    name="control_answer_state",
    create_type=False,
)
_attestation_trigger = ENUM(
    "schedule",
    "change",
    "manual",
    "incident",
    name="attestation_trigger",
    create_type=False,
)
_attestation_result = ENUM(
    "pass", "fail", "degraded", "error", name="attestation_result", create_type=False
)
_finding_source = ENUM(
    "probe",
    "cve",
    "drift",
    "policy",
    "attestation",
    "manual",
    name="finding_source",
    create_type=False,
)
_finding_category = ENUM(
    "prompt_injection",
    "jailbreak",
    "unsafe_tool",
    "excessive_agency",
    "dependency",
    "model_change",
    "residency_violation",
    "oversight_gap",
    "secret_exposure",
    "output_leakage",
    "denial_of_wallet",
    "sla_breach",
    "ownership_gap",
    "bom_incomplete",
    "undeclared_capability",
    name="finding_category",
    create_type=False,
)
_finding_state = ENUM(
    "open",
    "triaged",
    "accepted",
    "mitigated",
    "fixed",
    "false_positive",
    name="finding_state",
    create_type=False,
)
_policy_decision_outcome = ENUM(
    "allow",
    "deny",
    "redact",
    "reroute",
    "require_approval",
    name="policy_decision_outcome",
    create_type=False,
)
_slo_kind = ENUM(
    "availability",
    "latency_p50",
    "latency_p95",
    "latency_p99",
    "success_rate",
    "resolution_p1",
    "resolution_p2",
    name="slo_kind",
    create_type=False,
)
_posture_band = ENUM(
    "strong", "adequate", "weak", "critical", name="posture_band", create_type=False
)


# ----------------------------------------------------------------------
# Policy
# ----------------------------------------------------------------------


class Policy(Base, TenantScoped):
    __tablename__ = "policies"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(Text, nullable=False)

    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PolicyVersion(Base, TenantScoped):
    """Immutable and signed. A policy editable in place cannot explain a decision made
    last quarter, which is the only reason to have a policy engine in an assurance
    product at all.

    Both the authored YAML and the parsed form are kept: the text is what a human
    reviewed and signed, the parsed form is what actually ran.
    """

    __tablename__ = "policy_versions"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    policy_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("policies.id", ondelete="CASCADE"), nullable=False
    )

    semver: Mapped[str] = mapped_column(Text, nullable=False)

    rules_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    rules_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    rules_digest: Mapped[str] = mapped_column(Text, nullable=False)

    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    effective_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    signature: Mapped[str | None] = mapped_column(Text)
    signing_key_ref: Mapped[str | None] = mapped_column(Text)

    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_by: Mapped[str] = mapped_column(Text, nullable=False)


class PolicyDecision(Base, TenantScoped):
    """Immutable. ``rule_id`` is recorded so the decision explains itself without
    re-running the evaluator against a policy that may since have moved on."""

    __tablename__ = "policy_decisions"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    policy_version_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("policy_versions.id"), nullable=False
    )
    agent_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    agent_version_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    engagement_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    outcome: Mapped[str] = mapped_column(_policy_decision_outcome, nullable=False)
    reason_code: Mapped[str] = mapped_column(Text, nullable=False)
    rule_id: Mapped[str] = mapped_column(Text, nullable=False)

    subject_ref: Mapped[str | None] = mapped_column(Text)
    data_classes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    requested_region: Mapped[str | None] = mapped_column(Text)
    effective_region: Mapped[str | None] = mapped_column(Text)

    # Soft reference: a foreign key into a partitioned table is not possible, and would
    # fight retention if it were.
    evidence_event_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


# ----------------------------------------------------------------------
# Security testing and findings
# ----------------------------------------------------------------------


class ProbeSuite(Base):
    """Not ``TenantScoped``: ``org_id`` NULL means we ship it, and the mixin implies a
    non-null org with a plain isolation policy. This table has neither.

    The one table in the system that holds prompt text by design — the adversarial
    inputs are ours, not the customer's.
    """

    __tablename__ = "probe_suites"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    org_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(_finding_category, nullable=False)

    probes_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    probe_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    content_digest: Mapped[str | None] = mapped_column(Text)

    is_builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    cadence: Mapped[str] = mapped_column(Text, nullable=False, server_default="weekly")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProbeRun(Base, TenantScoped):
    """``results_json`` holds per-probe verdicts with digests of the agent's response,
    never the response itself — a jailbreak transcript is customer content."""

    __tablename__ = "probe_runs"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    suite_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("probe_suites.id", ondelete="CASCADE"),
        nullable=False,
    )

    agent_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    agent_version_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[str | None] = mapped_column(_attestation_result)

    probes_run: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    probes_passed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    probes_failed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    results_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    summary_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")

    triggered_by: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)


class Finding(Base, TenantScoped):
    """Anything requiring remediation, whatever found it — probe, CVE scan or drift.

    ``fingerprint`` is the deduplication key. A CVE rediscovered on every scan must be
    one finding with a moving ``last_seen_at``, or the triage queue is unusable inside
    a week.
    """

    __tablename__ = "findings"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    agent_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    agent_version_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    source: Mapped[str] = mapped_column(_finding_source, nullable=False)
    category: Mapped[str] = mapped_column(_finding_category, nullable=False)
    severity: Mapped[str] = mapped_column(Text, nullable=False)

    title: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    subject_ref: Mapped[str | None] = mapped_column(Text)

    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(_finding_state, nullable=False)

    cve_id: Mapped[str | None] = mapped_column(Text)
    cvss_score: Mapped[Decimal | None] = mapped_column(Numeric(3, 1))
    component_name: Mapped[str | None] = mapped_column(Text)
    component_version: Mapped[str | None] = mapped_column(Text)
    fixed_version: Mapped[str | None] = mapped_column(Text)

    probe_run_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    release_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    evidence_event_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    remediation_due: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    triaged_by: Mapped[str | None] = mapped_column(Text)
    triaged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_by: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)


# ----------------------------------------------------------------------
# Service levels
#
# engagement_service_levels (0002) records what was promised. These record what was
# delivered. Keeping them apart is the difference between a contract clause and a
# measurement.
# ----------------------------------------------------------------------


class SloDefinition(Base, TenantScoped):
    __tablename__ = "slo_definitions"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    engagement_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    agent_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    service_level_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    kind: Mapped[str] = mapped_column(_slo_kind, nullable=False)
    target: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    unit: Mapped[str | None] = mapped_column(Text)
    measurement_window: Mapped[str] = mapped_column(Text, nullable=False, server_default="monthly")

    penalty_model: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )

    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SloMeasurement(Base, TenantScoped):
    """``sample_count`` is the denominator, so a 100% figure over three requests is not
    mistaken for a 100% figure over three million."""

    __tablename__ = "slo_measurements"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    slo_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("slo_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )

    bucket_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bucket_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    value: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    sample_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")

    is_breaching: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SloBreach(Base, TenantScoped):
    __tablename__ = "slo_breaches"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    slo_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("slo_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )

    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    worst_value: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    target: Mapped[Decimal] = mapped_column(Numeric, nullable=False)

    credit_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    credit_currency: Mapped[str] = mapped_column(Text, nullable=False, server_default="GBP")
    credit_basis: Mapped[str | None] = mapped_column(Text)

    acknowledged_by: Mapped[str | None] = mapped_column(Text)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    evidence_event_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))


class PostureScore(Base, TenantScoped):
    """Immutable. ``contributors`` is NOT NULL and checked non-empty by the migration:
    the HLD requires the score never appears without its factors, and the cheapest
    place to guarantee that is the schema."""

    __tablename__ = "posture_scores"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    agent_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    agent_version_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    score: Mapped[int] = mapped_column(Integer, nullable=False)
    band: Mapped[str] = mapped_column(_posture_band, nullable=False)

    contributors: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)

    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ruleset: Mapped[str] = mapped_column(Text, nullable=False, server_default="default")


# ----------------------------------------------------------------------
# Accreditation
# ----------------------------------------------------------------------


class Accreditation(Base, TenantScoped):
    """An approval of one version, under one framework, for one client.

    ``engagement_id`` is part of the identity rather than metadata: the same version
    approved under ISO 42001 for one bank is not approved for another bank running its
    own questionnaire, and conflating them would let the product claim approval that
    does not exist.
    """

    __tablename__ = "accreditations"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    agent_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    agent_version_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    framework_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    engagement_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    customer_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    reference: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(_accreditation_state, nullable=False)

    control_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    control_answered: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    control_partial: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    control_gaps: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    submitted_by: Mapped[str | None] = mapped_column(Text)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    suspension_reason: Mapped[str | None] = mapped_column(Text)
    suspended_by_release_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    last_attestation_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_attestation_due: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AccreditationTransition(Base, TenantScoped):
    """Immutable. One row per state change, which is what lets the console answer
    "why is this suspended, and who decided?" without inference."""

    __tablename__ = "accreditation_transitions"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    accreditation_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("accreditations.id", ondelete="CASCADE"),
        nullable=False,
    )

    from_state: Mapped[str | None] = mapped_column(_accreditation_state)
    to_state: Mapped[str] = mapped_column(_accreditation_state, nullable=False)

    actor: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    triggered_by: Mapped[str] = mapped_column(Text, nullable=False)

    release_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    attestation_run_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    evidence_event_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AccreditationControl(Base, TenantScoped):
    """One control's answer within one accreditation.

    ``gap_reason`` is required whenever the state is ``unanswerable`` — the migration
    enforces it. A gap list that says "not covered" without saying why cannot be acted
    on, and the readiness view is the screen that wins an onboarding conversation.
    """

    __tablename__ = "accreditation_controls"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    accreditation_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("accreditations.id", ondelete="CASCADE"),
        nullable=False,
    )
    control_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    state: Mapped[str] = mapped_column(_control_answer_state, nullable=False)

    narrative: Mapped[str | None] = mapped_column(Text)
    is_edited: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    evidence_kinds: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    evidence_event_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PgUUID(as_uuid=True)), nullable=False, server_default="{}"
    )

    gap_reason: Mapped[str | None] = mapped_column(Text)

    waived_by: Mapped[str | None] = mapped_column(Text)
    waived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    waiver_reason: Mapped[str | None] = mapped_column(Text)

    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answered_by: Mapped[str] = mapped_column(Text, nullable=False)


class AccreditationPack(Base, TenantScoped):
    """Immutable, signed, rendered artifact.

    ``checkpoint_id`` binds the pack to an evidence root the customer also holds, so it
    cannot be quietly re-rendered against rewritten history. That binding is what makes
    signing it worth anything.
    """

    __tablename__ = "accreditation_packs"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    accreditation_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("accreditations.id", ondelete="CASCADE"),
        nullable=False,
    )

    format: Mapped[str] = mapped_column(Text, nullable=False)
    pack_uri: Mapped[str] = mapped_column(Text, nullable=False)
    pack_digest: Mapped[str] = mapped_column(Text, nullable=False)
    byte_size: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")

    checkpoint_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    signature: Mapped[str | None] = mapped_column(Text)
    signing_key_ref: Mapped[str | None] = mapped_column(Text)
    signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    rendered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    rendered_by: Mapped[str] = mapped_column(Text, nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class AttestationRun(Base, TenantScoped):
    """A scheduled or triggered re-verification. What turns accreditation from a
    certificate in a folder into a living state."""

    __tablename__ = "attestation_runs"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    accreditation_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("accreditations.id", ondelete="CASCADE"),
        nullable=False,
    )

    trigger: Mapped[str] = mapped_column(_attestation_trigger, nullable=False)
    result: Mapped[str | None] = mapped_column(_attestation_result)

    checks_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, server_default="[]"
    )
    checks_run: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    checks_failed: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    findings_opened: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    caused_transition_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    release_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    triggered_by: Mapped[str] = mapped_column(Text, nullable=False)
    error: Mapped[str | None] = mapped_column(Text)
