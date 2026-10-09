"""Operations logic — accepting run reports and turning them into the estate's story.

Ingest is the interesting half. A reporter sends the same run twice, once when work
starts and once when it ends, and may send either of those more than once because
delivery is at-least-once. So this module is written to be replay-safe throughout: run
identity comes from the client, durations are computed here rather than trusted, and
tool counts from one batch are combined before they reach the database so a batch of 500
runs touching the same MCP server is one bucket update instead of 500.

The read half exists to answer one screen. Every series is gap-filled here rather than in
SQL, because a day with no runs is a product decision — it is zero, not missing — and
that decision belongs above the database.
"""

from __future__ import annotations

import base64
from datetime import UTC, date, datetime, timedelta
from itertools import pairwise
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.operations import repository as repo
from app.domains.operations.schemas import (
    ActivitySeries,
    AgentOperations,
    CostDay,
    CostReport,
    CostSlice,
    ErrorKindCount,
    FrameworkShare,
    GraphEdgeStat,
    GraphNodeStat,
    IngestResult,
    McpInventory,
    McpServerRow,
    ObservedGraph,
    OperationsSnapshot,
    RunBatch,
    RunDetail,
    RunOutcome,
    RunOutcomeCount,
    RunPage,
    RunReport,
    RunRow,
    StepKind,
    StepRow,
    ToolInventory,
    ToolRow,
    ToolSurface,
)

# Longest window the console may ask for in one request. A year of daily buckets is 365
# points, which is already more than a chart can show usefully, and the cap keeps a
# hand-written query string from turning into a full-history scan.
MAX_WINDOW_DAYS = 365
DEFAULT_WINDOW_DAYS = 30
MAX_STEPS_RETURN = 1000

_STEP_FAILURES = frozenset({"failed", "timed_out"})
_TOOL_STEP_KINDS = frozenset({StepKind.TOOL.value, StepKind.MCP_TOOL.value})


def workload_reporter_ref(credential_id: UUID) -> str:
    """Reversible credential audit reference within the schema's 32-byte bound."""
    encoded = base64.urlsafe_b64encode(credential_id.bytes).decode("ascii").rstrip("=")
    return f"workload:{encoded}"


class OperationsError(Exception):
    """Base class for this domain. Translated to HTTP in router.py."""


class UnknownAgentError(OperationsError):
    def __init__(self, names: list[str]) -> None:
        self.names = names
        listed = ", ".join(sorted(names)[:5])
        super().__init__(f"no registered agent matches {listed}")


class RunNotFoundError(OperationsError):
    def __init__(self, run_id: UUID) -> None:
        self.run_id = run_id
        super().__init__(f"run {run_id} was not found")


class ReporterScopeError(OperationsError):
    """A machine credential attempted to report outside its agent or environment."""


def _window_start(days: int) -> datetime:
    """Midnight UTC `days - 1` days ago, so a window of 1 means today.

    Truncated to a day boundary because every series is bucketed by day, and a window
    starting mid-afternoon makes the first bucket a partial day that looks like a
    collapse in traffic.
    """
    today = datetime.now(tz=UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=max(days, 1) - 1)


def _clamp_days(days: int) -> int:
    return max(1, min(days, MAX_WINDOW_DAYS))


def _share(part: int, whole: int) -> float:
    return round(part * 100.0 / whole, 1) if whole else 0.0


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


