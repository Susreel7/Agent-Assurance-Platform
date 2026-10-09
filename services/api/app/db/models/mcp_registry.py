"""Models for migration 0017 — MCP servers, capability snapshots, grants and usage.

A capability row records shape only: name, schema digest, declared annotation and
verified risk. Tool arguments never appear here (AGENTS.md rule 5).
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, ENUM
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped, Timestamped

_transport = ENUM(
    "stdio",
    "http",
    "sse",
    "streamable_http",
    name="mcp_transport",
    create_type=False,
)

_trust_tier = ENUM(
    "internal",
    "accredited",
    "partner",
    "community",
    "unverified",
    name="mcp_trust_tier",
    create_type=False,
)

_server_state = ENUM(
    "draft",
    "in_review",
    "approved",
    "quarantined",
    "retired",
    name="mcp_server_state",
    create_type=False,
)

_capability_kind = ENUM(
    "tool",
    "resource",
    "prompt",
    name="mcp_capability_kind",
    create_type=False,
)

_risk_tier = ENUM(
    "low",
    "medium",
    "high",
    "critical",
    name="risk_tier",
    create_type=False,
)

_health_state = ENUM(
    "unknown",
    "healthy",
    "degraded",
    "unreachable",
    "drift",
    name="health_state",
    create_type=False,
)

_lifecycle_state = ENUM(
    "dev",
    "test",
    "staging",
    "production",
    "retired",
    name="lifecycle_state",
    create_type=False,
)

_subject_kind = ENUM(
    "member",
    "team",
    "agent",
    "agent_version",
    "workload",
    "project",
    name="access_subject_kind",
    create_type=False,
)


class McpServer(Base, TenantScoped, Timestamped):
    __tablename__ = "mcp_servers"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        ForeignKeyConstraint(
            ["org_id", "owner_team_id"],
            ["teams.org_id", "teams.id"],
        ),
        ForeignKeyConstraint(
            ["org_id", "connection_id"],
            ["provider_connections.org_id", "provider_connections.id"],
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    transport: Mapped[str] = mapped_column(_transport, nullable=False)
    endpoint_url: Mapped[str | None] = mapped_column(Text)
    command: Mapped[str | None] = mapped_column(Text)
    owner_team_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    connection_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    trust_tier: Mapped[str] = mapped_column(_trust_tier, nullable=False, default="unverified")
    state: Mapped[str] = mapped_column(_server_state, nullable=False, default="draft")
    risk_tier: Mapped[str] = mapped_column(_risk_tier, nullable=False, default="medium")
    health: Mapped[str] = mapped_column(_health_state, nullable=False, default="unknown")
    environments: Mapped[list[str]] = mapped_column(ARRAY(_lifecycle_state), nullable=False)
    approved_snapshot_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    observed_snapshot_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    requires_approval_for_writes: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    quarantined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quarantine_reason: Mapped[str | None] = mapped_column(Text)
    last_discovered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class McpSnapshot(Base, TenantScoped):
    """An immutable capability set. Append-only by database trigger."""

    __tablename__ = "mcp_snapshots"
    __table_args__ = (
        UniqueConstraint("org_id", "server_id", "id"),
        ForeignKeyConstraint(
            ["org_id", "server_id"],
            ["mcp_servers.org_id", "mcp_servers.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    server_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    capability_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    protocol_version: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(Text, nullable=False, default="discovery")
    tool_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    resource_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    prompt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    discovered_by: Mapped[str] = mapped_column(Text, nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(Text)
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class McpCapability(Base, TenantScoped, Timestamped):
    """One tool, resource or prompt within a snapshot. Append-only by trigger."""

    __tablename__ = "mcp_capabilities"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        ForeignKeyConstraint(
            ["org_id", "server_id", "snapshot_id"],
            ["mcp_snapshots.org_id", "mcp_snapshots.server_id", "mcp_snapshots.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    snapshot_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    server_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    kind: Mapped[str] = mapped_column(_capability_kind, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    input_schema_digest: Mapped[bytes | None] = mapped_column(LargeBinary)
    declared_read_only: Mapped[bool | None] = mapped_column(Boolean)
    declared_destructive: Mapped[bool | None] = mapped_column(Boolean)
    declared_idempotent: Mapped[bool | None] = mapped_column(Boolean)
    declared_open_world: Mapped[bool | None] = mapped_column(Boolean)
    verified_risk: Mapped[str] = mapped_column(_risk_tier, nullable=False, default="medium")
    verified_write: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    verified_irreversible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class McpGrant(Base, TenantScoped, Timestamped):
    """Effective tool access. ``capability_name IS NULL`` grants the whole server."""

    __tablename__ = "mcp_grants"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        ForeignKeyConstraint(
            ["org_id", "server_id"],
            ["mcp_servers.org_id", "mcp_servers.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "server_id", "pinned_snapshot_id"],
            ["mcp_snapshots.org_id", "mcp_snapshots.server_id", "mcp_snapshots.id"],
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    server_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    capability_name: Mapped[str | None] = mapped_column(Text)
    subject_kind: Mapped[str] = mapped_column(_subject_kind, nullable=False)
    subject_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    environments: Mapped[list[str]] = mapped_column(ARRAY(_lifecycle_state), nullable=False)
    permission: Mapped[str] = mapped_column(Text, nullable=False, default="invoke")
    requires_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    pinned_snapshot_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    granted_by: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class McpCapabilityUsageDaily(Base, TenantScoped):
    """Daily rollup. Per-call volume lives in ClickHouse behind Observe."""

    __tablename__ = "mcp_capability_usage_daily"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "server_id"],
            ["mcp_servers.org_id", "mcp_servers.id"],
            ondelete="CASCADE",
        ),
    )

    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    usage_date: Mapped[date] = mapped_column(Date, primary_key=True)
    server_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    capability_name: Mapped[str] = mapped_column(Text, primary_key=True)
    # All-zero means "not attributed to one". Migration 0017 explains why these are not
    # nullable: a primary key cannot contain an expression.
    agent_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    member_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    call_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    denied_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    approval_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    error_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    p95_latency_ms: Mapped[int | None] = mapped_column(Integer)
    cost_micros: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
