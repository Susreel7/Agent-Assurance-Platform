"""Models for migration 0014 — projects and workload credentials."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
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

_lifecycle_state = ENUM(
    "dev",
    "test",
    "staging",
    "production",
    "retired",
    name="lifecycle_state",
    create_type=False,
)


class Project(Base, TenantScoped, Timestamped):
    __tablename__ = "projects"
    __table_args__ = (UniqueConstraint("org_id", "id"),)

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    trace_capture_mode: Mapped[str] = mapped_column(Text, nullable=False, default="digest")
    payload_retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    payload_encryption_key_ref: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class WorkloadCredential(Base, TenantScoped, Timestamped):
    __tablename__ = "workload_credentials"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        ForeignKeyConstraint(
            ["org_id", "project_id"],
            ["projects.org_id", "projects.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "agent_id"],
            ["agents.org_id", "agents.id"],
        ),
        ForeignKeyConstraint(
            ["org_id", "member_id"],
            ["members.org_id", "members.id"],
        ),
        ForeignKeyConstraint(
            ["org_id", "id", "active_generation_id"],
            [
                "workload_credential_generations.org_id",
                "workload_credential_generations.credential_id",
                "workload_credential_generations.id",
            ],
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    agent_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    member_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    environment: Mapped[str] = mapped_column(_lifecycle_state, nullable=False)
    modules: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    allowed_model_patterns: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    rpm: Mapped[int | None] = mapped_column(Integer)
    tpm: Mapped[int | None] = mapped_column(Integer)
    max_concurrency: Mapped[int | None] = mapped_column(Integer)
    daily_budget_micros: Mapped[int | None] = mapped_column(BigInteger)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    active_generation_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(Text, nullable=False)


class WorkloadCredentialGeneration(Base, TenantScoped):
    __tablename__ = "workload_credential_generations"
    __table_args__ = (
        UniqueConstraint("org_id", "credential_id", "id"),
        ForeignKeyConstraint(
            ["org_id", "credential_id"],
            ["workload_credentials.org_id", "workload_credentials.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    credential_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    generation_number: Mapped[int] = mapped_column(Integer, nullable=False)
    secret_digest: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