async def record_runs(
    session: AsyncSession,
    org_id: UUID,
    batch: RunBatch,
    *,
    reporter_agent_id: UUID | None = None,
    reporter_environment: str | None = None,
    reporter_ref: str | None = None,
) -> IngestResult:
    """Accept a batch of run reports.

    An unknown agent fails the whole batch rather than being dropped. That is the
    opposite of how evidence ingest behaves, and deliberately: evidence may legitimately
    describe an agent nobody has declared yet, whereas a run is reported *by* the agent
    or by a collector watching it, and both know which registered agent they are. A
    silently discarded run is a gap in a cost report that nobody will ever explain.
    """
    urns = {r.agent_urn for r in batch.runs if r.agent_urn and r.agent_id is None}
    by_urn = await repo.resolve_agent_ids(session, org_id, urns)

    missing = sorted(urns - by_urn.keys())
    if missing:
        raise UnknownAgentError(missing)

    resolved: list[tuple[RunReport, UUID]] = []
    for report in batch.runs:
        agent_id = report.agent_id or by_urn[str(report.agent_urn)]
        if reporter_agent_id is not None and agent_id != reporter_agent_id:
            raise ReporterScopeError("credential is bound to a different agent")
        if reporter_environment is not None and report.environment.value != reporter_environment:
            raise ReporterScopeError(
                f"credential is bound to {reporter_environment!r}, not {report.environment.value!r}"
            )
        resolved.append((report, agent_id))

    # Fill in the version for reporters that did not name one, so the frameworks panel
    # can attribute the run. Only asked for the agents actually in this batch.
    needs_version = {agent_id for report, agent_id in resolved if report.agent_version_id is None}
    live_versions = await repo.live_version_ids(session, org_id, needs_version)

    rows: list[dict[str, Any]] = []
    step_rows: list[dict[str, Any]] = []
    opened = 0
    closed = 0
    for report, agent_id in resolved:
        run_id = report.run_id or uuid4()
        if report.outcome is RunOutcome.RUNNING:
            opened += 1
        else:
            closed += 1
        rows.append(
            _run_values(
                report,
                agent_id,
                live_versions,
                run_id=run_id,
                reporter_ref=reporter_ref,
            )
        )
        if report.steps:
            step_rows.extend(_step_values(report, run_id, agent_id))

    accepted = await repo.upsert_runs(session, org_id, _collapse_run_rows(rows))
    buckets = await repo.upsert_tool_usage(session, org_id, _tool_buckets(resolved))
    steps_written = await repo.upsert_steps(session, org_id, _collapse_step_rows(step_rows))

    return IngestResult(
        opened=opened,
        closed=closed,
        # A report the database declined to apply because the run had already finished.
        # Not an error: it is a duplicate delivery, which is expected.
        ignored=max(len(rows) - accepted, 0),
        tool_buckets=buckets,
        steps=steps_written,
    )


def _step_values(report: RunReport, run_id: UUID, agent_id: UUID) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for step in report.steps:
        duration_ms: int | None = None
        if step.ended_at is not None:
            duration_ms = int((step.ended_at - step.started_at).total_seconds() * 1000)
        rows.append(
            {
                "run_id": run_id,
                "agent_id": agent_id,
                "seq": step.seq,
                "parent_seq": step.parent_seq,
                "kind": step.kind.value,
                "name": step.name,
                "surface": step.surface.value if step.surface is not None else None,
                "server_name": step.server_name,
                "started_at": step.started_at,
                "ended_at": step.ended_at,
                "duration_ms": duration_ms,
                "outcome": step.outcome.value,
                "attempt": step.attempt,
                "model": step.model,
                "tokens_in": step.tokens_in,
                "tokens_out": step.tokens_out,
                "cost_micros": step.cost_micros,
                "error_kind": step.error_kind,
            }
        )
    return rows


def _collapse_run_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[UUID, datetime], dict[str, Any]] = {}
    for row in rows:
        merged[(row["id"], row["started_at"])] = row
    return list(merged.values())


