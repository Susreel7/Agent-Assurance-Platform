"""Operations against a real Postgres.

Everything here is database behaviour a mocked session would only assert about itself:
the partition the run lands in, the trigger that refuses to reopen a finished run, the
conflict target that makes a replayed delivery a no-op, and `percentile_cont` skipping
the nulls that in-flight runs leave behind.

Ingest is at-least-once by design, so most of these tests are the same report sent
twice. That is not a pathological case — a collector that buffers to disk replays after
every restart.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.operations import repository as repo
from app.domains.operations import service
from app.domains.operations.schemas import (
    RunBatch,
    RunOutcome,
    RunReport,
    StepKind,
    StepReport,
    ToolCallReport,
    ToolSurface,
)
from app.domains.registry import repository as registry_repo

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

# Today at midday, because the daily rollups bucket by date and a run near a UTC midnight
# would land in yesterday's bucket on some runs and today's on others.
#
# It is midday *today*, which means it is in the future for any run of the suite before
# 12:00 UTC. Derive other timestamps from NOW, never from `datetime.now()` — mixing the
# two produced a test that failed every morning and passed every afternoon, with an error
# about `ended_at` preceding `started_at` that said nothing about the clock.
NOW = datetime.now(tz=UTC).replace(hour=12, minute=0, second=0, microsecond=0)


async def make_agent(
    session: AsyncSession, org_id: uuid.UUID, *, framework: str = "langgraph"
) -> Any:
    agent = await registry_repo.insert_agent(
        session,
        org_id,
        {
            "id": uuid.uuid4(),
            "urn": f"urn:aap:ops:{uuid.uuid4().hex[:8]}:eu",
            "display_name": "Ops Agent",
            "lifecycle_state": "production",
        },
    )
    version = await registry_repo.insert_version(
        session,
        org_id,
        agent.id,
        {
            "id": uuid.uuid4(),
            "semver": "1.0.0",
            "descriptor_json": {"aap_version": "0.1"},
            "descriptor_digest": "sha256:" + uuid.uuid4().hex * 2,
            "environment": "production",
            "runtime_framework": framework,
            "published_by": "person:it@test.example",
        },
    )
    await session.flush()
    await session.execute(
        text("UPDATE agents SET current_version_id = :v WHERE id = :a"),
        {"v": version.id, "a": agent.id},
    )
    return agent


def report(agent_id: uuid.UUID, **overrides: Any) -> RunReport:
    base: dict[str, Any] = {
        "run_id": uuid.uuid4(),
        "agent_id": agent_id,
        "started_at": NOW,
        "environment": "production",
    }
    return RunReport.model_validate(base | overrides)


# ----------------------------------------------------------------------
# Ingest
# ----------------------------------------------------------------------


async def test_a_run_is_opened_then_closed_by_a_second_report(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """The same `run_id` sent twice: once when work starts, once when it finishes. The
    second report has to find the first rather than create a duplicate."""
    agent = await make_agent(session, org_id)
    open_report = report(agent.id)

    opened = await service.record_runs(session, org_id, RunBatch(runs=[open_report]))
    assert (opened.opened, opened.closed) == (1, 0)

    closed = await service.record_runs(
        session,
        org_id,
        RunBatch(
            runs=[
                open_report.model_copy(
                    update={
                        "ended_at": NOW + timedelta(seconds=3),
                        "outcome": RunOutcome.SUCCEEDED,
                        "cost_micros": 12_000,
                    }
                )
            ]
        ),
    )
    assert (closed.opened, closed.closed, closed.ignored) == (0, 1, 0)

    page = await service.list_runs(session, org_id, agent_id=agent.id)
    assert page.total == 1
    assert page.items[0].outcome is RunOutcome.SUCCEEDED
    assert page.items[0].duration_ms == 3_000
    assert page.items[0].cost_micros == 12_000


async def test_machine_reporter_cannot_cross_its_agent_or_environment(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    bound = await make_agent(session, org_id)
    other = await make_agent(session, org_id)

    with pytest.raises(service.ReporterScopeError, match="different agent"):
        await service.record_runs(
            session,
            org_id,
            RunBatch(runs=[report(other.id)]),
            reporter_agent_id=bound.id,
            reporter_environment="production",
        )

    with pytest.raises(service.ReporterScopeError, match="production"):
        await service.record_runs(
            session,
            org_id,
            RunBatch(runs=[report(bound.id, environment="staging")]),
            reporter_agent_id=bound.id,
            reporter_environment="production",
        )


async def test_machine_reporter_identity_overrides_caller_supplied_audit_text(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    agent = await make_agent(session, org_id)
    run = report(agent.id, reported_by="person:forged@example")
    credential_id = uuid.uuid4()
    reporter_ref = service.workload_reporter_ref(credential_id)
    assert len(reporter_ref) <= 32

    await service.record_runs(
        session,
        org_id,
        RunBatch(runs=[run]),
        reporter_agent_id=agent.id,
        reporter_environment="production",
        reporter_ref=reporter_ref,
    )

    recorded = await session.scalar(
        text(
            "SELECT reported_by FROM agent_runs "
            "WHERE org_id = :org_id AND id = :run_id AND started_at = :started_at"
        ),
        {"org_id": org_id, "run_id": run.run_id, "started_at": run.started_at},
    )
    assert recorded == reporter_ref


async def test_replaying_a_finished_run_is_ignored_rather_than_failing_the_batch(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """The immutability trigger refuses to rewrite a terminal run, so the upsert is
    guarded by `WHERE outcome = 'running'`. Without that guard one duplicate delivery
    takes down the whole batch it arrived in."""
    agent = await make_agent(session, org_id)
    finished = report(agent.id, ended_at=NOW + timedelta(seconds=1), outcome=RunOutcome.SUCCEEDED)

    first = await service.record_runs(session, org_id, RunBatch(runs=[finished]))
    assert first.closed == 1

    replay = await service.record_runs(session, org_id, RunBatch(runs=[finished]))
    assert replay.ignored == 1

    assert (await service.list_runs(session, org_id, agent_id=agent.id)).total == 1


async def test_a_batch_naming_an_unregistered_agent_is_rejected_whole(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """The opposite of how evidence ingest behaves, deliberately. A run is reported by
    the agent or by a collector watching it, and both know which agent they are — a
    silently discarded run is a gap in a cost report nobody will ever explain."""
    agent = await make_agent(session, org_id)
    batch = RunBatch(
        runs=[
            report(agent.id),
            RunReport.model_validate({"agent_urn": "urn:aap:ops:nobody:eu", "started_at": NOW}),
        ]
    )

    with pytest.raises(service.UnknownAgentError, match="urn:aap:ops:nobody:eu"):
        await service.record_runs(session, org_id, batch)


async def test_a_run_reported_by_urn_resolves_to_the_registered_agent(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """An SDK knows its URN from configuration next to the agent's code; the id is a
    database key it has no reason to hold."""
    agent = await make_agent(session, org_id)
    await service.record_runs(
        session,
        org_id,
        RunBatch(runs=[RunReport.model_validate({"agent_urn": agent.urn, "started_at": NOW})]),
    )

    page = await service.list_runs(session, org_id, agent_id=agent.id)
    assert page.total == 1
    assert page.items[0].agent_urn == agent.urn


async def test_tool_counters_accumulate_across_batches_within_a_day(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """One daily bucket per agent, surface, server and tool. Two batches touching it
    add rather than replace, and the maximum takes the larger of the two."""
    agent = await make_agent(session, org_id)
    call = ToolCallReport(
        surface=ToolSurface.MCP,
        server_name="stripe",
        tool_name="list_charges",
        calls=4,
        errors=1,
        total_duration_ms=800,
        max_duration_ms=400,
    )

    await service.record_runs(session, org_id, RunBatch(runs=[report(agent.id, tools=[call])]))
    await service.record_runs(
        session,
        org_id,
        RunBatch(
            runs=[
                report(
                    agent.id,
                    tools=[call.model_copy(update={"calls": 2, "max_duration_ms": 1_500})],
                )
            ]
        ),
    )

    inventory = await service.build_tool_inventory(session, org_id, 7)
    row = next(r for r in inventory.items if r.tool_name == "list_charges")
    assert row.calls == 6
    assert row.errors == 2
    assert row.max_duration_ms == 1_500


# ----------------------------------------------------------------------
# Reads
# ----------------------------------------------------------------------


async def test_the_activity_series_fills_days_that_had_no_runs(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """A day with no runs is zero, not missing. Gap-filling is what makes a quiet
    weekend a visible trough rather than a straight line drawn across it."""
    agent = await make_agent(session, org_id)
    await service.record_runs(session, org_id, RunBatch(runs=[report(agent.id)]))

    series = await service.build_activity_series(session, org_id, 14)
    assert len(series.days) == 14
    assert len(series.totals) == 14
    assert sum(series.totals) == 1
    assert series.totals[-1] == 1


async def test_an_in_flight_run_is_not_counted_as_instantaneous(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """`percentile_cont` ignores nulls, which is the behaviour we want: a run with no
    duration yet must not drag the median to zero."""
    agent = await make_agent(session, org_id)
    await service.record_runs(
        session,
        org_id,
        RunBatch(
            runs=[
                report(
                    agent.id,
                    ended_at=NOW + timedelta(seconds=10),
                    outcome=RunOutcome.SUCCEEDED,
                ),
                report(agent.id),
            ]
        ),
    )

    snapshot = await service.build_snapshot(session, org_id, 7)
    assert snapshot.runs_total == 2
    assert snapshot.running_now == 1
    assert snapshot.p50_duration_ms == 10_000


async def test_refusals_are_excluded_from_the_success_rate(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """An agent declining to act is the guardrail working. Counting it as a failure
    makes a well-governed estate look broken and gives somebody a reason to turn the
    guardrail off."""
    agent = await make_agent(session, org_id)
    ended = {"ended_at": NOW + timedelta(seconds=1)}
    await service.record_runs(
        session,
        org_id,
        RunBatch(
            runs=[
                report(agent.id, outcome=RunOutcome.SUCCEEDED, **ended),
                report(agent.id, outcome=RunOutcome.REFUSED, **ended),
            ]
        ),
    )

    snapshot = await service.build_snapshot(session, org_id, 7)
    assert snapshot.runs_refused == 1
    assert snapshot.success_rate_pct == 100.0


async def test_a_tool_is_undeclared_when_the_agent_calling_it_never_declared_it(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """Asked per calling agent, not per estate. "Some other team declared this tool" is
    no answer to "why is this agent calling it"."""
    agent = await make_agent(session, org_id)
    await service.record_runs(
        session,
        org_id,
        RunBatch(
            runs=[
                report(
                    agent.id,
                    tools=[ToolCallReport(surface=ToolSurface.NATIVE, tool_name="exec_shell")],
                )
            ]
        ),
    )

    inventory = await service.build_tool_inventory(session, org_id, 7)
    row = next(r for r in inventory.items if r.tool_name == "exec_shell")
    assert row.declared is False
    assert row.undeclared_agents == 1
    assert inventory.undeclared == 1


async def test_an_mcp_server_declared_as_a_url_reconciles_with_its_short_name(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """The descriptor holds the server as a URL; the runtime reports `stripe`. Without
    normalisation every correctly-declared MCP server is flagged, which is worse than
    not checking at all (D-039)."""
    agent = await make_agent(session, org_id)
    version_id = (
        await session.execute(
            text("SELECT current_version_id FROM agents WHERE id = :a"), {"a": agent.id}
        )
    ).scalar_one()
    await session.execute(
        text(
            "INSERT INTO bom_components (id, org_id, agent_version_id, kind, name) "
            "VALUES (gen_random_uuid(), :o, :v, 'mcp_server', :n)"
        ),
        {"o": org_id, "v": version_id, "n": "https://mcp.northwind.internal/stripe"},
    )

    await service.record_runs(
        session,
        org_id,
        RunBatch(
            runs=[
                report(
                    agent.id,
                    tools=[
                        ToolCallReport(
                            surface=ToolSurface.MCP,
                            server_name="stripe",
                            tool_name="list_charges",
                        )
                    ],
                )
            ]
        ),
    )

    mcp = await service.build_mcp_inventory(session, org_id, 7)
    assert [s.server_name for s in mcp.servers] == ["stripe"]
    assert mcp.servers[0].declared is True
    assert mcp.undeclared_servers == 0


async def test_framework_shares_come_from_the_version_the_run_executed(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """Counted from the version that actually ran, so a fleet mid-migration shows both
    frameworks in the proportion they were really used."""
    langgraph = await make_agent(session, org_id, framework="langgraph")
    cursor_sdk = await make_agent(session, org_id, framework="cursor-sdk")

    await service.record_runs(
        session,
        org_id,
        RunBatch(runs=[report(langgraph.id), report(langgraph.id), report(cursor_sdk.id)]),
    )

    shares = {s.framework: s for s in await service.build_framework_shares(session, org_id, 7)}
    assert shares["langgraph"].runs == 2
    assert shares["cursor-sdk"].runs == 1
    assert shares["langgraph"].share_pct == pytest.approx(66.7, abs=0.1)


async def test_per_agent_operations_scope_to_that_agent_alone(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """The detail page runs the estate's queries with an agent predicate added, so this
    also guards against a predicate going missing from one of them."""
    mine = await make_agent(session, org_id)
    theirs = await make_agent(session, org_id)
    ended = {"ended_at": NOW + timedelta(seconds=2), "outcome": RunOutcome.SUCCEEDED}

    await service.record_runs(
        session,
        org_id,
        RunBatch(
            runs=[
                report(mine.id, cost_micros=5_000, **ended),
                report(theirs.id, cost_micros=90_000, **ended),
            ]
        ),
    )

    scoped = await service.build_agent_operations(session, org_id, mine.id, 7)
    assert scoped.runs_total == 1
    assert scoped.cost_micros == 5_000
    assert sum(scoped.activity.totals) == 1


async def test_an_agent_that_has_never_run_returns_an_empty_window_not_an_error(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """A registered-this-morning agent is a real and common state, and it is exactly
    the one somebody is most likely to be checking on."""
    agent = await make_agent(session, org_id)
    scoped = await service.build_agent_operations(session, org_id, agent.id, 30)

    assert scoped.runs_total == 0
    assert scoped.success_rate_pct == 100.0
    assert len(scoped.activity.days) == 30
    assert scoped.recent_runs == []


async def test_runs_are_scoped_to_their_organisation(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    agent = await make_agent(session, org_id)
    await service.record_runs(session, org_id, RunBatch(runs=[report(agent.id)]))

    assert (await service.list_runs(session, org_id)).total == 1
    assert (await service.list_runs(session, other_org_id)).total == 0
    assert await repo.count_running(session, other_org_id) == 0


# ----------------------------------------------------------------------
# Run tracing
# ----------------------------------------------------------------------


def _steps(**overrides: Any) -> list[StepReport]:
    end = NOW + timedelta(seconds=2)
    base = StepReport(
        seq=0,
        kind=StepKind.NODE,
        name="router",
        started_at=NOW,
        ended_at=end,
        outcome=RunOutcome.SUCCEEDED,
    )
    return [base.model_copy(update=overrides)] if overrides else [base]


async def test_replaying_the_same_step_batch_writes_one_row(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    agent = await make_agent(session, org_id)
    run_id = uuid.uuid4()
    ended = {"ended_at": NOW + timedelta(seconds=2), "outcome": RunOutcome.SUCCEEDED}
    payload = report(agent.id, run_id=run_id, steps=_steps(), **ended)

    first = await service.record_runs(session, org_id, RunBatch(runs=[payload]))
    second = await service.record_runs(session, org_id, RunBatch(runs=[payload]))
    assert first.steps == 1
    assert second.steps == 0

    detail = await service.build_run_detail(session, org_id, run_id)
    assert len(detail.steps) == 1


async def test_duplicate_step_keys_in_one_batch_are_collapsed_before_upsert(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    agent = await make_agent(session, org_id)
    run_id = uuid.uuid4()
    end = NOW + timedelta(seconds=1)
    open_step = StepReport(
        seq=0,
        kind=StepKind.NODE,
        name="first",
        started_at=NOW,
        outcome=RunOutcome.RUNNING,
    )
    closed_step = open_step.model_copy(
        update={"name": "second", "ended_at": end, "outcome": RunOutcome.SUCCEEDED}
    )
    await service.record_runs(
        session,
        org_id,
        RunBatch(
            runs=[
                report(agent.id, run_id=run_id, steps=[open_step]),
                report(
                    agent.id,
                    run_id=run_id,
                    steps=[closed_step],
                    ended_at=NOW + timedelta(seconds=2),
                    outcome=RunOutcome.SUCCEEDED,
                ),
            ]
        ),
    )
    detail = await service.build_run_detail(session, org_id, run_id)
    assert len(detail.steps) == 1
    assert detail.steps[0].name == "second"


async def test_a_finished_step_cannot_be_rewritten(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    agent = await make_agent(session, org_id)
    run_id = uuid.uuid4()
    finished = report(
        agent.id,
        run_id=run_id,
        steps=_steps(),
        ended_at=NOW + timedelta(seconds=2),
        outcome=RunOutcome.SUCCEEDED,
    )
    await service.record_runs(session, org_id, RunBatch(runs=[finished]))

    with pytest.raises(Exception, match="already finished"):
        await session.execute(
            text(
                "UPDATE run_steps SET outcome = 'failed' "
                "WHERE org_id = :o AND run_id = :r AND seq = 0"
            ),
            {"o": org_id, "r": run_id},
        )


async def test_steps_route_to_a_monthly_partition(session: AsyncSession, org_id: uuid.UUID) -> None:
    agent = await make_agent(session, org_id)
    run_id = uuid.uuid4()
    await service.record_runs(
        session,
        org_id,
        RunBatch(
            runs=[
                report(
                    agent.id,
                    run_id=run_id,
                    steps=_steps(),
                    ended_at=NOW + timedelta(seconds=2),
                    outcome=RunOutcome.SUCCEEDED,
                )
            ]
        ),
    )
    partition = (
        await session.execute(
            text(
                "SELECT tableoid::regclass::text FROM run_steps "
                "WHERE org_id = :o AND run_id = :r LIMIT 1"
            ),
            {"o": org_id, "r": run_id},
        )
    ).scalar_one()
    assert partition.startswith("run_steps_")
    assert not partition.endswith("_default")


async def test_the_database_refuses_a_node_that_claims_a_tool_surface(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    agent = await make_agent(session, org_id)
    with pytest.raises(Exception, match="run_steps_surface_matches_kind"):
        await session.execute(
            text(
                "INSERT INTO run_steps (org_id, run_id, agent_id, seq, kind, name, surface, "
                "started_at, ended_at, duration_ms, outcome) "
                "VALUES (:o, :r, :a, 0, 'node', 'router', 'native', :t, :t, 1, 'succeeded')"
            ),
            {"o": org_id, "r": uuid.uuid4(), "a": agent.id, "t": NOW},
        )


async def test_the_database_refuses_an_mcp_step_with_no_server(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    agent = await make_agent(session, org_id)
    with pytest.raises(Exception, match="run_steps_mcp_names_its_server"):
        await session.execute(
            text(
                "INSERT INTO run_steps (org_id, run_id, agent_id, seq, kind, name, surface, "
                "server_name, started_at, ended_at, duration_ms, outcome) "
                "VALUES (:o, :r, :a, 0, 'mcp_tool', 'query', 'mcp', '', :t, :t, 1, 'succeeded')"
            ),
            {"o": org_id, "r": uuid.uuid4(), "a": agent.id, "t": NOW},
        )


async def test_run_detail_derives_self_time_and_critical_path(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    agent = await make_agent(session, org_id)
    run_id = uuid.uuid4()
    end = NOW + timedelta(seconds=10)
    steps = [
        StepReport(
            seq=0,
            kind=StepKind.NODE,
            name="root",
            started_at=NOW,
            ended_at=NOW + timedelta(seconds=10),
            outcome=RunOutcome.SUCCEEDED,
        ),
        StepReport(
            seq=1,
            parent_seq=0,
            kind=StepKind.NODE,
            name="light",
            started_at=NOW + timedelta(seconds=1),
            ended_at=NOW + timedelta(seconds=3),
            outcome=RunOutcome.SUCCEEDED,
        ),
        StepReport(
            seq=2,
            parent_seq=0,
            kind=StepKind.NODE,
            name="heavy",
            started_at=NOW + timedelta(seconds=1),
            ended_at=NOW + timedelta(seconds=7),
            outcome=RunOutcome.SUCCEEDED,
        ),
    ]
    await service.record_runs(
        session,
        org_id,
        RunBatch(
            runs=[
                report(
                    agent.id,
                    run_id=run_id,
                    steps=steps,
                    ended_at=end,
                    outcome=RunOutcome.SUCCEEDED,
                )
            ]
        ),
    )
    detail = await service.build_run_detail(session, org_id, run_id)
    assert detail.self_ms_by_seq[0] == 2000
    assert detail.critical_path == [0, 2]


async def test_observed_graph_percentiles_skip_in_flight_steps(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    agent = await make_agent(session, org_id)
    run_id = uuid.uuid4()
    steps = [
        StepReport(
            seq=0,
            kind=StepKind.NODE,
            name="router",
            started_at=NOW,
            ended_at=NOW + timedelta(seconds=5),
            outcome=RunOutcome.SUCCEEDED,
        ),
        StepReport(
            seq=1,
            kind=StepKind.NODE,
            name="router",
            started_at=NOW + timedelta(seconds=6),
            outcome=RunOutcome.RUNNING,
        ),
    ]
    await service.record_runs(
        session,
        org_id,
        RunBatch(runs=[report(agent.id, run_id=run_id, steps=steps)]),
    )
    graph = await service.build_observed_graph(session, org_id, agent.id, 7)
    node = next(n for n in graph.nodes if n.name == "router")
    assert node.p50_duration_ms == 5000
    assert node.p95_duration_ms == 5000


async def test_observed_graph_counts_retries_and_cycles(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    agent = await make_agent(session, org_id)
    run_id = uuid.uuid4()
    end = NOW + timedelta(seconds=4)
    steps = [
        StepReport(
            seq=0,
            kind=StepKind.NODE,
            name="a",
            started_at=NOW,
            ended_at=NOW + timedelta(seconds=1),
            outcome=RunOutcome.SUCCEEDED,
        ),
        StepReport(
            seq=1,
            kind=StepKind.NODE,
            name="b",
            started_at=NOW + timedelta(seconds=1),
            ended_at=NOW + timedelta(seconds=2),
            outcome=RunOutcome.FAILED,
        ),
        StepReport(
            seq=2,
            kind=StepKind.NODE,
            name="a",
            started_at=NOW + timedelta(seconds=2),
            ended_at=NOW + timedelta(seconds=3),
            outcome=RunOutcome.SUCCEEDED,
            attempt=2,
        ),
        StepReport(
            seq=3,
            kind=StepKind.NODE,
            name="b",
            started_at=NOW + timedelta(seconds=3),
            ended_at=end,
            outcome=RunOutcome.SUCCEEDED,
            attempt=2,
        ),
    ]
    await service.record_runs(
        session,
        org_id,
        RunBatch(
            runs=[
                report(
                    agent.id,
                    run_id=run_id,
                    steps=steps,
                    ended_at=end,
                    outcome=RunOutcome.SUCCEEDED,
                )
            ]
        ),
    )
    graph = await service.build_observed_graph(session, org_id, agent.id, 7)
    a = next(n for n in graph.nodes if n.name == "a")
    assert a.executions == 2
    assert a.runs == 1
    edge = next(e for e in graph.edges if e.from_node == "a" and e.to_node == "b")
    assert edge.traversals == 2
    assert edge.failures == 1


async def test_run_detail_is_scoped_to_the_callers_organisation(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    agent = await make_agent(session, org_id)
    run_id = uuid.uuid4()
    await service.record_runs(
        session,
        org_id,
        RunBatch(
            runs=[
                report(
                    agent.id,
                    run_id=run_id,
                    steps=_steps(),
                    ended_at=NOW + timedelta(seconds=2),
                    outcome=RunOutcome.SUCCEEDED,
                )
            ]
        ),
    )
    with pytest.raises(service.RunNotFoundError):
        await service.build_run_detail(session, other_org_id, run_id)


async def test_observed_graph_is_scoped_to_the_callers_organisation(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    agent = await make_agent(session, org_id)
    await service.record_runs(
        session,
        org_id,
        RunBatch(
            runs=[
                report(
                    agent.id,
                    steps=_steps(),
                    ended_at=NOW + timedelta(seconds=2),
                    outcome=RunOutcome.SUCCEEDED,
                )
            ]
        ),
    )
    mine = await service.build_observed_graph(session, org_id, agent.id, 7)
    theirs = await service.build_observed_graph(session, other_org_id, agent.id, 7)
    assert mine.nodes[0].executions == 1
    assert theirs.nodes == []
