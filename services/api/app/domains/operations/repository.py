"""Operations persistence. SQL only.

Every statement here is built with SQLAlchemy constructs rather than ``text()``. That is
not stylistic: D-020 records that ``text()`` silently leaves a bind parameter unbound
when a colon follows it, which broke Merkle sealing and graph reconciliation in the two
places this codebase built VALUES lists by hand. Ingest here is the third such place, so
it uses ``postgresql.insert`` and never assembles SQL from strings.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Date, Integer, and_, case, cast, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.operations import AgentRun, RunStep, ToolUsageDaily
from app.db.models.registry import Agent, AgentVersion, BomComponent


def _day_bucket() -> Any:
    """`started_at` truncated to a whole day, typed as a date.

    Cast to `Date` so what arrives in Python is a `date` and lines up directly with the
    axis the service builds. Left as a timestamp it would come back as midnight in some
    timezone and need converting at every comparison, which is where an off-by-one day
    in a chart comes from.
    """
    return cast(func.date_trunc("day", AgentRun.started_at), Date).label("day")


# Which BOM component kinds correspond to something callable at runtime. A model or a
# library is in the bill of materials too, but it is not a tool an agent invokes.
_CALLABLE_KINDS = ("tool", "mcp_server", "sub_agent", "vector_store", "data_source")

_TERMINAL_FAILURES = ("failed", "timed_out")


async def upsert_runs(session: AsyncSession, org_id: UUID, rows: list[dict[str, Any]]) -> int:
    """Insert new runs and close the ones already open. Returns the number accepted.

    Idempotent by design, because delivery is at-least-once: a collector that buffers to
    disk will replay after a restart. The conflict target is the primary key, which
    includes ``started_at`` because the table is partitioned on it.

    ``WHERE agent_runs.outcome = 'running'`` on the update is what makes a replayed
    *terminal* report a no-op instead of an error. Without it the immutability trigger
    refuses the write and one duplicate delivery fails the whole batch — so the row
    count returned is deliberately "how many we acted on", and the caller treats the
    difference as ignored rather than as a failure.
    """
    if not rows:
        return 0

    base = pg_insert(AgentRun).values([{"org_id": org_id, **row} for row in rows])
    stmt = base.on_conflict_do_update(
        index_elements=[AgentRun.id, AgentRun.started_at],
        set_={
            "ended_at": base.excluded.ended_at,
            "duration_ms": base.excluded.duration_ms,
            "outcome": base.excluded.outcome,
            "step_count": base.excluded.step_count,
            "tool_call_count": base.excluded.tool_call_count,
            "retry_count": base.excluded.retry_count,
            "model": base.excluded.model,
            "tokens_in": base.excluded.tokens_in,
            "tokens_out": base.excluded.tokens_out,
            "cost_micros": base.excluded.cost_micros,
            "escalated": base.excluded.escalated,
            "guardrail_blocks": base.excluded.guardrail_blocks,
            "error_kind": base.excluded.error_kind,
            "trace_id": base.excluded.trace_id,
            "agent_version_id": base.excluded.agent_version_id,
        },
        where=AgentRun.outcome == "running",
    ).returning(AgentRun.id)

    # D-017: row counts come from RETURNING, never from `rowcount`.
    return len((await session.execute(stmt)).all())


async def upsert_tool_usage(
    session: AsyncSession, org_id: UUID, buckets: list[dict[str, Any]]
) -> int:
    """Add to today's counters for each tool. Returns the number of buckets touched.

    Accumulating rather than replacing: the increments come from a single run, and many
    runs land in the same daily bucket. ``max_duration_ms`` takes the larger of the two
    because a maximum cannot be summed.
    """
    if not buckets:
        return 0

    base = pg_insert(ToolUsageDaily).values([{"org_id": org_id, **b} for b in buckets])
    stmt = base.on_conflict_do_update(
        constraint="tool_usage_daily_bucket_unique",
        set_={
            "calls": ToolUsageDaily.calls + base.excluded.calls,
            "errors": ToolUsageDaily.errors + base.excluded.errors,
            "denied": ToolUsageDaily.denied + base.excluded.denied,
            "total_duration_ms": (
                ToolUsageDaily.total_duration_ms + base.excluded.total_duration_ms
            ),
            "max_duration_ms": func.greatest(
                ToolUsageDaily.max_duration_ms, base.excluded.max_duration_ms
            ),
            "last_seen_at": func.now(),
        },
    ).returning(ToolUsageDaily.id)

    return len((await session.execute(stmt)).all())


async def resolve_agent_ids(session: AsyncSession, org_id: UUID, urns: set[str]) -> dict[str, UUID]:
    """Map agent URNs to ids in one query.

    An SDK knows its agent by URN — that comes from configuration sitting next to the
    agent's own code — while the id is a database key it has no reason to hold. Resolved
    here in a single statement rather than one lookup per run, because a batch of 500
    runs from one collector is usually a handful of distinct agents.

    Reads the shared `Agent` model rather than calling registry's repository, which
    AGENTS.md rule 2 forbids. Models are shared across domains by D-011 precisely so a
    neighbouring domain can ask a question the owning service does not expose.
    """
    if not urns:
        return {}
    stmt = select(Agent.urn, Agent.id).where(Agent.org_id == org_id, Agent.urn.in_(urns))
    return {str(urn): agent_id for urn, agent_id in (await session.execute(stmt)).all()}


async def live_version_ids(
    session: AsyncSession, org_id: UUID, agent_ids: set[UUID]
) -> dict[UUID, UUID]:
    """Each agent's current version, for runs whose reporter did not name one.

    Attributing a run to the agent's current version is a guess, but it is a much better
    one than `unknown`: the alternative leaves the frameworks panel unable to say what
    the estate is built on. Reporters that do send a version always win over this.
    """
    if not agent_ids:
        return {}
    stmt = select(Agent.id, Agent.current_version_id).where(
        Agent.org_id == org_id,
        Agent.id.in_(agent_ids),
        Agent.current_version_id.is_not(None),
    )
    return {
        agent_id: version_id
        for agent_id, version_id in (await session.execute(stmt)).all()
        if version_id is not None
    }


def _run_row_columns() -> list[Any]:
    return [
        AgentRun.id,
        AgentRun.agent_id,
        Agent.display_name.label("agent_display_name"),
        Agent.urn.label("agent_urn"),
        AgentRun.environment,
        AgentRun.started_at,
        AgentRun.ended_at,
        AgentRun.duration_ms,
        AgentRun.outcome,
        AgentRun.step_count,
        AgentRun.tool_call_count,
        AgentRun.retry_count,
        AgentRun.model,
        AgentRun.tokens_in,
        AgentRun.tokens_out,
        AgentRun.cost_micros,
        AgentRun.escalated,
        AgentRun.guardrail_blocks,
        AgentRun.error_kind,
        AgentRun.trace_id,
    ]


async def list_runs(
    session: AsyncSession,
    org_id: UUID,
    *,
    since: datetime | None = None,
    agent_id: UUID | None = None,
    environment: str | None = None,
    outcomes: list[str] | None = None,
    escalated_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[Any], int]:
    predicates = [AgentRun.org_id == org_id, Agent.org_id == org_id]
    if since is not None:
        predicates.append(AgentRun.started_at >= since)
    if agent_id is not None:
        predicates.append(AgentRun.agent_id == agent_id)
    if environment is not None:
        predicates.append(AgentRun.environment == environment)
    if outcomes:
        predicates.append(AgentRun.outcome.in_(outcomes))
    if escalated_only:
        predicates.append(AgentRun.escalated.is_(True))

    rows = (
        await session.execute(
            select(*_run_row_columns())
            .join(Agent, Agent.id == AgentRun.agent_id)
            .where(*predicates)
            .order_by(AgentRun.started_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).all()

    total = (
        await session.execute(
            select(func.count())
            .select_from(AgentRun)
            .join(Agent, Agent.id == AgentRun.agent_id)
            .where(*predicates)
        )
    ).scalar_one()

    return list(rows), int(total)


def _run_scope(org_id: UUID, since: datetime, agent_id: UUID | None) -> list[Any]:
    """The where-clause every aggregate below shares.

    ``agent_id`` is threaded through each of them rather than given its own set of
    queries, because the agent detail screen asks exactly the estate's questions of one
    agent. Two copies of the same aggregate drift, and the one nobody looks at drifts
    first.
    """
    predicates: list[Any] = [AgentRun.org_id == org_id, AgentRun.started_at >= since]
    if agent_id is not None:
        predicates.append(AgentRun.agent_id == agent_id)
    return predicates


async def activity_by_day(
    session: AsyncSession, org_id: UUID, since: datetime, agent_id: UUID | None = None
) -> list[Any]:
    """Runs and failures per day per environment. Days with no runs are simply absent —
    the service fills the gaps, because a chart needs a continuous axis and deciding what
    an empty day means is not the database's job."""
    day = _day_bucket()
    stmt = (
        select(
            day.label("day"),
            AgentRun.environment,
            func.count().label("runs"),
            func.count(case((AgentRun.outcome.in_(_TERMINAL_FAILURES), 1))).label("failures"),
        )
        .where(*_run_scope(org_id, since, agent_id))
        .group_by(day, AgentRun.environment)
        .order_by(day)
    )
    return list((await session.execute(stmt)).all())