def _collapse_step_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per conflict target. A single upsert cannot touch the same row twice."""
    merged: dict[tuple[UUID, int, datetime], dict[str, Any]] = {}
    for row in rows:
        key = (row["run_id"], row["seq"], row["started_at"])
        merged[key] = row
    return list(merged.values())


def _run_values(
    report: RunReport,
    agent_id: UUID,
    live_versions: dict[UUID, UUID],
    *,
    run_id: UUID,
    reporter_ref: str | None = None,
) -> dict[str, Any]:
    """One row for `agent_runs`.

    `duration_ms` is computed here and never read from the report. A reporter that
    measured it differently — including the time it spent waiting to flush — would make
    the latency figures incomparable between one SDK and the next.
    """
    duration_ms: int | None = None
    if report.ended_at is not None:
        duration_ms = int((report.ended_at - report.started_at).total_seconds() * 1000)

    return {
        "id": run_id,
        "agent_id": agent_id,
        "agent_version_id": report.agent_version_id or live_versions.get(agent_id),
        "environment": report.environment.value,
        "started_at": report.started_at,
        "ended_at": report.ended_at,
        "duration_ms": duration_ms,
        "outcome": report.outcome.value,
        "step_count": report.step_count,
        "tool_call_count": report.tool_call_count,
        "retry_count": report.retry_count,
        "model": report.model,
        "tokens_in": report.tokens_in,
        "tokens_out": report.tokens_out,
        "cost_micros": report.cost_micros,
        "escalated": report.escalated,
        "guardrail_blocks": report.guardrail_blocks,
        "error_kind": report.error_kind,
        "trace_id": report.trace_id,
        "reported_by": reporter_ref or report.reported_by,
    }


def _tool_buckets(resolved: list[tuple[RunReport, UUID]]) -> list[dict[str, Any]]:
    """Combine the batch's tool calls into one row per bucket.

    Without this, a batch reporting 500 runs that each called the same MCP server sends
    500 conflicting inserts for one row, and Postgres refuses: a single statement cannot
    hit the same row twice via ON CONFLICT. Combining first is therefore required, not
    merely an optimisation.

    The bucket day comes from when the run *started*, matching how every other series
    here is bucketed. A run that begins before midnight and ends after it counts on the
    day it began, so a day's tool calls and a day's runs describe the same population.
    """
    merged: dict[tuple[UUID, date, str, str, str], dict[str, Any]] = {}

    for report, agent_id in resolved:
        day = report.started_at.astimezone(UTC).date()
        for call in report.tools:
            key = (agent_id, day, call.surface.value, call.server_name, call.tool_name)
            bucket = merged.get(key)
            if bucket is None:
                merged[key] = {
                    "agent_id": agent_id,
                    "day": day,
                    "surface": call.surface.value,
                    "server_name": call.server_name,
                    "tool_name": call.tool_name,
                    "calls": call.calls,
                    "errors": call.errors,
                    "denied": call.denied,
                    "total_duration_ms": call.total_duration_ms,
                    "max_duration_ms": call.max_duration_ms,
                }
                continue
            bucket["calls"] += call.calls
            bucket["errors"] += call.errors
            bucket["denied"] += call.denied
            bucket["total_duration_ms"] += call.total_duration_ms
            bucket["max_duration_ms"] = max(bucket["max_duration_ms"], call.max_duration_ms)

    return list(merged.values())


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------


async def list_runs(
    session: AsyncSession,
    org_id: UUID,
    *,
    days: int = DEFAULT_WINDOW_DAYS,
    agent_id: UUID | None = None,
    environment: str | None = None,
    outcomes: list[str] | None = None,
    escalated_only: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> RunPage:
    rows, total = await repo.list_runs(
        session,
        org_id,
        since=_window_start(_clamp_days(days)),
        agent_id=agent_id,
        environment=environment,
        outcomes=outcomes,
        escalated_only=escalated_only,
        limit=limit,
        offset=offset,
    )
    return RunPage(
        items=[RunRow.model_validate(row._mapping) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


async def build_activity_series(
    session: AsyncSession,
    org_id: UUID,
    days: int = DEFAULT_WINDOW_DAYS,
    agent_id: UUID | None = None,
) -> ActivitySeries:
    """Runs per day per environment, with every day present.

    The database returns only days that had runs. Filling the gaps here means a quiet
    weekend is a visible trough rather than two points joined by a straight line across
    it, which is the difference between a chart that shows a pattern and one that hides
    it.
    """
    window = _clamp_days(days)
    start = _window_start(window)
    rows = await repo.activity_by_day(session, org_id, start, agent_id=agent_id)

    axis = [(start + timedelta(days=offset)).date() for offset in range(window)]
    index = {day: position for position, day in enumerate(axis)}

    environments = sorted({str(row.environment) for row in rows})
    by_environment = {name: [0] * window for name in environments}
    totals = [0] * window
    failures = [0] * window

    for row in rows:
        position = index.get(row.day)
        if position is None:
            continue
        by_environment[str(row.environment)][position] += int(row.runs)
        totals[position] += int(row.runs)
        failures[position] += int(row.failures)

    return ActivitySeries(
        days=axis, by_environment=by_environment, totals=totals, failures=failures
    )


async def build_cost_report(
    session: AsyncSession, org_id: UUID, days: int = DEFAULT_WINDOW_DAYS
) -> CostReport:
    window = _clamp_days(days)
    start = _window_start(window)
    previous_start = start - timedelta(days=window)

    totals = await repo.window_totals(session, org_id, start)
    previous = await repo.window_totals(session, org_id, previous_start, start)

    by_day_rows = await repo.cost_by_day(session, org_id, start)
    by_day_index = {row.day: row for row in by_day_rows}

    # Same gap-filling as the activity series, and for the same reason: a missing day in
    # a cost chart reads as free rather than as idle.
    by_day = [
        CostDay(
            day=day,
            cost_micros=int(getattr(by_day_index.get(day), "cost_micros", 0) or 0),
            tokens_in=int(getattr(by_day_index.get(day), "tokens_in", 0) or 0),
            tokens_out=int(getattr(by_day_index.get(day), "tokens_out", 0) or 0),
            runs=int(getattr(by_day_index.get(day), "runs", 0) or 0),
        )
        for day in ((start + timedelta(days=offset)).date() for offset in range(window))
    ]

    total_cost = int(totals.cost_micros)

    def slices(rows: list[Any]) -> list[CostSlice]:
        return [
            CostSlice(
                label=str(row.label),
                cost_micros=int(row.cost_micros),
                tokens=int(row.tokens),
                runs=int(row.runs),
                share_pct=_share(int(row.cost_micros), total_cost),
            )
            for row in rows
        ]

    return CostReport(
        window_days=window,
        total_cost_micros=total_cost,
        total_tokens=int(totals.tokens_in) + int(totals.tokens_out),
        total_runs=int(totals.runs),
        previous_cost_micros=int(previous.cost_micros),
        by_day=by_day,
        by_model=slices(await repo.cost_by_model(session, org_id, start)),
        by_agent=slices(await repo.cost_by_agent(session, org_id, start)),
        by_environment=slices(await repo.cost_by_environment(session, org_id, start)),
    )


def declaration_keys(name: str) -> set[str]:
    """Every form a declared component might be reported as at runtime.

    An MCP server is declared in the descriptor as a URL, because that is what
    `references.mcp_servers` holds, while a runtime reports whatever the server calls
    itself — in practice the last path segment. Matching on the exact string alone marks
    every correctly-declared MCP server as undeclared: on the demo estate that was 14 of
    17 "undeclared" rows, all false alarms, which is worse than not checking at all
    because it trains people to ignore the column.

    So one declaration contributes several keys: the raw name, the URL without its
    scheme, the host, and the last path segment. This is a heuristic and it is the weak
    point of the reconciliation — the real fix is for the descriptor to carry a stable
    server name alongside the URL, raised as Q-017.
    """
    cleaned = name.strip().lower()
    keys = {cleaned}
    if "://" in cleaned:
        without_scheme = cleaned.split("://", 1)[1].rstrip("/")
        host, _, path = without_scheme.partition("/")
        keys.add(without_scheme)
        keys.add(host)
        if path:
            keys.add(path.rsplit("/", 1)[-1])
    return {key for key in keys if key}


async def _declaration_index(session: AsyncSession, org_id: UUID) -> dict[UUID, set[str]]:
    """Every name each agent's bill of materials declares, normalised for matching."""
    index: dict[UUID, set[str]] = {}
    for pair in await repo.declared_components_by_agent(session, org_id):
        index.setdefault(pair.agent_id, set()).update(declaration_keys(str(pair.name)))
    return index


