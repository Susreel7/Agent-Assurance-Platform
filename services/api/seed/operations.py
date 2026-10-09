"""Thirty days of runs, cost and tool calls for the demo estate.

Separate from `generate.py` because that file is already a thousand lines and this phase
has a shape of its own: it is the only one that writes tens of thousands of rows, so it
batches, and it is the only one whose output is a time series, so it has to look like
one. A flat line at the same value every day would make every chart in the console
useless for judging whether it works.

The traffic model is deliberately not uniform random. Real estates have a weekly rhythm,
a couple of agents that dominate volume, and incidents that show up as a bad afternoon
rather than as evenly-sprinkled failures. Each of those is reproduced here because each
one is something a person looking at the dashboard is trying to see.

Everything goes through `operations.service.record_runs`, not straight into the tables.
Seeding through the service is what makes this an end-to-end exercise of the ingest path
— the URN resolution, the batch tool-bucket merge and the upsert all run for real, and a
bug in any of them fails the seed instead of waiting for a customer.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.operations import AgentRun, RunStep
from app.domains.operations import service as operations_svc
from app.domains.operations.schemas import (
    RunBatch,
    RunOutcome,
    RunReport,
    StepKind,
    StepReport,
    ToolCallReport,
    ToolSurface,
)
from app.domains.registry.schemas import LifecycleState

if TYPE_CHECKING:
    from uuid import UUID

    from seed.generate import AgentPlan, Log

# Cost per million tokens in USD micros, by model. Rough public list prices as of
# writing, and only their *ratios* matter here: the cost panel is worth looking at when
# the expensive model costs visibly more than the cheap one, not when the absolute
# figure is right.
_PRICE_PER_MTOK: dict[str, tuple[int, int]] = {
    "claude-sonnet-4-5": (3_000_000, 15_000_000),
    "gpt-4.1": (2_000_000, 8_000_000),
    "gpt-4o": (2_500_000, 10_000_000),
    "llama-3.3-70b": (200_000, 200_000),
    "mistral-large-2": (2_000_000, 6_000_000),
}
_DEFAULT_PRICE = (1_000_000, 3_000_000)

# How busy each environment is relative to production. Nobody runs their dev agents
# ten thousand times a day, and a chart that says otherwise is not describing anything.
_ENVIRONMENT_LOAD: dict[LifecycleState, float] = {
    LifecycleState.PRODUCTION: 1.0,
    LifecycleState.STAGING: 0.22,
    LifecycleState.TEST: 0.12,
    LifecycleState.DEV: 0.08,
    LifecycleState.RETIRED: 0.0,
}

# Runs per agent per day at full load, before the weekly and hourly shaping below.
_BASE_RUNS_PER_DAY = 34

# Written in chunks so one batch is never large enough to hold a transaction open for
# a noticeable time. Also under the 500-run cap the ingest schema enforces.
_BATCH = 250

_ERROR_KINDS = (
    "tool_timeout",
    "rate_limited",
    "context_overflow",
    "downstream_5xx",
    "schema_validation",
)

# Tools an agent calls that its descriptor never mentioned. Seeded on purpose: the
# declared-versus-observed reconciliation is the point of the tools screen, and a demo
# where everything reconciles cleanly demonstrates nothing.
_SHADOW_TOOLS = ("web_fetch", "shell_exec", "email_send")


def _price(model: str, tokens_in: int, tokens_out: int) -> int:
    """Cost in integer micros of USD. Never a float, at any point in the arithmetic."""
    per_in, per_out = _PRICE_PER_MTOK.get(model, _DEFAULT_PRICE)
    return (tokens_in * per_in + tokens_out * per_out) // 1_000_000


def _day_shape(day: datetime, rng: random.Random) -> float:
    """A multiplier for one day's volume.

    Weekends are quiet, midweek is busy, and there is noise on top. Without this the
    activity chart is a horizontal line and gives a reader no way to tell a working
    chart from a broken one.
    """
    weekday = day.weekday()
    weekly = 0.28 if weekday >= 5 else (1.0 if weekday < 4 else 0.82)
    return weekly * rng.uniform(0.78, 1.24)


def _start_time(day: datetime, rng: random.Random) -> datetime:
    """A plausible moment within a working day.

    Triangular around mid-morning, so runs cluster during office hours with a tail into
    the evening rather than spreading evenly across the small hours.
    """
    hour = int(rng.triangular(6, 22, 10))
    return day.replace(hour=hour, minute=rng.randrange(60), second=rng.randrange(60))


def _outcome(rng: random.Random, *, unhealthy: bool, incident: bool) -> RunOutcome:
    roll = rng.random()
    failure_rate = 0.16 if incident else (0.07 if unhealthy else 0.018)
    if roll < failure_rate:
        return RunOutcome.TIMED_OUT if rng.random() < 0.3 else RunOutcome.FAILED
    # Refusals are the guardrails doing their job, and they are common enough in a
    # governed estate that a dashboard never showing one would be suspicious.
    if roll < failure_rate + 0.035:
        return RunOutcome.REFUSED
    if roll < failure_rate + 0.042:
        return RunOutcome.CANCELLED
    return RunOutcome.SUCCEEDED


def _tool_calls(plan: AgentPlan, rng: random.Random, *, failed: bool) -> list[ToolCallReport]:
    """What one run called.

    MCP servers are named the way a runtime names them — the last path segment of the
    declared URL — so the reconciliation on the tools screen has to actually do its job
    to mark them declared.
    """
    from seed.generate import mcp_server_name

    calls: list[ToolCallReport] = []

    for server in plan.mcp_servers:
        if rng.random() > 0.62:
            continue
        tool = rng.choice(server["tools"])
        count = rng.randint(1, 4)
        errors = 1 if failed and rng.random() < 0.45 else 0
        duration = rng.randint(40, 2200)
        calls.append(
            ToolCallReport(
                surface=ToolSurface.MCP,
                server_name=mcp_server_name(str(server["url"])),
                tool_name=str(tool),
                calls=count,
                errors=min(errors, count),
                denied=0,
                total_duration_ms=duration * count,
                max_duration_ms=duration,
            )
        )

    for name in plan.native_tools:
        if rng.random() > 0.5:
            continue
        count = rng.randint(1, 3)
        denied = 1 if rng.random() < 0.03 else 0
        duration = rng.randint(15, 900)
        calls.append(
            ToolCallReport(
                surface=ToolSurface.NATIVE,
                tool_name=name,
                calls=count,
                errors=0,
                denied=min(denied, count),
                total_duration_ms=duration * count,
                max_duration_ms=duration,
            )
        )

    return calls


def _steps_for_run(plan: AgentPlan, report: RunReport, rng: random.Random) -> list[StepReport]:
    """A LangGraph-shaped trace: router, workers, tools nested under nodes, guardrail last."""
    from seed.generate import mcp_server_name

    run_rng = random.Random(report.run_id.int if report.run_id else rng.randint(0, 2**31))
    started = report.started_at
    total_ms = (
        int((report.ended_at - report.started_at).total_seconds() * 1000)
        if report.ended_at is not None
        else 8_000
    )
    failed = report.outcome in (RunOutcome.FAILED, RunOutcome.TIMED_OUT)
    refused = report.outcome is RunOutcome.REFUSED
    running = report.outcome is RunOutcome.RUNNING

    shares = [0.1, 0.14, 0.12, 0.18, 0.2, 0.16, 0.1]
    offset_ms = 0
    steps: list[StepReport] = []

    def add_step(
        seq: int,
        *,
        parent_seq: int | None,
        kind: StepKind,
        name: str,
        share: float,
        outcome: RunOutcome,
        surface: ToolSurface | None = None,
        server_name: str = "",
        attempt: int = 1,
        error_kind: str | None = None,
    ) -> None:
        nonlocal offset_ms
        dur = max(int(total_ms * share * run_rng.uniform(0.85, 1.15)), 20)
        step_start = started + timedelta(milliseconds=offset_ms)
        offset_ms += dur
        terminal = outcome is not RunOutcome.RUNNING
        steps.append(
            StepReport(
                seq=seq,
                parent_seq=parent_seq,
                kind=kind,
                name=name,
                surface=surface,
                server_name=server_name,
                started_at=step_start,
                ended_at=None if not terminal else step_start + timedelta(milliseconds=dur),
                outcome=outcome,
                attempt=attempt,
                model=report.model if kind is StepKind.LLM else None,
                tokens_in=int(report.tokens_in * share) if kind is StepKind.LLM else 0,
                tokens_out=int(report.tokens_out * share) if kind is StepKind.LLM else 0,
                cost_micros=int(report.cost_micros * share) if kind is StepKind.LLM else 0,
                error_kind=error_kind,
            )
        )

    add_step(
        0,
        parent_seq=None,
        kind=StepKind.NODE,
        name="supervisor",
        share=shares[0],
        outcome=RunOutcome.SUCCEEDED,
    )
    add_step(
        1,
        parent_seq=0,
        kind=StepKind.NODE,
        name="retrieve_context",
        share=shares[1],
        outcome=RunOutcome.SUCCEEDED,
    )
    add_step(
        2,
        parent_seq=1,
        kind=StepKind.RETRIEVAL,
        name="vector_search",
        share=shares[2],
        surface=ToolSurface.RETRIEVAL,
        outcome=RunOutcome.SUCCEEDED,
    )
    add_step(
        3,
        parent_seq=0,
        kind=StepKind.NODE,
        name="plan",
        share=shares[3],
        outcome=RunOutcome.SUCCEEDED,
    )
    add_step(
        4,
        parent_seq=3,
        kind=StepKind.LLM,
        name=report.model or "gpt-4.1",
        share=shares[4],
        outcome=RunOutcome.SUCCEEDED,
    )

    tool_outcome = (
        RunOutcome.RUNNING if running else (RunOutcome.FAILED if failed else RunOutcome.SUCCEEDED)
    )
    mcp_server = (
        mcp_server_name(str(plan.mcp_servers[0]["url"])) if plan.mcp_servers else "postgres"
    )
    flaky = mcp_server in {"stripe", "jira", "github"} or run_rng.random() < 0.12
    if flaky and failed and run_rng.random() < 0.7:
        add_step(
            5,
            parent_seq=0,
            kind=StepKind.NODE,
            name="call_tools",
            share=shares[5],
            outcome=RunOutcome.FAILED,
            error_kind=report.error_kind,
        )
        add_step(
            6,
            parent_seq=5,
            kind=StepKind.MCP_TOOL,
            name="run_query",
            share=0.08,
            surface=ToolSurface.MCP,
            server_name=mcp_server,
            outcome=RunOutcome.FAILED,
            attempt=1,
            error_kind=report.error_kind or "tool_timeout",
        )
        add_step(
            7,
            parent_seq=5,
            kind=StepKind.MCP_TOOL,
            name="run_query",
            share=0.07,
            surface=ToolSurface.MCP,
            server_name=mcp_server,
            outcome=RunOutcome.FAILED,
            attempt=2,
            error_kind=report.error_kind or "tool_timeout",
        )
    else:
        add_step(
            5,
            parent_seq=0,
            kind=StepKind.NODE,
            name="call_tools",
            share=shares[5],
            outcome=tool_outcome,
            error_kind=report.error_kind if failed else None,
        )
        native = plan.native_tools[0] if plan.native_tools else "web_search"
        add_step(
            6,
            parent_seq=5,
            kind=StepKind.TOOL,
            name=native,
            share=0.07,
            surface=ToolSurface.NATIVE,
            outcome=tool_outcome,
            error_kind=report.error_kind if failed else None,
        )
        if plan.mcp_servers and run_rng.random() < 0.55:
            add_step(
                7,
                parent_seq=5,
                kind=StepKind.MCP_TOOL,
                name=run_rng.choice(plan.mcp_servers[0]["tools"]),
                share=0.06,
                surface=ToolSurface.MCP,
                server_name=mcp_server,
                outcome=tool_outcome,
                error_kind=report.error_kind if failed and flaky else None,
            )

    guard_outcome = RunOutcome.REFUSED if refused else RunOutcome.SUCCEEDED
    add_step(
        8,
        parent_seq=0,
        kind=StepKind.GUARDRAIL,
        name="output_policy",
        share=shares[6],
        outcome=guard_outcome if not running else RunOutcome.RUNNING,
    )

    return steps


def _reports_for_agent(
    plan: AgentPlan,
    *,
    version_id: UUID | None,
    days: int,
    rng: random.Random,
) -> list[RunReport]:
    """Every run one agent performed across the window."""
    load = _ENVIRONMENT_LOAD.get(plan.lifecycle, 0.1)
    if load <= 0:
        return []

    # A minority of agents carry most of the traffic, which is what every real estate
    # looks like and what makes a "top agents by cost" panel say anything.
    weight = rng.choices([0.35, 1.0, 2.6], weights=[45, 40, 15])[0]
    unhealthy = rng.random() < 0.18
    shadow_tool = _SHADOW_TOOLS[rng.randrange(len(_SHADOW_TOOLS))] if rng.random() < 0.14 else None

    model = _model_for(plan)
    midnight = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)

    # One bad day per unhealthy agent, so the failure chart has a spike to explain
    # rather than a uniform smear of errors.
    incident_day = rng.randrange(days) if unhealthy else -1

    reports: list[RunReport] = []
    for offset in range(days):
        day = midnight - timedelta(days=days - 1 - offset)
        incident = offset == incident_day
        count = int(_BASE_RUNS_PER_DAY * load * weight * _day_shape(day, rng))

        for _ in range(count):
            started = _start_time(day, rng)
            outcome = _outcome(rng, unhealthy=unhealthy, incident=incident)
            failed = outcome in (RunOutcome.FAILED, RunOutcome.TIMED_OUT)

            tokens_in = rng.randint(700, 9_000)
            tokens_out = rng.randint(120, 2_400)
            duration_ms = rng.randint(900, 42_000) + rng.randint(120, 2_400)

            tools = _tool_calls(plan, rng, failed=failed)
            if shadow_tool and rng.random() < 0.3:
                tools.append(
                    ToolCallReport(
                        surface=ToolSurface.NATIVE,
                        tool_name=shadow_tool,
                        calls=1,
                        total_duration_ms=rng.randint(50, 700),
                        max_duration_ms=700,
                    )
                )

            run_id = uuid4()
            draft = RunReport(
                run_id=run_id,
                agent_id=plan.agent_id,
                agent_version_id=version_id,
                environment=plan.lifecycle,
                started_at=started,
                ended_at=started + timedelta(milliseconds=duration_ms),
                outcome=outcome,
                step_count=0,
                tool_call_count=sum(t.calls for t in tools),
                retry_count=rng.randint(1, 3) if failed else 0,
                model=model,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_micros=_price(model, tokens_in, tokens_out),
                escalated=outcome is RunOutcome.REFUSED and rng.random() < 0.45,
                guardrail_blocks=1 if outcome is RunOutcome.REFUSED else 0,
                error_kind=rng.choice(_ERROR_KINDS) if failed else None,
                trace_id=uuid4().hex,
                reported_by="seed",
                tools=tools,
            )
            trace = _steps_for_run(plan, draft, rng)
            reports.append(draft.model_copy(update={"steps": trace, "step_count": len(trace)}))

    return reports


def _model_for(plan: AgentPlan) -> str:
    """The model the agent's latest descriptor names, or a default.

    Read off the descriptor rather than picked again, so the cost breakdown by model
    agrees with what the registry says each agent runs.
    """
    if not plan.descriptors:
        return "gpt-4.1"
    _, descriptor, _ = plan.descriptors[-1]
    models = descriptor.get("models") or []
    first: dict[str, Any] = models[0] if models else {}
    return str(first.get("id") or "gpt-4.1")


def _in_flight(plan: AgentPlan, version_id: UUID | None, rng: random.Random) -> RunReport:
    """One run still going, so the console's "running now" figure is not always zero."""
    return RunReport(
        run_id=uuid4(),
        agent_id=plan.agent_id,
        agent_version_id=version_id,
        environment=plan.lifecycle,
        started_at=datetime.now(tz=UTC) - timedelta(seconds=rng.randint(5, 240)),
        outcome=RunOutcome.RUNNING,
        step_count=rng.randint(1, 6),
        model=_model_for(plan),
        reported_by="seed",
    )