async def window_totals(
    session: AsyncSession,
    org_id: UUID,
    since: datetime,
    until: datetime | None = None,
    agent_id: UUID | None = None,
) -> Any:
    predicates = _run_scope(org_id, since, agent_id)
    if until is not None:
        predicates.append(AgentRun.started_at < until)

    stmt = select(
        func.count().label("runs"),
        func.count(func.distinct(AgentRun.agent_id)).label("agents_active"),
        func.coalesce(func.sum(AgentRun.cost_micros), 0).label("cost_micros"),
        func.coalesce(func.sum(AgentRun.tokens_in), 0).label("tokens_in"),
        func.coalesce(func.sum(AgentRun.tokens_out), 0).label("tokens_out"),
        func.count(case((AgentRun.outcome.in_(_TERMINAL_FAILURES), 1))).label("failed"),
        func.count(case((AgentRun.outcome == "refused", 1))).label("refused"),
        func.count(case((AgentRun.outcome == "succeeded", 1))).label("succeeded"),
        func.count(case((AgentRun.escalated.is_(True), 1))).label("escalations"),
        func.coalesce(func.sum(AgentRun.tool_call_count), 0).label("tool_calls"),
        # percentile_cont ignores nulls, which is what we want: an in-flight run has no
        # duration yet and must not be counted as instantaneous.
        func.coalesce(
            cast(
                func.percentile_cont(0.5).within_group(AgentRun.duration_ms.asc()),
                Integer,
            ),
            0,
        ).label("p50_duration_ms"),
        func.coalesce(
            cast(
                func.percentile_cont(0.95).within_group(AgentRun.duration_ms.asc()),
                Integer,
            ),
            0,
        ).label("p95_duration_ms"),
    ).where(*predicates)

    return (await session.execute(stmt)).one()