def _offenders(callers: list[UUID], wanted: set[str], declared: dict[UUID, set[str]]) -> int:
    """How many of the agents that called this declared neither it nor its server."""
    return sum(1 for agent_id in callers if not (wanted & declared.get(agent_id, set())))


async def build_tool_inventory(
    session: AsyncSession,
    org_id: UUID,
    days: int = DEFAULT_WINDOW_DAYS,
    agent_id: UUID | None = None,
) -> ToolInventory:
    """Which tools and MCP servers the estate actually called, and whether it should have.

    The declared check is what makes this more than a usage chart, and it is asked *per
    calling agent*: a tool counts as declared for an agent if that agent's own bill of
    materials names it, or — for an MCP tool — names the server it came from. Matching on
    the server is the honest reading, because an MCP server's tool list is its own to
    change, so declaring the server declares what it exposes.

    A row is flagged when any single agent calling it has not declared it. "Some other
    team declared this tool" is no answer to "why is this agent calling it".
    """
    window = _clamp_days(days)
    since_day = _window_start(window).date()

    rows = await repo.tool_rollup(session, org_id, since_day, agent_id=agent_id)
    declared_by_agent = await _declaration_index(session, org_id)

    items: list[ToolRow] = []
    servers: set[str] = set()
    undeclared = 0

    for row in rows:
        calls = int(row.calls)
        server = str(row.server_name)
        surface = ToolSurface(str(row.surface))
        tool = str(row.tool_name)

        if surface is ToolSurface.MCP and server:
            servers.add(server)

        wanted = {tool.strip().lower()}
        if server:
            wanted.add(server.strip().lower())

        offenders = _offenders(list(row.agent_ids or []), wanted, declared_by_agent)
        if offenders:
            undeclared += 1

        items.append(
            ToolRow(
                surface=surface,
                server_name=server,
                tool_name=tool,
                agents=int(row.agents),
                calls=calls,
                errors=int(row.errors),
                denied=int(row.denied),
                error_rate_pct=_share(int(row.errors), calls),
                mean_duration_ms=int(int(row.total_duration_ms) / calls) if calls else 0,
                max_duration_ms=int(row.max_duration_ms),
                declared=offenders == 0,
                undeclared_agents=offenders,
            )
        )

    return ToolInventory(
        window_days=window, items=items, mcp_servers=len(servers), undeclared=undeclared
    )


