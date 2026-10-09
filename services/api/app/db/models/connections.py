"""Models for migration 0017 — customer-owned provider connections.

No column in this module holds a secret value. ``credential_ref`` points into the
customer's secret provider and ``fingerprint`` is a SHA-256 digest kept only so a
rotation can be proven to have changed the material.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
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

_provider_kind = ENUM(
    "openai",
    "anthropic",
    "azure_openai",
    "bedrock",
    "vertex",
    "mistral",
    "cohere",
    "vllm",
    "ollama",
    "mcp_http",
    "custom",
    name="connection_provider_kind",
    create_type=False,
)

_auth_kind = ENUM(
    "api_key",
    "oauth_client",
    "iam_role",
    "mtls",
    "workload_identity",
    "none",
    name="connection_auth_kind",
    create_type=False,
)

_status = ENUM(
    "pending",
    "healthy",
    "degraded",
    "rotating",
    "disabled",
    name="connection_status",
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


class ProviderConnection(Base, TenantScoped, Timestamped):
    __tablename__ = "provider_connections"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        ForeignKeyConstraint(
            ["org_id", "owner_team_id"],
            ["teams.org_id", "teams.id"],
        ),
        ForeignKeyConstraint(
            ["org_id", "personal_member_id"],
            ["members.org_id", "members.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    provider_kind: Mapped[str] = mapped_column(_provider_kind, nullable=False)
    auth_kind: Mapped[str] = mapped_column(_auth_kind, nullable=False)
    status: Mapped[str] = mapped_column(_status, nullable=False, default="pending")
    owner_team_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    personal_member_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    endpoint_url: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    residency_zone: Mapped[str | None] = mapped_column(Text)
    environments: Mapped[list[str]] = mapped_column(ARRAY(_lifecycle_state), nullable=False)
    active_secret_version_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    rotation_due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_health_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    health_detail: Mapped[str | None] = mapped_column(Text)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ConnectionSecretVersion(Base, TenantScoped, Timestamped):
    __tablename__ = "connection_secret_versions"
    __table_args__ = (
        UniqueConstraint("org_id", "connection_id", "id"),
        ForeignKeyConstraint(
            ["org_id", "connection_id"],
            ["provider_connections.org_id", "provider_connections.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    connection_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    credential_ref: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(Text, nullable=False)


class ConnectionGrant(Base, TenantScoped, Timestamped):
    __tablename__ = "connection_grants"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        ForeignKeyConstraint(
            ["org_id", "connection_id"],
            ["provider_connections.org_id", "provider_connections.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    connection_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    subject_kind: Mapped[str] = mapped_column(_subject_kind, nullable=False)
    subject_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    environments: Mapped[list[str]] = mapped_column(ARRAY(_lifecycle_state), nullable=False)
    granted_by: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