async def count_running(session: AsyncSession, org_id: UUID, agent_id: UUID | None = None) -> int:
    """Uses the partial index, so it stays proportional to what is in flight."""
    predicates: list[Any] = [AgentRun.org_id == org_id, AgentRun.outcome == "running"]
    if agent_id is not None:
        predicates.append(AgentRun.agent_id == agent_id)
    stmt = select(func.count()).where(*predicates)
    return int((await session.execute(stmt)).scalar_one())


async def outcome_counts(
    session: AsyncSession, org_id: UUID, since: datetime, agent_id: UUID | None = None
) -> list[Any]:
    stmt = (
        select(AgentRun.outcome, func.count().label("runs"))
        .where(*_run_scope(org_id, since, agent_id))
        .group_by(AgentRun.outcome)
        .order_by(func.count().desc())
    )
    return list((await session.execute(stmt)).all())


async def cost_by_day(
    session: AsyncSession, org_id: UUID, since: datetime, agent_id: UUID | None = None
) -> list[Any]:
    day = _day_bucket()
    stmt = (
        select(
            day.label("day"),
            func.coalesce(func.sum(AgentRun.cost_micros), 0).label("cost_micros"),
            func.coalesce(func.sum(AgentRun.tokens_in), 0).label("tokens_in"),
            func.coalesce(func.sum(AgentRun.tokens_out), 0).label("tokens_out"),
            func.count().label("runs"),
        )
        .where(*_run_scope(org_id, since, agent_id))
        .group_by(day)
        .order_by(day)
    )
    return list((await session.execute(stmt)).all())