async def build_mcp_inventory(
    session: AsyncSession,
    org_id: UUID,
    days: int = DEFAULT_WINDOW_DAYS,
    agent_id: UUID | None = None,
) -> McpInventory:
    """The MCP servers the estate is actually talking to.

    The tool names on each row come from the tool rollup rather than from a second
    grouping query, because the caller almost always wants both lists and asking twice
    for the same buckets is how the two end up disagreeing after a retry lands between
    them.
    """
    window = _clamp_days(days)
    since_day = _window_start(window).date()

    rows = await repo.mcp_server_rollup(session, org_id, since_day, agent_id=agent_id)
    declared_by_agent = await _declaration_index(session, org_id)

    tools_by_server: dict[str, list[str]] = {}
    for tool_row in await repo.tool_rollup(session, org_id, since_day, agent_id=agent_id):
        if str(tool_row.surface) == ToolSurface.MCP.value and tool_row.server_name:
            tools_by_server.setdefault(str(tool_row.server_name), []).append(
                str(tool_row.tool_name)
            )

    servers: list[McpServerRow] = []
    undeclared_servers = 0

    for row in rows:
        server = str(row.server_name)
        calls = int(row.calls)
        offenders = _offenders(
            list(row.agent_ids or []), {server.strip().lower()}, declared_by_agent
        )
        if offenders:
            undeclared_servers += 1

        servers.append(
            McpServerRow(
                server_name=server,
                tools=int(row.tools),
                agents=int(row.agents),
                calls=calls,
                errors=int(row.errors),
                denied=int(row.denied),
                error_rate_pct=_share(int(row.errors), calls),
                mean_duration_ms=int(int(row.total_duration_ms) / calls) if calls else 0,
                last_seen_at=row.last_seen_at,
                declared=offenders == 0,
                undeclared_agents=offenders,
                tool_names=sorted(tools_by_server.get(server, [])),
            )
        )

    return McpInventory(
        window_days=window,
        servers=servers,
        total_calls=sum(s.calls for s in servers),
        undeclared_servers=undeclared_servers,
    )


async def build_framework_shares(
    session: AsyncSession, org_id: UUID, days: int = DEFAULT_WINDOW_DAYS
) -> list[FrameworkShare]:
    start = _window_start(_clamp_days(days))
    rows = await repo.framework_shares(session, org_id, start)

    total_runs = sum(int(row.runs) for row in rows)
    if total_runs:
        return [
            FrameworkShare(
                framework=str(row.framework),
                agents=int(row.agents),
                runs=int(row.runs),
                share_pct=_share(int(row.runs), total_runs),
            )
            for row in rows
        ]

    # No runs in the window. Fall back to what the registry declares, so the panel says
    # what the estate is built on rather than going blank on a quiet week.
    declared = await repo.declared_framework_shares(session, org_id)
    total_agents = sum(int(row.agents) for row in declared)
    return [
        FrameworkShare(
            framework=str(row.framework),
            agents=int(row.agents),
            runs=0,
            share_pct=_share(int(row.agents), total_agents),
        )
        for row in declared
    ]


