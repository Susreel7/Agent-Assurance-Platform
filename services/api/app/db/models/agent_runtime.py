"""Models for migration 0023 — the runtime identity chain below an agent version.

Mirrors ``0023_agent_runtime_identity.py``. The hand-written migration is the source of
truth for the schema; these declarations exist to give a query result a type, and
``tests/integration/test_model_drift.py`` asserts the two agree.

Thin by rule (AGENTS.md): no relationships, no cascades, no behaviour.

``AgentSession`` is the agent's context window and has nothing to do with
``AuthSession``, which is a person's browser session from `0022`. Both are exported from
this package, and the names are the only thing keeping them apart — so neither is
abbreviated anywhere.

Every foreign key here is *composite* on ``(org_id, ...)``. A single-column key would let
an instance in one tenant reference an agent in another and leave row-level security as
the only thing between them.
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

# Created by migration 0001. Every reference must declare create_type=False, or the
# second table using the type tries to create it again.
_lifecycle_state = ENUM(
    "dev",
    "test",
    "staging",
    "production",
    "retired",
    name="lifecycle_state",
    create_type=False,
)


class AgentInstance(Base, TenantScoped, Timestamped):
    """One running copy of one agent, on one host, in one environment.

    ``human_member_id`` is not nullable, and that is the product's central claim rather
    than a convenience: an instance with no accountable person is an instance no
    incident can be attributed to (`design/14` §1). ``root_human_basis`` says *why* that
    person is the root, so a scheduled agent is attributed to whoever approved it without
    the evidence implying they were at a keyboard.

    ``enforcement_grade_available`` is what we could have done about this instance's
    actions at registration time, not what we can do now. ``unknown`` is accepted and
    reads as ``E`` everywhere.

    ``host_fingerprint`` is a 32-byte digest. There is no column for a hostname.
    """

    __tablename__ = "agent_instances"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        ForeignKeyConstraint(
            ["org_id", "agent_id"],
            ["agents.org_id", "agents.id"],
            ondelete="CASCADE",
        ),
        # The version, member and self-parent keys are declared in the migration with
        # PostgreSQL 15's per-column `ON DELETE SET NULL (...)` form and with NO ACTION,
        # neither of which SQLAlchemy can express faithfully. They are omitted here
        # rather than approximated: a model that states the wrong delete action is worse
        # than one that states none, and the migration is the source of truth.
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )

    agent_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    agent_version_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    human_member_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    root_human_basis: Mapped[str] = mapped_column(Text, nullable=False)

    environment: Mapped[str] = mapped_column(_lifecycle_state, nullable=False)
    deployment_location: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    host_fingerprint: Mapped[bytes | None] = mapped_column(LargeBinary)
    harness: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    harness_version: Mapped[str | None] = mapped_column(Text)

    attestation: Mapped[str] = mapped_column(Text, nullable=False, server_default="none")
    enforcement_grade_available: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="unknown"
    )

    lifecycle: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    parent_instance_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    delegation_depth: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AgentSession(Base, TenantScoped, Timestamped):
    """One continuous agent context window. Carries taint.

    ``taint`` only ever escalates — a database trigger refuses a downgrade, because
    "tainted → clean" is the erasure of a security fact rather than a state transition.
    A clean context window is a new row.

    ``context_source_classes`` holds classifications, never context: ``issue_public``
    records that a public issue body was ingested and says nothing about what it said.
    The vocabulary is closed by a CHECK in the migration.
    """

    __tablename__ = "agent_sessions"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        ForeignKeyConstraint(
            ["org_id", "instance_id"],
            ["agent_instances.org_id", "agent_instances.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )

    instance_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    taint: Mapped[str] = mapped_column(Text, nullable=False, server_default="clean")
    taint_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    taint_reason_code: Mapped[str | None] = mapped_column(Text)

    context_source_classes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )


class AgentTask(Base, TenantScoped, Timestamped):
    """One unit of intent inside a session.

    ``origin`` is load-bearing: a task originating from a webhook carrying a public issue
    body is tainted from birth, and the only way to know that is to have recorded where
    the intent came from.

    ``intent_digest`` is a 32-byte digest. There is no column for the intent.
    """

    __tablename__ = "agent_tasks"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        ForeignKeyConstraint(
            ["org_id", "session_id"],
            ["agent_sessions.org_id", "agent_sessions.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )

    session_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    origin: Mapped[str] = mapped_column(Text, nullable=False, server_default="unknown")
    intent_digest: Mapped[bytes | None] = mapped_column(LargeBinary)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Delegation(Base, TenantScoped, Timestamped):
    """A parent instance granting a subset of its authority to a child instance.

    ``expires_at`` is not nullable. `design/14` §7: a grant with no expiry is how a
    governance product becomes a list of permanent exceptions, so the schema does not
    permit one.

    Attenuation — a child's granted set is a subset of its parent's — is enforced by a
    trigger, because it is a statement about two rows that a CHECK cannot see.
    """

    __tablename__ = "delegations"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        ForeignKeyConstraint(
            ["org_id", "parent_instance_id"],
            ["agent_instances.org_id", "agent_instances.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "child_instance_id"],
            ["agent_instances.org_id", "agent_instances.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )

    parent_instance_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    child_instance_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)

    granted_capability_selectors: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    depth: Mapped[int] = mapped_column(Integer, nullable=False)

    reason_code: Mapped[str | None] = mapped_column(Text)
    granted_by_member_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason_code: Mapped[str | None] = mapped_column(Text)