async def cost_by_model(
    session: AsyncSession,
    org_id: UUID,
    since: datetime,
    limit: int = 8,
    agent_id: UUID | None = None,
) -> list[Any]:
    label = func.coalesce(AgentRun.model, "unattributed")
    stmt = (
        select(
            label.label("label"),
            func.coalesce(func.sum(AgentRun.cost_micros), 0).label("cost_micros"),
            func.coalesce(func.sum(AgentRun.tokens_in + AgentRun.tokens_out), 0).label("tokens"),
            func.count().label("runs"),
        )
        .where(*_run_scope(org_id, since, agent_id))
        .group_by(label)
        .order_by(func.sum(AgentRun.cost_micros).desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).all())


async def cost_by_agent(
    session: AsyncSession, org_id: UUID, since: datetime, limit: int = 8
) -> list[Any]:
    stmt = (
        select(
            Agent.display_name.label("label"),
            func.coalesce(func.sum(AgentRun.cost_micros), 0).label("cost_micros"),
            func.coalesce(func.sum(AgentRun.tokens_in + AgentRun.tokens_out), 0).label("tokens"),
            func.count().label("runs"),
        )
        .join(Agent, Agent.id == AgentRun.agent_id)
        .where(AgentRun.org_id == org_id, Agent.org_id == org_id, AgentRun.started_at >= since)
        .group_by(Agent.display_name)
        .order_by(func.sum(AgentRun.cost_micros).desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).all())


async def cost_by_environment(
    session: AsyncSession, org_id: UUID, since: datetime, agent_id: UUID | None = None
) -> list[Any]:
    stmt = (
        select(
            AgentRun.environment.label("label"),
            func.coalesce(func.sum(AgentRun.cost_micros), 0).label("cost_micros"),
            func.coalesce(func.sum(AgentRun.tokens_in + AgentRun.tokens_out), 0).label("tokens"),
            func.count().label("runs"),
        )
        .where(*_run_scope(org_id, since, agent_id))
        .group_by(AgentRun.environment)
        .order_by(func.sum(AgentRun.cost_micros).desc())
    )
    return list((await session.execute(stmt)).all())


async def error_kinds(
    session: AsyncSession,
    org_id: UUID,
    since: datetime,
    agent_id: UUID | None = None,
    limit: int = 8,
) -> list[Any]:
    """Why runs failed, most common first.

    `error_kind` is a bounded classification, never a message — nothing a model wrote can
    reach this column (AGENTS.md rule 5). That is what makes it safe to show on a screen
    a customer's staff might see over somebody's shoulder.
    """
    stmt = (
        select(AgentRun.error_kind.label("label"), func.count().label("runs"))
        .where(*_run_scope(org_id, since, agent_id), AgentRun.error_kind.is_not(None))
        .group_by(AgentRun.error_kind)
        .order_by(func.count().desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).all())


async def framework_shares(session: AsyncSession, org_id: UUID, since: datetime) -> list[Any]:
    """Agents and runs per agent framework — LangGraph, CrewAI, the Cursor SDK.

    Counted from the version each run actually executed, not from the agent's current
    version, so a fleet mid-migration shows both frameworks in the proportion they were
    really used. Runs whose reporter did not say which version they ran are grouped as
    unknown rather than dropped, because dropping them would understate the total.
    """
    label = func.coalesce(AgentVersion.runtime_framework, "unknown")
    stmt = (
        select(
            label.label("framework"),
            func.count(func.distinct(AgentRun.agent_id)).label("agents"),
            func.count().label("runs"),
        )
        .outerjoin(AgentVersion, AgentVersion.id == AgentRun.agent_version_id)
        .where(AgentRun.org_id == org_id, AgentRun.started_at >= since)
        .group_by(label)
        .order_by(func.count().desc())
    )
    return list((await session.execute(stmt)).all())


async def declared_framework_shares(session: AsyncSession, org_id: UUID) -> list[Any]:
    """Fallback for an estate with no run history yet: count each agent's current version.

    Without this a fresh install shows an empty frameworks panel, which reads as "we
    could not tell" when the answer is knowable from the registry alone.
    """
    label = func.coalesce(AgentVersion.runtime_framework, "unknown")
    stmt = (
        select(label.label("framework"), func.count().label("agents"))
        .select_from(Agent)
        .join(AgentVersion, AgentVersion.id == Agent.current_version_id)
        .where(Agent.org_id == org_id, AgentVersion.org_id == org_id)
        .group_by(label)
        .order_by(func.count().desc())
    )
    return list((await session.execute(stmt)).all())


