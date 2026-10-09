"""Operations logic that has no database in it.

The three things worth pinning down here are the ones that would fail quietly. Bucket
merging protects against a Postgres error that only appears under a batch shape nobody
constructs by hand. Duration is computed rather than trusted, and a reporter sending its
own figure must not be able to change it. And the declaration heuristic is the weak
point of the whole reconciliation — it is the difference between "14 undeclared MCP
servers" and "none", on the same data.

The query-shaped half of this domain is covered by tests/integration/test_operations.py
against a real Postgres, because the interesting parts of it — partition routing, the
immutability trigger, `percentile_cont` over nulls — are database behaviour that a mock
would only assert about itself.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domains.operations.schemas import (
    ActivitySeries,
    RunOutcome,
    RunReport,
    StepKind,
    StepReport,
    StepRow,
    ToolCallReport,
    ToolSurface,
)
from app.domains.operations.service import (
    _collapse_step_rows,
    _run_values,
    _step_values,
    _tool_buckets,
    _window_start,
    busiest_day,
    critical_path,
    declaration_keys,
    environment_totals,
    self_ms_by_seq,
)

AGENT = uuid4()
START = datetime(2026, 9, 14, 10, 0, tzinfo=UTC)


def _report(**overrides: object) -> RunReport:
    base: dict[str, object] = {"agent_id": AGENT, "started_at": START}
    return RunReport.model_validate(base | overrides)


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


def test_a_batch_hitting_one_bucket_twice_is_merged_into_a_single_row() -> None:
    """Postgres refuses an ON CONFLICT statement that touches the same row twice, so
    this is a correctness requirement rather than an optimisation: without it, a batch
    of runs that all called the same MCP server fails outright."""
    call = ToolCallReport(
        surface=ToolSurface.MCP,
        server_name="stripe",
        tool_name="list_charges",
        calls=3,
        errors=1,
        total_duration_ms=300,
        max_duration_ms=200,
    )
    other = call.model_copy(update={"calls": 2, "errors": 0, "max_duration_ms": 900})

    buckets = _tool_buckets([(_report(tools=[call]), AGENT), (_report(tools=[other]), AGENT)])

    assert len(buckets) == 1
    merged = buckets[0]
    assert merged["calls"] == 5
    assert merged["errors"] == 1
    assert merged["total_duration_ms"] == 600
    # A maximum cannot be summed.
    assert merged["max_duration_ms"] == 900


def test_buckets_stay_separate_per_agent_and_per_day() -> None:
    call = ToolCallReport(surface=ToolSurface.MCP, server_name="jira", tool_name="create_issue")
    other_agent = uuid4()
    tomorrow = _report(started_at=START + timedelta(days=1), tools=[call])

    buckets = _tool_buckets(
        [
            (_report(tools=[call]), AGENT),
            (_report(tools=[call]), other_agent),
            (tomorrow, AGENT),
        ]
    )

    assert len(buckets) == 3


def test_a_bucket_is_dated_by_when_the_run_started() -> None:
    """So a day's tool calls and a day's runs describe the same population. A run that
    begins before midnight and ends after it counts on the day it began."""
    late = _report(
        started_at=datetime(2026, 9, 14, 23, 40, tzinfo=UTC),
        ended_at=datetime(2026, 9, 15, 0, 20, tzinfo=UTC),
        outcome=RunOutcome.SUCCEEDED,
        tools=[ToolCallReport(surface=ToolSurface.NATIVE, tool_name="web_search")],
    )
    assert _tool_buckets([(late, AGENT)])[0]["day"] == date(2026, 9, 14)


def test_duration_is_computed_here_and_not_taken_from_the_reporter() -> None:
    """A reporter that measured it differently — including its own flush latency —
    would make latency incomparable between one SDK and the next."""
    values = _run_values(
        _report(ended_at=START + timedelta(seconds=2.5), outcome=RunOutcome.SUCCEEDED),
        AGENT,
        {},
        run_id=uuid4(),
    )
    assert values["duration_ms"] == 2500


def test_a_run_still_in_flight_has_no_duration() -> None:
    assert _run_values(_report(), AGENT, {}, run_id=uuid4())["duration_ms"] is None


def test_a_run_without_a_version_is_attributed_to_the_agents_current_one() -> None:
    """A guess, but a much better one than `unknown`: the alternative leaves the
    frameworks panel unable to say what the estate is built on."""
    live = uuid4()
    assert _run_values(_report(), AGENT, {AGENT: live}, run_id=uuid4())["agent_version_id"] == live


def test_a_reported_version_wins_over_the_current_one() -> None:
    reported, live = uuid4(), uuid4()
    values = _run_values(_report(agent_version_id=reported), AGENT, {AGENT: live}, run_id=uuid4())
    assert values["agent_version_id"] == reported


# ---------------------------------------------------------------------------
# Report validation — mirrors the database constraints so a bad report is a 422
# naming the field rather than a 500 out of Postgres.
# ---------------------------------------------------------------------------


def test_a_run_must_name_an_agent() -> None:
    with pytest.raises(ValidationError, match="agent_id or agent_urn"):
        RunReport.model_validate({"started_at": START})


def test_a_finished_run_must_carry_an_end_time() -> None:
    with pytest.raises(ValidationError, match="must carry ended_at"):
        _report(outcome=RunOutcome.SUCCEEDED)


def test_a_run_with_an_end_time_must_report_a_terminal_outcome() -> None:
    with pytest.raises(ValidationError, match="terminal outcome"):
        _report(ended_at=START + timedelta(seconds=1))


def test_a_run_cannot_end_before_it_started() -> None:
    with pytest.raises(ValidationError, match="cannot precede"):
        _report(ended_at=START - timedelta(seconds=1), outcome=RunOutcome.SUCCEEDED)


def test_tool_outcomes_cannot_exceed_the_calls_they_came_from() -> None:
    with pytest.raises(ValidationError, match="cannot exceed calls"):
        ToolCallReport(surface=ToolSurface.NATIVE, tool_name="x", calls=2, errors=2, denied=1)


# ---------------------------------------------------------------------------
# Declaration matching
# ---------------------------------------------------------------------------


def test_an_mcp_url_matches_the_short_name_a_runtime_reports() -> None:
    """The descriptor holds `references.mcp_servers` as URLs; a runtime reports whatever
    the server calls itself. Matching on the exact string alone marked 14 of 17 servers
    on the demo estate as undeclared, all false alarms — which is worse than not
    checking, because it trains people to ignore the column (D-039)."""
    keys = declaration_keys("https://mcp.northwind.internal/stripe")
    assert "stripe" in keys
    assert "mcp.northwind.internal" in keys
    assert "mcp.northwind.internal/stripe" in keys


def test_declaration_matching_ignores_case_and_trailing_slashes() -> None:
    assert "github" in declaration_keys("HTTPS://Mcp.Acme.Com/GitHub/")


def test_a_plain_tool_name_contributes_only_itself() -> None:
    assert declaration_keys("search_claims") == {"search_claims"}


def test_an_empty_declaration_contributes_no_keys() -> None:
    """Otherwise every tool matches the empty string and nothing is ever undeclared."""
    assert declaration_keys("   ") == set()


# ---------------------------------------------------------------------------
# Windows and series
# ---------------------------------------------------------------------------


def test_a_window_of_one_day_starts_at_midnight_today() -> None:
    """Truncated to a day boundary because every series is bucketed by day. A window
    starting mid-afternoon makes the first bucket a partial day that reads as a
    collapse in traffic."""
    start = _window_start(1)
    assert (start.hour, start.minute, start.second) == (0, 0, 0)
    assert start.date() == datetime.now(tz=UTC).date()


def test_a_window_of_thirty_days_includes_today() -> None:
    assert (datetime.now(tz=UTC).date() - _window_start(30).date()).days == 29


def test_environment_totals_sum_each_series() -> None:
    series = ActivitySeries(
        days=[date(2026, 9, 13), date(2026, 9, 14)],
        by_environment={"production": [10, 4], "dev": [1, 0]},
        totals=[11, 4],
        failures=[1, 0],
    )
    assert environment_totals(series) == {"production": 14, "dev": 1}


def test_the_busiest_day_is_the_peak_of_the_totals() -> None:
    series = ActivitySeries(
        days=[date(2026, 9, 12), date(2026, 9, 13), date(2026, 9, 14)],
        totals=[3, 19, 7],
        failures=[0, 2, 1],
    )
    assert busiest_day(series) == (date(2026, 9, 13), 19)


def test_an_empty_window_has_no_busiest_day() -> None:
    assert busiest_day(ActivitySeries()) is None


# ---------------------------------------------------------------------------
# Step ingest and trace arithmetic
# ---------------------------------------------------------------------------


def test_step_duration_is_computed_from_timestamps() -> None:
    end = START + timedelta(milliseconds=850)
    rows = _step_values(
        _report(
            steps=[
                StepReport(
                    seq=0,
                    kind=StepKind.NODE,
                    name="router",
                    started_at=START,
                    ended_at=end,
                    outcome=RunOutcome.SUCCEEDED,
                )
            ]
        ),
        uuid4(),
        AGENT,
    )
    assert rows[0]["duration_ms"] == 850


def test_duplicate_step_keys_in_one_batch_are_collapsed() -> None:
    """Same conflict target twice in one upsert payload — last row wins."""
    end = START + timedelta(seconds=1)
    run_id = uuid4()
    open_step = StepReport(
        seq=0,
        kind=StepKind.NODE,
        name="first",
        started_at=START,
        outcome=RunOutcome.RUNNING,
    )
    closed_step = open_step.model_copy(
        update={"name": "second", "ended_at": end, "outcome": RunOutcome.SUCCEEDED}
    )
    rows = _collapse_step_rows(
        _step_values(_report(steps=[open_step]), run_id, AGENT)
        + _step_values(_report(steps=[closed_step]), run_id, AGENT)
    )
    assert len(rows) == 1
    assert rows[0]["name"] == "second"


def test_a_tool_step_must_carry_a_surface() -> None:
    with pytest.raises(ValidationError, match="surface is required"):
        StepReport(
            seq=0,
            kind=StepKind.TOOL,
            name="search",
            started_at=START,
            ended_at=START + timedelta(seconds=1),
            outcome=RunOutcome.SUCCEEDED,
        )


def test_an_mcp_step_must_name_its_server() -> None:
    with pytest.raises(ValidationError, match="server_name is required"):
        StepReport(
            seq=0,
            kind=StepKind.MCP_TOOL,
            name="query",
            surface=ToolSurface.MCP,
            started_at=START,
            ended_at=START + timedelta(seconds=1),
            outcome=RunOutcome.SUCCEEDED,
        )


def test_duplicate_step_seq_in_one_run_report_is_rejected() -> None:
    end = START + timedelta(seconds=1)
    with pytest.raises(ValidationError, match="duplicate step seq"):
        _report(
            steps=[
                StepReport(
                    seq=1,
                    kind=StepKind.NODE,
                    name="a",
                    started_at=START,
                    ended_at=end,
                    outcome=RunOutcome.SUCCEEDED,
                ),
                StepReport(
                    seq=1,
                    kind=StepKind.NODE,
                    name="b",
                    started_at=START,
                    ended_at=end,
                    outcome=RunOutcome.SUCCEEDED,
                ),
            ]
        )


def _step_row(
    seq: int,
    *,
    parent: int | None,
    duration: int | None,
    kind: StepKind = StepKind.NODE,
) -> StepRow:
    end = None if duration is None else START + timedelta(milliseconds=duration)
    outcome = RunOutcome.RUNNING if duration is None else RunOutcome.SUCCEEDED
    return StepRow(
        id=uuid4(),
        seq=seq,
        parent_seq=parent,
        kind=kind,
        name=f"step-{seq}",
        surface=None,
        server_name="",
        started_at=START,
        ended_at=end,
        duration_ms=duration,
        outcome=outcome,
        attempt=1,
        model=None,
        tokens_in=0,
        tokens_out=0,
        cost_micros=0,
        error_kind=None,
    )


def test_self_time_subtracts_children_in_a_nested_trace() -> None:
    steps = [
        _step_row(0, parent=None, duration=1000),
        _step_row(1, parent=0, duration=400),
        _step_row(2, parent=0, duration=300),
    ]
    self_ms = self_ms_by_seq(steps)
    assert self_ms[0] == 300
    assert self_ms[1] == 400
    assert self_ms[2] == 300


def test_critical_path_follows_the_heavier_concurrent_branch() -> None:
    steps = [
        _step_row(0, parent=None, duration=1000),
        _step_row(1, parent=0, duration=200),
        _step_row(2, parent=0, duration=700),
    ]
    assert critical_path(steps) == [0, 2]


def test_in_flight_steps_are_omitted_from_self_time_as_zero_duration() -> None:
    steps = [
        _step_row(0, parent=None, duration=500),
        _step_row(1, parent=0, duration=None),
    ]
    assert self_ms_by_seq(steps)[0] == 500
