"""Model for migration 0017 — the append-only security audit log.

Partitioned by month, append-only by trigger. ``detail`` carries classifications,
digests and decisions; it is size-capped in the database precisely so it cannot become
somewhere prompts or tool arguments are kept (AGENTS.md rule 5).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, LargeBinary, Text, func
from sqlalchemy.dialects.postgresql import ENUM, INET, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped

_actor_kind = ENUM(
    "member",
    "workload",
    "agent",
    "service",
    "system",
    name="audit_actor_kind",
    create_type=False,
)

_outcome = ENUM(
    "allowed",
    "denied",
    "created",
    "updated",
    "revoked",
    "failed",
    "expired",
    name="audit_outcome",
    create_type=False,
)

_severity = ENUM(
    "info",
    "notice",
    "warning",
    "critical",
    name="audit_severity",
    create_type=False,
)


class SecurityAuditEvent(Base, TenantScoped):
    __tablename__ = "security_audit_events"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=func.now()
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    severity: Mapped[str] = mapped_column(_severity, nullable=False, default="info")
    outcome: Mapped[str] = mapped_column(_outcome, nullable=False)
    actor_kind: Mapped[str] = mapped_column(_actor_kind, nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    actor_label: Mapped[str] = mapped_column(Text, nullable=False)
    target_kind: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    target_label: Mapped[str | None] = mapped_column(Text)
    reason_code: Mapped[str | None] = mapped_column(Text)
    policy_digest: Mapped[bytes | None] = mapped_column(LargeBinary)
    request_id: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(Text)
    source_ip: Mapped[str | None] = mapped_column(INET)
    user_agent_digest: Mapped[bytes | None] = mapped_column(LargeBinary)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
