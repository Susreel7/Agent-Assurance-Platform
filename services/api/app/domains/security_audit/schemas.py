"""Security audit boundary models.

``detail`` is a small, closed-vocabulary object: classifications, digests, counts and
decisions. It is not a place for prompts, tool arguments or tool results, and the
database caps its size so it cannot quietly become one (AGENTS.md rule 5).
"""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.api.pagination import KeysetPage

MAX_DETAIL_KEYS = 32
MAX_DETAIL_VALUE_CHARS = 512

# The authoritative bound, measured on the compact JSON encoding. Migration 0017 caps the
# stored column at twice this, on ``pg_column_size``, which measures jsonb's binary layout
# rather than its text — the two numbers are close but not the same quantity, so the CHECK
# is left deliberately slack and exists to catch a writer that bypassed this validator.
# Enforced here so an oversized detail is a 422 naming the field, rather than a constraint
# violation that fails a thousand-event batch from somewhere inside Postgres.
MAX_DETAIL_BYTES = 2048


class ActorKind(StrEnum):
    MEMBER = "member"
    WORKLOAD = "workload"
    AGENT = "agent"
    SERVICE = "service"
    SYSTEM = "system"


class Outcome(StrEnum):
    ALLOWED = "allowed"
    DENIED = "denied"
    CREATED = "created"
    UPDATED = "updated"
    REVOKED = "revoked"
    FAILED = "failed"
    EXPIRED = "expired"


class Severity(StrEnum):
    INFO = "info"
    NOTICE = "notice"
    WARNING = "warning"
    CRITICAL = "critical"


class Category(StrEnum):
    """The tab an event appears under in the console.

    A closed set rather than free text. An auditor filtering for "everything that touched
    access control last quarter" needs the category to mean the same thing in January as
    in December, which free-text strings do not survive.
    """

    IDENTITY = "identity"
    ACCESS = "access"
    CREDENTIAL = "credential"
    MCP = "mcp"
    ROUTING = "routing"
    DATA = "data"
    ADMIN = "admin"


class AuditRecord(BaseModel):
    """One event, as a producer submits it.

    There is no ``occurred_at``: the database stamps it. A caller-supplied timestamp on an
    append-only log is a way to write history out of order, and the partition a row lands
    in is decided by that column.
    """

    event_type: str = Field(min_length=1, max_length=128, pattern=r"^[a-z][a-z0-9_.]*$")
    category: Category
    severity: Severity = Severity.INFO
    outcome: Outcome
    actor_kind: ActorKind
    actor_id: UUID | None = None
    actor_label: str = Field(min_length=1, max_length=256)
    target_kind: str | None = Field(default=None, max_length=64)
    target_id: UUID | None = None
    target_label: str | None = Field(default=None, max_length=256)
    reason_code: str | None = Field(default=None, max_length=64)
    policy_digest_hex: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    request_id: str | None = Field(default=None, max_length=128)
    trace_id: str | None = Field(default=None, max_length=64)
    source_ip: str | None = Field(default=None, max_length=45)
    detail: dict[str, Any] = Field(default_factory=dict)

    @field_validator("detail")
    @classmethod
    def _detail_is_small_and_flat(cls, detail: dict[str, Any]) -> dict[str, Any]:
        """Keep ``detail`` a decision record rather than a payload dump.

        Bounded key count, scalar values only, and a length cap per value. Without this
        the field is an unpoliced hole through which a well-meaning caller puts a whole
        prompt into an append-only table that nobody can redact afterwards.
        """
        if len(detail) > MAX_DETAIL_KEYS:
            raise ValueError(f"detail carries more than {MAX_DETAIL_KEYS} keys")
        for key, value in detail.items():
            if not isinstance(key, str) or len(key) > 64:
                raise ValueError("detail keys must be strings of at most 64 characters")
            if isinstance(value, str):
                if len(value) > MAX_DETAIL_VALUE_CHARS:
                    raise ValueError(
                        f"detail['{key}'] is longer than {MAX_DETAIL_VALUE_CHARS} characters"
                    )
            elif not isinstance(value, bool | int | float | type(None)):
                raise ValueError(f"detail['{key}'] must be a scalar, not {type(value).__name__}")

        encoded = len(json.dumps(detail, separators=(",", ":")).encode())
        if encoded > MAX_DETAIL_BYTES:
            raise ValueError(
                f"detail serialises to {encoded} bytes, over the {MAX_DETAIL_BYTES} byte limit"
            )
        return detail


class AuditEventOut(BaseModel):
    id: UUID
    occurred_at: datetime
    event_type: str
    category: str
    severity: Severity
    outcome: Outcome
    actor_kind: ActorKind
    actor_id: UUID | None
    actor_label: str
    target_kind: str | None
    target_id: UUID | None
    target_label: str | None
    reason_code: str | None
    policy_digest_hex: str | None
    request_id: str | None
    trace_id: str | None
    source_ip: str | None
    detail: dict[str, Any]


AuditPage = KeysetPage[AuditEventOut]


class AuditQuery(BaseModel):
    """Filters for a keyset listing.

    Every filter narrows an index the listing already uses. Deliberately no free-text
    search: on a partitioned table with billions of rows an unindexed `ILIKE` is a way to
    take the control plane down from the audit page.
    """

    category: Category | None = None
    severity: Severity | None = None
    outcome: Outcome | None = None
    actor_id: UUID | None = None
    target_id: UUID | None = None
    event_type: str | None = Field(default=None, max_length=128)
    since: datetime | None = None
    until: datetime | None = None


class CategoryCount(BaseModel):
    category: str
    severity: Severity
    event_count: int


class AuditDigest(BaseModel):
    """Counts for the security overview, over a bounded window.

    Bounded because the aggregate is computed live: a window is a partition-pruned scan,
    "all time" is not.
    """

    since: datetime
    until: datetime
    counts: list[CategoryCount]
    denied_count: int
    critical_count: int
