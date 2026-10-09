"""Models for migration 0001 — organisations, agents, versions, ownership, BOM, releases.

Mirrors ``0001_baseline.py``. The hand-written migration is the source of truth for the
schema; these declarations exist to give a query result a type, and
``tests/integration/test_model_drift.py`` asserts the two agree.

Thin by rule (AGENTS.md): no relationships, no cascades, no behaviour. Lazy loading in an
async codebase produces failures that are tedious to trace, and a model that can emit a
query is a model that will emit one from inside a request that has already committed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped

# Enum types are created by the migration. Every reference must declare
# create_type=False, or the second table using a type tries to create it again.
_lifecycle_state = ENUM(
    "dev",
    "test",
    "staging",
    "production",
    "retired",
    name="lifecycle_state",
    create_type=False,
)
_ownership_role = ENUM(
    "accountable",
    "approver_of_record",
    "technical",
    "change_authority",
    "business",
    name="ownership_role",
    create_type=False,
)
_component_kind = ENUM(
    "model",
    "prompt",
    "tool",
    "mcp_server",
    "library",
    "dataset",
    "sub_agent",
    "vector_store",
    "data_source",
    "guardrail",
    "skill",
    "config",
    "rule_source",
    "rule_obligation",
    "model_policy",
    name="component_kind",
    create_type=False,
)
_materiality = ENUM("material", "immaterial", "needs_review", name="materiality", create_type=False)
_release_state = ENUM(
    "draft",
    "proposed",
    "approved",
    "rolled_out",
    "rolled_back",
    "abandoned",
    name="release_state",
    create_type=False,
)
_change_category = ENUM(
    "model",
    "inference_params",
    "prompt",
    "tool",
    "mcp_server",
    "capability",
    "dependency",
    "data_source",
    "data_class",
    "residency",
    "guardrail",
    "oversight",
    "resilience",
    "delegation",
    "deployment",
    "metadata",
    "skill",
    "sub_agent",
    "config",
    "rule_obligation",
    "rule_source",
    "model_policy",
    "memory_retrieval",
    name="change_category",
    create_type=False,
)
_change_operation = ENUM(
    "added",
    "removed",
    "modified",
    "renamed",
    name="change_operation",
    create_type=False,
)
_impact_dimension = ENUM(
    "behaviour",
    "security",
    "cost",
    "latency",
    "compliance",
    name="impact_dimension",
    create_type=False,
)


class Organization(Base):
    """Present even in single-tenant installs, so the code path is identical in all
    three deployment modes."""

    __tablename__ = "organizations"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Agent(Base, TenantScoped):
    """Stable identity across versions. ``urn`` is what the estate knows it by.

    ``current_version_id`` and ``baseline_version_id`` differing is the single most
    consequential fact in the product: something is running that was not signed off.
    """

    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("org_id", "id"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    urn: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    owning_team: Mapped[str | None] = mapped_column(Text)
    lifecycle_state: Mapped[str] = mapped_column(_lifecycle_state, nullable=False)

    current_version_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    baseline_version_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_source: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentVersion(Base, TenantScoped):
    """Append-only. A database trigger enforces it; do not work around it.

    This table is why materiality is computable at all: without an immutable record of
    what was approved, "is this still the thing we signed off on?" is a judgement call
    rather than a query.
    """

    __tablename__ = "agent_versions"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    agent_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )

    semver: Mapped[str] = mapped_column(Text, nullable=False)

    descriptor_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    descriptor_digest: Mapped[str] = mapped_column(Text, nullable=False)

    runtime_framework: Mapped[str | None] = mapped_column(Text)
    runtime_language: Mapped[str | None] = mapped_column(Text)
    environment: Mapped[str] = mapped_column(_lifecycle_state, nullable=False)
    autonomy: Mapped[str | None] = mapped_column(Text)

    vcs_provider: Mapped[str | None] = mapped_column(Text)
    vcs_repo: Mapped[str | None] = mapped_column(Text)
    vcs_ref: Mapped[str | None] = mapped_column(Text)

    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_by: Mapped[str] = mapped_column(Text, nullable=False)


class AgentOwnership(Base, TenantScoped):
    """Validity windows rather than a single current holder, so accountability survives
    a reorganisation and a past approval still names the person who gave it."""

    __tablename__ = "agent_ownership"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    agent_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )

    role: Mapped[str] = mapped_column(_ownership_role, nullable=False)
    principal_id: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)

    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class BomComponent(Base, TenantScoped):
    """What is actually inside one agent version. Append-only.

    ``declared_meta`` is what the component claims about itself — MCP tool annotations,
    for instance, which the specification requires clients to treat as untrusted.
    ``observed_meta`` is what we measured. Disagreement between them is a finding.
    """

    __tablename__ = "bom_components"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    agent_version_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("agent_versions.id", ondelete="CASCADE"),
        nullable=False,
    )

    kind: Mapped[str] = mapped_column(_component_kind, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str | None] = mapped_column(Text)
    provider: Mapped[str | None] = mapped_column(Text)
    licence: Mapped[str | None] = mapped_column(Text)

    effect: Mapped[str | None] = mapped_column(Text)
    reversible: Mapped[bool | None] = mapped_column(Boolean)
    human_approval: Mapped[str | None] = mapped_column(Text)

    digest: Mapped[str | None] = mapped_column(Text)

    declared_meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    observed_meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )


class Release(Base, TenantScoped):
    """A governed transition between two versions.

    The roll-up columns are maintained by the ``release_changes_rollup`` trigger, not by
    the application. Writing them from Python would mean the list view and the detail
    view could disagree about the same release.
    """

    __tablename__ = "releases"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    agent_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )

    from_version_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    to_version_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    release_tag: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(_release_state, nullable=False)

    change_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    material_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    review_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    impacts: Mapped[list[str]] = mapped_column(
        ARRAY(_impact_dimension), nullable=False, server_default="{}"
    )
    categories: Mapped[list[str]] = mapped_column(
        ARRAY(_change_category), nullable=False, server_default="{}"
    )

    accreditation_impact: Mapped[str] = mapped_column(Text, nullable=False, server_default="none")
    affected_accreditations: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    vcs_provider: Mapped[str | None] = mapped_column(Text)
    vcs_repo: Mapped[str | None] = mapped_column(Text)
    vcs_ref: Mapped[str | None] = mapped_column(Text)
    vcs_pr_ref: Mapped[str | None] = mapped_column(Text)

    proposed_by: Mapped[str | None] = mapped_column(Text)
    proposed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_descriptor_digest: Mapped[str | None] = mapped_column(Text)
    rolled_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rolled_back_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ReleaseChange(Base, TenantScoped):
    """One typed, human-legible change. Append-only.

    ``summary`` is the field that makes the product legible to a reviewer who did not
    write the change. It is not decoration and it is not optional.
    """

    __tablename__ = "release_changes"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    release_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("releases.id", ondelete="CASCADE"), nullable=False
    )

    category: Mapped[str] = mapped_column(_change_category, nullable=False)
    operation: Mapped[str] = mapped_column(_change_operation, nullable=False)

    path: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)

    before_value: Mapped[Any | None] = mapped_column(JSONB)
    after_value: Mapped[Any | None] = mapped_column(JSONB)

    summary: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)

    impacts: Mapped[list[str]] = mapped_column(
        ARRAY(_impact_dimension), nullable=False, server_default="{}"
    )
    severity: Mapped[str] = mapped_column(Text, nullable=False, server_default="info")

    verdict: Mapped[str] = mapped_column(_materiality, nullable=False, server_default="immaterial")
    rules_fired: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")

    detected_by: Mapped[str] = mapped_column(Text, nullable=False, server_default="descriptor_diff")

    adjudicated_by: Mapped[str | None] = mapped_column(Text)
    adjudicated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    adjudication_reason: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Job(Base):
    """Postgres SKIP LOCKED instead of a broker.

    ``org_id`` is nullable here — some jobs are installation-wide (partition
    maintenance, licence reload) — so this does not use ``TenantScoped``.
    """

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    org_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    kind: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    dedupe_key: Mapped[str | None] = mapped_column(Text)

    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")

    locked_by: Mapped[str | None] = mapped_column(Text)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