async def agent_activity_index(
    session: AsyncSession, org_id: UUID, days: int = DEFAULT_WINDOW_DAYS
) -> dict[UUID, dict[str, Any]]:
    """Per-agent totals keyed by agent id, for whoever is rendering an agent table.

    Returned as a plain mapping rather than a schema because the caller joins it onto its
    own rows; `home` owns the shape that reaches the console.
    """
    rows = await repo.per_agent_activity(session, org_id, _window_start(_clamp_days(days)))
    return {
        row.agent_id: {
            "runs": int(row.runs),
            "failures": int(row.failures),
            "cost_micros": int(row.cost_micros),
            "tokens": int(row.tokens),
            "p95_duration_ms": int(row.p95_duration_ms),
            "last_run_at": row.last_run_at,
            "running_now": int(row.running_now),
            "escalations": int(row.escalations),
            "success_rate_pct": _share(int(row.runs) - int(row.failures), int(row.runs)),
        }
        for row in rows
    }


async def build_snapshot(
    session: AsyncSession, org_id: UUID, days: int = DEFAULT_WINDOW_DAYS
) -> OperationsSnapshot:
    """Everything this domain knows about the window.

    One call so the landing page makes one round trip for the operational half of what it
    shows. The governance half — approvals, findings, service levels — is added by
    `home`, which is the only module permitted to know about all of them.
    """
    window = _clamp_days(days)
    start = _window_start(window)

    totals = await repo.window_totals(session, org_id, start)
    previous = await repo.window_totals(session, org_id, start - timedelta(days=window), start)

    runs_total = int(totals.runs)
    failed = int(totals.failed)
    succeeded = int(totals.succeeded)
    refused = int(totals.refused)

    # Refusals are excluded from the denominator rather than counted as failures. An
    # agent declining to act is the guardrail working, and scoring it as unreliable is
    # how somebody ends up arguing for switching the guardrail off.
    judged = succeeded + failed

    outcomes = [
        RunOutcomeCount(outcome=RunOutcome(str(row.outcome)), runs=int(row.runs))
        for row in await repo.outcome_counts(session, org_id, start)
    ]

    page = await list_runs(session, org_id, days=window, limit=8)

    return OperationsSnapshot(
        window_days=window,
        generated_at=datetime.now(tz=UTC),
        runs_total=runs_total,
        runs_previous=int(previous.runs),
        runs_failed=failed,
        runs_refused=refused,
        running_now=await repo.count_running(session, org_id),
        agents_active=int(totals.agents_active),
        escalations=int(totals.escalations),
        success_rate_pct=_share(succeeded, judged) if judged else 100.0,
        p50_duration_ms=int(totals.p50_duration_ms),
        p95_duration_ms=int(totals.p95_duration_ms),
        activity=await build_activity_series(session, org_id, window),
        outcomes=outcomes,
        frameworks=await build_framework_shares(session, org_id, window),
        cost=await build_cost_report(session, org_id, window),
        tools=await build_tool_inventory(session, org_id, window),
        recent_runs=page.items,
    )


