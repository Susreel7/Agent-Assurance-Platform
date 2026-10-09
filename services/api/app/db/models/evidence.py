"""Models for migration 0003 — the evidence store.

Mirrors ``0003_evidence.py``. Thin by rule (AGENTS.md): no relationships, no behaviour.

``EvidenceEvent`` declares a composite primary key because the table is partitioned by
range on ``occurred_at`` and Postgres requires the partition key inside the key. That is
not a modelling choice to revisit — it is what the partitioning costs.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ARRAY, BigInteger, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped

_evidence_kind = ENUM(
    "model_inventory",
    "tool_permission_inventory",
    "data_class_inventory",
    "bom_completeness",
    "ownership_record",
    "residency_proof",
    "oversight_record",
    "change_history",
    "materiality_verdict",
    "adversarial_probe",
    "vulnerability_scan",
    "service_level_attainment",
    "chain_integrity",
    "accreditation_decision",
    "attestation_run",
    "policy_decision",
    "routing_decision",
    "failover_event",
    "incident_record",
    "approval_record",
    "prompt_integrity",
    "delegation_record",
    "guardrail_activation",
    "retention_proof",
    "access_review",
    name="evidence_kind",
    create_type=False,
)
_evidence_outcome = ENUM(
    "observed",
    "allow",
    "deny",
    "redact",
    "reroute",
    "require_approval",
    "pass",
    "fail",
    "degraded",
    "error",
    name="evidence_outcome",
    create_type=False,
)


class EvidenceBatch(Base, TenantScoped):
    """A sealed group of events with an RFC 6962 Merkle root over them.

    The hash chain lives here rather than on individual events: chaining every row
    serialises ingest behind one lock, while chaining batches keeps tamper detection
    and adds inclusion proofs. ``tree_size`` is cumulative across the organisation, so
    a consumer holding an older checkpoint can confirm the log only ever grew.
    """

    __tablename__ = "evidence_batches"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    seq: Mapped[int] = mapped_column(BigInteger, nullable=False)

    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    leaf_count: Mapped[int] = mapped_column(Integer, nullable=False)
    tree_size: Mapped[int] = mapped_column(BigInteger, nullable=False)

    merkle_root: Mapped[str] = mapped_column(Text, nullable=False)
    prev_batch_digest: Mapped[str] = mapped_column(Text, nullable=False)
    batch_digest: Mapped[str] = mapped_column(Text, nullable=False)

    sealed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    sealed_by: Mapped[str] = mapped_column(Text, nullable=False)

    signature: Mapped[str | None] = mapped_column(Text)
    signing_key_ref: Mapped[str | None] = mapped_column(Text)


class EvidenceEvent(Base, TenantScoped):
    """One governed fact. Append-only, with anchoring written once by the sealer.

    Holds digests, classifications and decisions. Never prompts, completions or tool
    arguments — that is AGENTS.md rule 5, and CHECK constraints in the migration bound
    every text field so the schema itself makes payload capture impossible.
    """

    __tablename__ = "evidence_events"

    # Composite key: the partition key must participate.
    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    kind: Mapped[str] = mapped_column(_evidence_kind, nullable=False)

    agent_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    agent_version_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    engagement_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    customer_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    actor: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    outcome: Mapped[str] = mapped_column(_evidence_outcome, nullable=False)

    subject_ref: Mapped[str | None] = mapped_column(Text)

    region: Mapped[str | None] = mapped_column(Text)
    data_classes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    decision: Mapped[str | None] = mapped_column(Text)
    reason_code: Mapped[str | None] = mapped_column(Text)

    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")

    content_digest: Mapped[str] = mapped_column(Text, nullable=False)
    detected_by: Mapped[str] = mapped_column(Text, nullable=False)

    batch_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    leaf_index: Mapped[int | None] = mapped_column(Integer)


class EvidenceCheckpoint(Base, TenantScoped):
    """A root shown to someone outside the organisation.

    Once a customer or auditor holds one of these, history before it cannot be rewritten
    even with full database access. That is what makes the log worth trusting rather
    than merely worth reading.
    """

    __tablename__ = "evidence_checkpoints"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    batch_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("evidence_batches.id"), nullable=False
    )

    tree_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    root: Mapped[str] = mapped_column(Text, nullable=False)

    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_to: Mapped[str] = mapped_column(Text, nullable=False)
    external_ref: Mapped[str | None] = mapped_column(Text)

    signature: Mapped[str | None] = mapped_column(Text)