async def run_steps_missing(session: AsyncSession, org_id: UUID) -> bool:
    total = await session.scalar(
        select(func.count()).select_from(RunStep).where(RunStep.org_id == org_id)
    )
    return int(total or 0) == 0


async def backfill_run_steps(
    session: AsyncSession,
    org_id: UUID,
    plans: list[AgentPlan],
    rng: random.Random,
    log: Log,
) -> None:
    """Add step traces to runs that were seeded before ``0009`` landed."""
    log.phase("Backfilling run step traces")
    plan_by_agent = {p.agent_id: p for p in plans if p.agent_id is not None}
    offset = 0
    written = 0

    while True:
        rows = (
            (
                await session.execute(
                    select(AgentRun)
                    .where(AgentRun.org_id == org_id)
                    .order_by(AgentRun.started_at)
                    .limit(_BATCH)
                    .offset(offset)
                )
            )
            .scalars()
            .all()
        )
        if not rows:
            break
        offset += len(rows)

        batch_reports: list[RunReport] = []
        for run in rows:
            plan = plan_by_agent.get(run.agent_id)
            if plan is None:
                continue
            draft = RunReport(
                run_id=run.id,
                agent_id=run.agent_id,
                agent_version_id=run.agent_version_id,
                environment=LifecycleState(run.environment),
                started_at=run.started_at,
                ended_at=run.ended_at,
                outcome=RunOutcome(run.outcome),
                step_count=0,
                tool_call_count=run.tool_call_count,
                retry_count=run.retry_count,
                model=run.model,
                tokens_in=int(run.tokens_in),
                tokens_out=int(run.tokens_out),
                cost_micros=int(run.cost_micros),
                escalated=run.escalated,
                guardrail_blocks=run.guardrail_blocks,
                error_kind=run.error_kind,
                trace_id=run.trace_id,
                reported_by="seed-backfill",
            )
            trace = _steps_for_run(plan, draft, rng)
            batch_reports.append(
                draft.model_copy(update={"steps": trace, "step_count": len(trace)})
            )

        if batch_reports:
            result = await operations_svc.record_runs(session, org_id, RunBatch(runs=batch_reports))
            written += result.steps

    log.line(f"backfilled steps for existing runs ({written} step rows written)")


async def seed_operations(
    session: AsyncSession,
    org_id: UUID,
    plans: list[AgentPlan],
    days: int,
    rng: random.Random,
    log: Log,
) -> None:
    log.phase("Runs, cost and tool usage")

    total_runs = 0
    for plan in plans:
        if plan.agent_id is None:
            continue

        version_id = plan.version_ids[-1] if plan.version_ids else None
        reports = _reports_for_agent(plan, version_id=version_id, days=days, rng=rng)

        if plan.lifecycle is LifecycleState.PRODUCTION and rng.random() < 0.25:
            reports.append(_in_flight(plan, version_id, rng))

        for start in range(0, len(reports), _BATCH):
            chunk = reports[start : start + _BATCH]
            if not chunk:
                continue
            await operations_svc.record_runs(session, org_id, RunBatch(runs=chunk))

        total_runs += len(reports)
        log.tally("runs", len(reports))

    log.line(f"{total_runs} runs across {len(plans)} agents over {days} days")