async def build_agent_operations(
    session: AsyncSession, org_id: UUID, agent_id: UUID, days: int = DEFAULT_WINDOW_DAYS
) -> AgentOperations:
    """The window, for one agent.

    Every aggregate here is the estate query with an agent predicate added, so a number
    on this page and the same number on the dashboard are computed by one piece of SQL.
    The alternative — a parallel set of per-agent queries — is how a detail page comes to
    disagree with the overview it was opened from.
    """
    window = _clamp_days(days)
    start = _window_start(window)

    totals = await repo.window_totals(session, org_id, start, agent_id=agent_id)
    previous = await repo.window_totals(
        session, org_id, start - timedelta(days=window), start, agent_id=agent_id
    )

    failed = int(totals.failed)
    succeeded = int(totals.succeeded)
    judged = succeeded + failed
    total_cost = int(totals.cost_micros)

    by_day_index = {
        row.day: row for row in await repo.cost_by_day(session, org_id, start, agent_id=agent_id)
    }
    axis = [(start + timedelta(days=offset)).date() for offset in range(window)]

    page = await list_runs(session, org_id, days=window, agent_id=agent_id, limit=15)
    inventory = await build_tool_inventory(session, org_id, window, agent_id=agent_id)
    mcp = await build_mcp_inventory(session, org_id, window, agent_id=agent_id)

    return AgentOperations(
        agent_id=agent_id,
        window_days=window,
        generated_at=datetime.now(tz=UTC),
        runs_total=int(totals.runs),
        runs_previous=int(previous.runs),
        runs_failed=failed,
        runs_refused=int(totals.refused),
        running_now=await repo.count_running(session, org_id, agent_id=agent_id),
        escalations=int(totals.escalations),
        success_rate_pct=_share(succeeded, judged) if judged else 100.0,
        p50_duration_ms=int(totals.p50_duration_ms),
        p95_duration_ms=int(totals.p95_duration_ms),
        cost_micros=total_cost,
        previous_cost_micros=int(previous.cost_micros),
        tokens=int(totals.tokens_in) + int(totals.tokens_out),
        activity=await build_activity_series(session, org_id, window, agent_id=agent_id),
        outcomes=[
            RunOutcomeCount(outcome=RunOutcome(str(row.outcome)), runs=int(row.runs))
            for row in await repo.outcome_counts(session, org_id, start, agent_id=agent_id)
        ],
        error_kinds=[
            ErrorKindCount(error_kind=str(row.label), runs=int(row.runs))
            for row in await repo.error_kinds(session, org_id, start, agent_id=agent_id)
        ],
        by_model=[
            CostSlice(
                label=str(row.label),
                cost_micros=int(row.cost_micros),
                tokens=int(row.tokens),
                runs=int(row.runs),
                share_pct=_share(int(row.cost_micros), total_cost),
            )
            for row in await repo.cost_by_model(session, org_id, start, agent_id=agent_id)
        ],
        cost_by_day=[
            CostDay(
                day=day,
                cost_micros=int(getattr(by_day_index.get(day), "cost_micros", 0) or 0),
                tokens_in=int(getattr(by_day_index.get(day), "tokens_in", 0) or 0),
                tokens_out=int(getattr(by_day_index.get(day), "tokens_out", 0) or 0),
                runs=int(getattr(by_day_index.get(day), "runs", 0) or 0),
            )
            for day in axis
        ],
        tools=inventory.items,
        mcp_servers=mcp.servers,
        recent_runs=page.items,
    )


def self_ms_by_seq(steps: list[StepRow]) -> dict[int, int]:
    """Exclusive time per step: duration minus the time spent in direct children."""
    children: dict[int, list[int]] = {}
    duration: dict[int, int] = {}
    for step in steps:
        duration[step.seq] = step.duration_ms or 0
        if step.parent_seq is not None:
            children.setdefault(step.parent_seq, []).append(step.seq)

    self_ms: dict[int, int] = {}
    for step in steps:
        child_sum = sum(duration.get(child, 0) for child in children.get(step.seq, []))
        self_ms[step.seq] = max(duration.get(step.seq, 0) - child_sum, 0)
    return self_ms


def critical_path(steps: list[StepRow]) -> list[int]:
    """The chain of steps whose exclusive time sums to the longest path through the trace."""
    if not steps:
        return []

    exclusive = self_ms_by_seq(steps)
    children: dict[int | None, list[int]] = {}
    for step in steps:
        children.setdefault(step.parent_seq, []).append(step.seq)

    def longest_from(seq: int) -> tuple[list[int], int]:
        child_seqs = children.get(seq, [])
        own = exclusive.get(seq, 0)
        if not child_seqs:
            return ([seq], own)
        best_path, best_cost = ([], -1)
        for child in child_seqs:
            sub_path, sub_cost = longest_from(child)
            if sub_cost > best_cost:
                best_path, best_cost = sub_path, sub_cost
        return ([seq, *best_path], own + best_cost)

    roots = children.get(None, [])
    if not roots:
        return [steps[0].seq]

    best: list[int] = []
    best_cost = -1
    for root in roots:
        path, cost = longest_from(root)
        if cost > best_cost:
            best, best_cost = path, cost
    return best