def _tool_scope(org_id: UUID, since_day: date, agent_id: UUID | None) -> list[Any]:
    predicates: list[Any] = [ToolUsageDaily.org_id == org_id, ToolUsageDaily.day >= since_day]
    if agent_id is not None:
        predicates.append(ToolUsageDaily.agent_id == agent_id)
    return predicates


async def tool_rollup(
    session: AsyncSession,
    org_id: UUID,
    since_day: date,
    limit: int = 200,
    agent_id: UUID | None = None,
) -> list[Any]:
    stmt = (
        select(
            ToolUsageDaily.surface,
            ToolUsageDaily.server_name,
            ToolUsageDaily.tool_name,
            func.count(func.distinct(ToolUsageDaily.agent_id)).label("agents"),
            func.coalesce(func.sum(ToolUsageDaily.calls), 0).label("calls"),
            func.coalesce(func.sum(ToolUsageDaily.errors), 0).label("errors"),
            func.coalesce(func.sum(ToolUsageDaily.denied), 0).label("denied"),
            func.coalesce(func.sum(ToolUsageDaily.total_duration_ms), 0).label("total_duration_ms"),
            func.coalesce(func.max(ToolUsageDaily.max_duration_ms), 0).label("max_duration_ms"),
            func.max(ToolUsageDaily.last_seen_at).label("last_seen_at"),
            # Which agents called it, so the service can check each one against its own
            # bill of materials rather than against the estate's.
            func.array_agg(func.distinct(ToolUsageDaily.agent_id)).label("agent_ids"),
        )
        .where(*_tool_scope(org_id, since_day, agent_id))
        .group_by(ToolUsageDaily.surface, ToolUsageDaily.server_name, ToolUsageDaily.tool_name)
        .order_by(func.sum(ToolUsageDaily.calls).desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).all())


async def mcp_server_rollup(
    session: AsyncSession, org_id: UUID, since_day: date, agent_id: UUID | None = None
) -> list[Any]:
    """One row per MCP server rather than per tool.

    An MCP server is the unit of supply-chain risk here: it is a process somebody else
    operates, reachable by several agents, and its tool list can change without any
    agent's descriptor changing. Grouping the calls by server is what makes "this server
    started exposing a tool nobody approved" a visible event rather than one row lost in
    a list of two hundred.
    """
    stmt = (
        select(
            ToolUsageDaily.server_name,
            func.count(func.distinct(ToolUsageDaily.tool_name)).label("tools"),
            func.count(func.distinct(ToolUsageDaily.agent_id)).label("agents"),
            func.coalesce(func.sum(ToolUsageDaily.calls), 0).label("calls"),
            func.coalesce(func.sum(ToolUsageDaily.errors), 0).label("errors"),
            func.coalesce(func.sum(ToolUsageDaily.denied), 0).label("denied"),
            func.coalesce(func.sum(ToolUsageDaily.total_duration_ms), 0).label("total_duration_ms"),
            func.max(ToolUsageDaily.last_seen_at).label("last_seen_at"),
            func.array_agg(func.distinct(ToolUsageDaily.agent_id)).label("agent_ids"),
        )
        .where(
            *_tool_scope(org_id, since_day, agent_id),
            ToolUsageDaily.surface == "mcp",
            ToolUsageDaily.server_name != "",
        )
        .group_by(ToolUsageDaily.server_name)
        .order_by(func.sum(ToolUsageDaily.calls).desc())
    )
    return list((await session.execute(stmt)).all())


async def declared_components_by_agent(session: AsyncSession, org_id: UUID) -> list[Any]:
    """Every callable thing each agent's versions declare, as (agent_id, name) pairs.

    Per agent, not per estate. "Some agent somewhere declares this tool" is a much
    weaker question than "the agent calling it declares it", and only the second one
    catches an agent reaching for a capability it was never approved for.

    Read from the shared models rather than through the bom service, which answers per
    component. Models are shared across domains by D-011; repositories are not.
    """
    stmt = (
        select(func.distinct(AgentVersion.agent_id).label("agent_id"), BomComponent.name)
        .join(AgentVersion, AgentVersion.id == BomComponent.agent_version_id)
        .where(
            BomComponent.org_id == org_id,
            AgentVersion.org_id == org_id,
            BomComponent.kind.in_(_CALLABLE_KINDS),
            BomComponent.name.is_not(None),
        )
    )
    return list((await session.execute(stmt)).all())


