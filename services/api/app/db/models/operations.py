"""Models for migrations 0008 and 0009 — what the fleet did, cost, called, and walked.

Mirrors ``0008_operations.py`` and ``0009_run_steps.py``. The hand-written migrations are
the source of truth for the schema; these declarations exist to give a query result a type.

Thin by rule (AGENTS.md): no relationships, no cascades, no behaviour.

Two shapes that differ from everything else in this package, both deliberate:

``AgentRun`` and ``RunStep`` have composite primary keys. Both tables are partitioned by
``started_at``, and Postgres requires the partition key to be part of the primary key.

``ToolUsageDaily`` is the only mutable table modelled here. It accumulates: ingest adds
to the current day's bucket rather than inserting a row per tool call. Every other table
in this schema is append-only, so the exception is stated rather than left to be noticed.

``RunStep.run_id`` has no foreign key to ``agent_runs``, which reads like an omission and
is not. See the argument in ``0009_run_steps.py``: retention drops run partitions, and a
dependent key turns that from a ``DROP TABLE`` into a cascade nobody asked for.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped

# Created by the migration. Every reference must declare create_type=False, or the
# second table using a type tries to create it again.
_lifecycle_state = ENUM(
    "dev",
    "test",
    "staging",
    "production",
    "retired",
    name="lifecycle_state",
    create_type=False,
)
_run_outcome = ENUM(
    "running",
    "succeeded",
    "failed",
    "refused",
    "timed_out",
    "cancelled",
    name="run_outcome",
    create_type=False,
)
_tool_surface = ENUM(
    "mcp",
    "native",
    "retrieval",
    "sub_agent",
    "handoff",
    name="tool_surface",
    create_type=False,
)
_step_kind = ENUM(
    "node",
    "llm",
    "tool",
    "mcp_tool",
    "retrieval",
    "guardrail",
    "handoff",
    "sub_agent",
    name="step_kind",
    create_type=False,
)


class AgentRun(Base, TenantScoped):
    """One invocation. For a LangGraph agent, one graph run.

    ``cost_micros`` is integer micros of USD. Summing floating-point money over a
    million rows gives an answer that depends on the order of summation, which is the
    one property a cost report must not have.

    There is nowhere in here to put a prompt, a completion or a tool argument, and the
    migration bounds every text column to a length none of them fit into. A run records
    *that* a model was called and what it cost.
    """

    __tablename__ = "agent_runs"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    # Part of the primary key because the table is partitioned on it.
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )

    agent_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )
    agent_version_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("agent_versions.id", ondelete="SET NULL")
    )

    environment: Mapped[str] = mapped_column(_lifecycle_state, nullable=False)

    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    outcome: Mapped[str] = mapped_column(_run_outcome, nullable=False, server_default="running")

    step_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    tool_call_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    model: Mapped[str | None] = mapped_column(Text)
    tokens_in: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    tokens_out: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    cost_micros: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")

    escalated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    guardrail_blocks: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    error_kind: Mapped[str | None] = mapped_column(Text)
    trace_id: Mapped[str | None] = mapped_column(Text)

    reported_by: Mapped[str] = mapped_column(Text, nullable=False, server_default="sdk")
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RunStep(Base, TenantScoped):
    """One step inside a run: a graph node, a model call, a tool or MCP call.

    ``name`` means whatever ``kind`` says it means — the node name for a ``node``, the
    tool name for a ``tool``, the model for an ``llm``. One column rather than three
    nullable ones, because every screen renders it in the same place and a three-way
    coalesce in every query is worse than a name whose meaning depends on a sibling.

    ``seq`` is the reporter's own counter, not a time ordering. Two steps can start in
    the same millisecond and concurrent branches of a graph routinely do, so ordering by
    ``started_at`` would shuffle them differently on every read.

    This is the closest the schema gets to a prompt, and the migration is where that is
    held back: ``name`` and ``error_kind`` are bounded, and there is no arguments column
    and no result column to put model output in.
    """

    __tablename__ = "run_steps"

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    # Part of the primary key because the table is partitioned on it.
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )

    run_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    agent_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )

    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    parent_seq: Mapped[int | None] = mapped_column(Integer)

    kind: Mapped[str] = mapped_column(_step_kind, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)

    surface: Mapped[str | None] = mapped_column(_tool_surface)
    server_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")

    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int | None] = mapped_column(Integer)

    outcome: Mapped[str] = mapped_column(_run_outcome, nullable=False, server_default="running")
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")

    model: Mapped[str | None] = mapped_column(Text)
    tokens_in: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    tokens_out: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    cost_micros: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")

    error_kind: Mapped[str | None] = mapped_column(Text)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ToolUsageDaily(Base, TenantScoped):
    """One day's worth of calls to one tool by one agent.

    A rollup rather than a row per call: a row per call is runs times tools, and no
    screen asks a question a daily bucket cannot answer. Per-call detail, if it is ever
    needed, belongs in evidence — where it would arrive with a digest and a decision
    rather than as a metric.

    ``server_name`` is empty rather than null for a tool defined in the agent's own
    code. The bucket's uniqueness depends on it, and a null in a unique constraint makes
    every row distinct from every other, so the upsert would insert per call instead of
    incrementing.
    """

    __tablename__ = "tool_usage_daily"

    # `server_default` matters here rather than being decoration: without it SQLAlchemy
    # warns on every insert that a primary key has no generator, because it cannot see
    # the column default the migration wrote. The value still came from Postgres, but
    # the warning is indistinguishable from the real bug it exists to catch.
    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )

    agent_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )

    day: Mapped[date] = mapped_column(Date, nullable=False)

    surface: Mapped[str] = mapped_column(_tool_surface, nullable=False)
    server_name: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    tool_name: Mapped[str] = mapped_column(Text, nullable=False)

    calls: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    errors: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    denied: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")

    total_duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    max_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
