"""Models for migration 0024 — the content-free agent action ledger.

Mirrors ``0024_agent_actions_ledger.py``. The hand-written migration is the source of
truth for the schema; these declarations exist to give a query result a type, and
``tests/integration/test_model_drift.py`` asserts the two agree.

Thin by rule (AGENTS.md): no relationships, no cascades, no behaviour.

Two shapes differ from the rest of this package, both deliberate.

``AgentAction`` has a composite primary key. The table is partitioned by ``occurred_at``
and Postgres requires the partition key to be part of the primary key.

``AgentAction`` has **no foreign keys** other than the implicit tenant column. That is the
point rather than an omission: the ledger has to outlive the configuration it refers to,
because an action taken by an agent that was later retired, against a server that was
deleted, is exactly the action an investigator wants six months later.

There is no column here for a prompt, a completion, a file body, a full path, a raw
command line or a raw tool argument. ``argument_digest`` is a digest and
``argument_facets`` is an allow-listed, length-bounded object policed by a CHECK. That
absence is the schema-level answer to "prove you don't store our code", so it is stated
here as well as in the migration.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped

# Created by migration 0001; see the note in agent_runtime.py.
_lifecycle_state = ENUM(
    "dev",
    "test",
    "staging",
    "production",
    "retired",
    name="lifecycle_state",
    create_type=False,
)


class AgentAction(Base, TenantScoped):
    """One capability invocation: ``aap.action.v1`` as a row.

    ``enforcement_grade`` is not nullable, and ``unknown`` is a permitted value that
    every reader must treat as ``E``. Use ``effective_enforcement_grade()`` in SQL or
    ``ActionEnvelope.effective_enforcement_grade`` at the boundary; do not compare this
    column to a grade directly.

    ``human_member_id`` is not nullable while ``agent_id`` is. An action we cannot
    attribute to a person is not evidence, so ingestion refuses it. An action we cannot
    attribute to a *registered* agent is a shadow-agent discovery, which is one of the
    things the ledger is for.
    """

    __tablename__ = "agent_actions"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    # Part of the primary key because the table is partitioned on it.
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # ---- identity ----------------------------------------------------------------
    event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    collector_id: Mapped[str] = mapped_column(Text, nullable=False)
    collector_version: Mapped[str] = mapped_column(Text, nullable=False)

    human_member_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    root_human_basis: Mapped[str] = mapped_column(Text, nullable=False)

    agent_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    agent_version_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    composition_digest: Mapped[bytes | None] = mapped_column(LargeBinary)

    instance_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    session_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    task_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    parent_instance_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    delegation_depth: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    environment: Mapped[str] = mapped_column(_lifecycle_state, nullable=False)

    # ---- action ------------------------------------------------------------------
    capability_kind: Mapped[str] = mapped_column(Text, nullable=False)
    capability_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    capability_digest: Mapped[bytes | None] = mapped_column(LargeBinary)
    operation: Mapped[str] = mapped_column(Text, nullable=False)

    resource_kind: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    resource_class: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    resource_digest: Mapped[bytes | None] = mapped_column(LargeBinary)
    destination_class: Mapped[str] = mapped_column(Text, nullable=False, server_default="none")
    data_classes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    is_write: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_irreversible: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    # ---- decision ----------------------------------------------------------------
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    reason_code: Mapped[str | None] = mapped_column(Text)
    enforcement_grade: Mapped[str] = mapped_column(Text, nullable=False)
    policy_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    policy_version: Mapped[int | None] = mapped_column(Integer)
    matched_grant_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    approval_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    latency_added_ms: Mapped[int | None] = mapped_column(Integer)

    # ---- risk --------------------------------------------------------------------
    risk_class: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    risk_signals: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    session_taint: Mapped[str] = mapped_column(Text, nullable=False, server_default="clean")

    # ---- credential --------------------------------------------------------------
    credential_lease_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    # ---- privacy -----------------------------------------------------------------
    argument_digest: Mapped[bytes | None] = mapped_column(LargeBinary)
    argument_facets: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    arguments_truncated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )

    # ---- provenance --------------------------------------------------------------
    source_harness: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    source_event_id: Mapped[str | None] = mapped_column(Text)

    # ---- integrity ---------------------------------------------------------------
    prev_event_hash: Mapped[bytes | None] = mapped_column(LargeBinary)
    event_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    # ---- downstream --------------------------------------------------------------
    downstream_mutation_kind: Mapped[str | None] = mapped_column(Text)
    downstream_mutation_ref: Mapped[str | None] = mapped_column(Text)

    # ---- call outcome ------------------------------------------------------------
    upstream_status: Mapped[int | None] = mapped_column(Integer)
    bytes_in: Mapped[int | None] = mapped_column(BigInteger)
    bytes_out: Mapped[int | None] = mapped_column(BigInteger)


class AgentActionReceipt(Base, TenantScoped):
    """One row per accepted collector event: the ledger's idempotency registry.

    Separate from the ledger and unpartitioned, because a unique constraint on a
    partitioned table must contain the partition key — so
    ``UNIQUE (org_id, event_id, occurred_at)`` would accept a retried event whose
    timestamp had been corrected on the way through, which is exactly the duplicate this
    table exists to refuse.

    ``action_id`` and ``action_occurred_at`` together address the row the receipt claims:
    the partition, and the id inside it.
    """

    __tablename__ = "agent_action_receipts"
    __table_args__ = (UniqueConstraint("org_id", "event_id"),)

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )

    event_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    collector_id: Mapped[str] = mapped_column(Text, nullable=False)

    action_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    action_occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