async def per_agent_activity(
    session: AsyncSession, org_id: UUID, since: datetime, limit: int = 200
) -> list[Any]:
    """One row per agent that ran in the window, for the estate table."""
    stmt = (
        select(
            AgentRun.agent_id,
            func.count().label("runs"),
            func.count(case((AgentRun.outcome.in_(_TERMINAL_FAILURES), 1))).label("failures"),
            func.coalesce(func.sum(AgentRun.cost_micros), 0).label("cost_micros"),
            func.coalesce(func.sum(AgentRun.tokens_in + AgentRun.tokens_out), 0).label("tokens"),
            func.coalesce(
                cast(func.percentile_cont(0.95).within_group(AgentRun.duration_ms.asc()), Integer),
                0,
            ).label("p95_duration_ms"),
            func.max(AgentRun.started_at).label("last_run_at"),
            func.count(case((and_(AgentRun.outcome == "running"), 1))).label("running_now"),
            func.count(case((AgentRun.escalated.is_(True), 1))).label("escalations"),
        )
        .where(AgentRun.org_id == org_id, AgentRun.started_at >= since)
        .group_by(AgentRun.agent_id)
        .order_by(func.count().desc())
        .limit(limit)
    )
    return list((await session.execute(stmt)).all())


async def upsert_steps(session: AsyncSession, org_id: UUID, rows: list[dict[str, Any]]) -> int:
    """Insert new steps and close the ones already open. Returns rows accepted.

    Same replay contract as ``upsert_runs``: terminal steps are immutable, so the update
    is guarded by ``WHERE outcome = 'running'``.
    """
    if not rows:
        return 0

    base = pg_insert(RunStep).values([{"org_id": org_id, **row} for row in rows])
    stmt = base.on_conflict_do_update(
        constraint="run_steps_seq_unique",
        set_={
            "ended_at": base.excluded.ended_at,
            "duration_ms": base.excluded.duration_ms,
            "outcome": base.excluded.outcome,
            "attempt": base.excluded.attempt,
            "model": base.excluded.model,
            "tokens_in": base.excluded.tokens_in,
            "tokens_out": base.excluded.tokens_out,
            "cost_micros": base.excluded.cost_micros,
            "error_kind": base.excluded.error_kind,
            "parent_seq": base.excluded.parent_seq,
            "kind": base.excluded.kind,
            "name": base.excluded.name,
            "surface": base.excluded.surface,
            "server_name": base.excluded.server_name,
        },
        where=RunStep.outcome == "running",
    ).returning(RunStep.id)

    return len((await session.execute(stmt)).all())


async def fetch_run_row(session: AsyncSession, org_id: UUID, run_id: UUID) -> Any | None:
    stmt = (
        select(*_run_row_columns())
        .join(Agent, Agent.id == AgentRun.agent_id)
        .where(AgentRun.org_id == org_id, Agent.org_id == org_id, AgentRun.id == run_id)
        .limit(1)
    )
    return (await session.execute(stmt)).first()


async def fetch_steps_for_run(
    session: AsyncSession,
    org_id: UUID,
    run_id: UUID,
    *,
    limit: int,
) -> list[RunStep]:
    stmt = (
        select(RunStep)
        .where(RunStep.org_id == org_id, RunStep.run_id == run_id)
        .order_by(RunStep.seq)
        .limit(limit + 1)
    )
    return list((await session.execute(stmt)).scalars().all())


async def count_steps_for_run(session: AsyncSession, org_id: UUID, run_id: UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(RunStep)
        .where(RunStep.org_id == org_id, RunStep.run_id == run_id)
    )
    return int((await session.execute(stmt)).scalar_one())


async def fetch_trace_steps_for_agent(
    session: AsyncSession, org_id: UUID, agent_id: UUID, since: datetime
) -> list[Any]:
    """Every step in the window for observed-graph derivation."""
    stmt = (
        select(
            RunStep.run_id,
            RunStep.seq,
            RunStep.parent_seq,
            RunStep.kind,
            RunStep.name,
            RunStep.outcome,
            RunStep.duration_ms,
            RunStep.cost_micros,
            RunStep.attempt,
            RunStep.surface,
            RunStep.server_name,
        )
        .where(
            RunStep.org_id == org_id,
            RunStep.agent_id == agent_id,
            RunStep.started_at >= since,
        )
        .order_by(RunStep.run_id, RunStep.seq)
    )
    return list((await session.execute(stmt)).all())
