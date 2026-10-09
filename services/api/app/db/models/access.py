"""Models for migration 0017 — members, teams, roles, grants and access requests."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, ENUM
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped, Timestamped

_member_status = ENUM(
    "invited",
    "active",
    "suspended",
    "disabled",
    name="member_status",
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

_scope_kind = ENUM(
    "account",
    "project",
    "environment",
    "agent",
    "mcp_server",
    "engagement",
    name="access_scope_kind",
    create_type=False,
)

_request_state = ENUM(
    "pending",
    "approved",
    "denied",
    "withdrawn",
    "expired",
    name="access_request_state",
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


class Member(Base, TenantScoped, Timestamped):
    __tablename__ = "members"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        ForeignKeyConstraint(
            ["org_id", "primary_team_id"],
            ["teams.org_id", "teams.id"],
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(_member_status, nullable=False, default="invited")
    job_title: Mapped[str | None] = mapped_column(Text)
    timezone: Mapped[str] = mapped_column(Text, nullable=False, default="UTC")
    avatar_tone: Mapped[str] = mapped_column(Text, nullable=False, default="default")
    primary_team_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    invited_by: Mapped[str | None] = mapped_column(Text)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class MemberIdentity(Base, TenantScoped, Timestamped):
    """A verified IdP subject bound to a member.

    Unique on ``(issuer, subject)`` globally rather than per organisation — see the
    migration for why answering "who did this" depends on that.
    """

    __tablename__ = "member_identities"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        ForeignKeyConstraint(
            ["org_id", "member_id"],
            ["members.org_id", "members.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    member_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    issuer: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mfa_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    directory_groups: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Team(Base, TenantScoped, Timestamped):
    __tablename__ = "teams"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        ForeignKeyConstraint(
            ["org_id", "parent_team_id"],
            ["teams.org_id", "teams.id"],
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    parent_team_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    source: Mapped[str] = mapped_column(Text, nullable=False, default="manual")
    directory_group_id: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TeamMember(Base, TenantScoped):
    __tablename__ = "team_members"
    __table_args__ = (
        ForeignKeyConstraint(
            ["org_id", "team_id"],
            ["teams.org_id", "teams.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "member_id"],
            ["members.org_id", "members.id"],
            ondelete="CASCADE",
        ),
    )

    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    team_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    member_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    is_lead: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    added_by: Mapped[str | None] = mapped_column(Text)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Role(Base, Timestamped):
    """Built-in roles are reference rows with ``org_id IS NULL``.

    Not ``TenantScoped``: the mixin declares a non-nullable ``org_id``, and the whole
    point of a built-in role is that it has none.
    """

    __tablename__ = "roles"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    org_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), index=True)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    builtin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    permissions: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    assignable_scopes: Mapped[list[str]] = mapped_column(ARRAY(_scope_kind), nullable=False)
    separation_of_duty: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AccessGrant(Base, TenantScoped, Timestamped):
    __tablename__ = "access_grants"
    __table_args__ = (UniqueConstraint("org_id", "id"),)

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    subject_kind: Mapped[str] = mapped_column(_subject_kind, nullable=False)
    subject_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    role_key: Mapped[str] = mapped_column(Text, nullable=False)
    scope_kind: Mapped[str] = mapped_column(_scope_kind, nullable=False)
    scope_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    granted_by: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[str | None] = mapped_column(Text)


class AccessRequest(Base, TenantScoped, Timestamped):
    __tablename__ = "access_requests"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        ForeignKeyConstraint(
            ["org_id", "requester_member_id"],
            ["members.org_id", "members.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    requester_member_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    role_key: Mapped[str] = mapped_column(Text, nullable=False)
    scope_kind: Mapped[str] = mapped_column(_scope_kind, nullable=False)
    scope_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    duration_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    ticket_ref: Mapped[str | None] = mapped_column(Text)
    risk: Mapped[str] = mapped_column(_risk_tier, nullable=False, default="low")
    state: Mapped[str] = mapped_column(_request_state, nullable=False, default="pending")
    decided_by: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    granted_grant_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