def _percentile(values: list[int], quantile: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (len(ordered) - 1) * quantile
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return int(ordered[lower] + (ordered[upper] - ordered[lower]) * weight)


async def build_run_detail(session: AsyncSession, org_id: UUID, run_id: UUID) -> RunDetail:
    row = await repo.fetch_run_row(session, org_id, run_id)
    if row is None:
        raise RunNotFoundError(run_id)

    total = await repo.count_steps_for_run(session, org_id, run_id)
    fetched = await repo.fetch_steps_for_run(session, org_id, run_id, limit=MAX_STEPS_RETURN)
    truncated = total > MAX_STEPS_RETURN
    if truncated:
        fetched = fetched[:MAX_STEPS_RETURN]

    steps = [StepRow.model_validate(step) for step in fetched]
    return RunDetail(
        run=RunRow.model_validate(row._mapping),
        steps=steps,
        self_ms_by_seq=self_ms_by_seq(steps),
        critical_path=critical_path(steps),
        steps_truncated=truncated,
    )


async def build_observed_graph(
    session: AsyncSession, org_id: UUID, agent_id: UUID, days: int = DEFAULT_WINDOW_DAYS
) -> ObservedGraph:
    window = _clamp_days(days)
    since = _window_start(window)
    rows = await repo.fetch_trace_steps_for_agent(session, org_id, agent_id, since)

    by_run: dict[UUID, list[Any]] = {}
    for row in rows:
        by_run.setdefault(row.run_id, []).append(row)

    node_runs: dict[str, set[UUID]] = {}
    node_exec: dict[str, int] = {}
    node_failures: dict[str, int] = {}
    node_durations: dict[str, list[int]] = {}
    node_cost: dict[str, int] = {}
    node_tools: dict[str, set[str]] = {}

    edge_traversals: dict[tuple[str, str], int] = {}
    edge_failures: dict[tuple[str, str], int] = {}
    entry_nodes: set[str] = set()
    terminal_nodes: set[str] = set()

    for run_id, run_rows in by_run.items():
        seq_to_node: dict[int, str] = {}
        for row in run_rows:
            if row.kind == StepKind.NODE.value:
                seq_to_node[row.seq] = row.name

        node_steps = [row for row in run_rows if row.kind == StepKind.NODE.value]
        if node_steps:
            entry_nodes.add(node_steps[0].name)
            terminal_nodes.add(node_steps[-1].name)

        for row in run_rows:
            if row.kind != StepKind.NODE.value:
                if row.kind in _TOOL_STEP_KINDS and row.parent_seq in seq_to_node:
                    node_tools.setdefault(seq_to_node[row.parent_seq], set()).add(row.name)
                continue

            node_exec[row.name] = node_exec.get(row.name, 0) + 1
            node_runs.setdefault(row.name, set()).add(run_id)
            if row.outcome in _STEP_FAILURES:
                node_failures[row.name] = node_failures.get(row.name, 0) + 1
            if row.duration_ms is not None:
                node_durations.setdefault(row.name, []).append(int(row.duration_ms))
            node_cost[row.name] = node_cost.get(row.name, 0) + int(row.cost_micros or 0)

        for prev, current in pairwise(node_steps):
            key = (prev.name, current.name)
            edge_traversals[key] = edge_traversals.get(key, 0) + 1
            if current.outcome in _STEP_FAILURES:
                edge_failures[key] = edge_failures.get(key, 0) + 1

    nodes = [
        GraphNodeStat(
            name=name,
            kind=StepKind.NODE,
            runs=len(node_runs.get(name, set())),
            executions=node_exec.get(name, 0),
            failures=node_failures.get(name, 0),
            p50_duration_ms=_percentile(node_durations.get(name, []), 0.5),
            p95_duration_ms=_percentile(node_durations.get(name, []), 0.95),
            cost_micros=node_cost.get(name, 0),
            tools=sorted(node_tools.get(name, set())),
        )
        for name in sorted(node_exec)
    ]

    edges = [
        GraphEdgeStat(
            from_node=from_node,
            to_node=to_node,
            traversals=count,
            failures=edge_failures.get((from_node, to_node), 0),
        )
        for (from_node, to_node), count in sorted(edge_traversals.items())
    ]

    return ObservedGraph(
        agent_id=agent_id,
        window_days=window,
        nodes=nodes,
        edges=edges,
        entry_nodes=sorted(entry_nodes),
        terminal_nodes=sorted(terminal_nodes),
    )


def environment_totals(series: ActivitySeries) -> dict[str, int]:
    """Total runs per environment across the series. Used by the console's legend."""
    return {name: sum(values) for name, values in series.by_environment.items()}


def busiest_day(series: ActivitySeries) -> tuple[date, int] | None:
    """The day with the most runs, or None for an empty window."""
    if not series.days or not series.totals:
        return None
    peak = max(range(len(series.totals)), key=lambda i: series.totals[i])
    return series.days[peak], series.totals[peak]
