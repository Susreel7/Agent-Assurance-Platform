from __future__ import annotations

from dataclasses import replace

from observe.worker import execution_reducer, normalizer, processor


def _agent_span(*, outcome: str, span_id: str, parent: str | None) -> normalizer.NormalizedSpan:
    return normalizer.NormalizedSpan(
        trace_id="t" * 32,
        span_id=span_id,
        parent_span_id=parent,
        execution_id="exec-1",
        parent_execution_id=None,
        execution_type="agent",
        session_id=None,
        user_session_id=None,
        environment_id=None,
        service_name=None,
        agent_id="a1",
        agent_name=None,
        agent_version_id=None,
        kind="agent",
        observation_type="agent",
        operation_name="run",
        source_convention="unknown",
        mapping_revision=2,
        status_code="ok",
        outcome=outcome,
        model=None,
        tool_name=None,
        provider=None,
        sdk_name=None,
        sdk_version=None,
        sdk_operation=None,
        mcp_server=None,
        mcp_method=None,
        retry_attempt=0,
        graph_node_id=None,
        graph_node_path=None,
        initiating_user_id=None,
        effective_actor_id=None,
        effective_actor_type=None,
        start_time_unix_nano=1_000_000_000,
        end_time_unix_nano=2_000_000_000,
        duration_ms=1.0,
        input_tokens=0,
        output_tokens=0,
        cost_micros=0,
        clock_skew_flag=False,
        is_terminal=True,
        tags=[],
        search_text="",
        content_fingerprint="x",
        payload_fields={},
    )


def test_root_success_wins_over_failed_child() -> None:
    root = _agent_span(outcome="success", span_id="r" * 16, parent=None)
    child = _agent_span(outcome="error", span_id="c" * 16, parent="r" * 16)
    agg = execution_reducer.reduce_execution(
        trace_id=root.trace_id,
        spans=[root, child],
        events=[],
        malformed=False,
        has_cycle=False,
        root_span_id="r" * 16,
        capture_level="digest",
    )
    assert agg.status == "succeeded"


def test_retry_count_uses_attempts_beyond_first() -> None:
    retry_span = replace(
        _agent_span(outcome="success", span_id="a" * 16, parent=None),
        observation_type="tool",
        retry_attempt=3,
    )
    agg = execution_reducer.reduce_execution(
        trace_id=retry_span.trace_id,
        spans=[retry_span],
        events=[],
        malformed=False,
        has_cycle=False,
        root_span_id="a" * 16,
        capture_level="digest",
    )
    assert agg.retry_count == 2


def test_live_lifecycle_distinguishes_execution_and_observation_states() -> None:
    root = _agent_span(outcome="success", span_id="r" * 16, parent=None)
    assert processor._span_lifecycle_event(replace(root, is_terminal=False)) == "execution.started"
    assert processor._span_lifecycle_event(root) == "execution.completed"
    assert processor._span_lifecycle_event(replace(root, outcome="error")) == "execution.failed"

    child = replace(
        root,
        span_id="c" * 16,
        parent_span_id=root.span_id,
        observation_type="tool",
    )
    assert (
        processor._span_lifecycle_event(replace(child, is_terminal=False)) == "observation.started"
    )
    assert processor._span_lifecycle_event(child) == "observation.completed"


def test_direct_sdk_activity_and_replay_lineage_are_preserved() -> None:
    sdk = replace(
        _agent_span(outcome="success", span_id="d" * 16, parent=None),
        execution_type=None,
        observation_type="sdk",
        kind="unknown",
        agent_id=None,
        parent_execution_id="parent-execution",
        parent_trace_id="p" * 32,
        replay_of_execution_id="original-execution",
        invocation_source="cli",
        application_name="cursor",
        client_name="desktop",
        request_id="request-1",
    )
    agg = execution_reducer.reduce_execution(
        trace_id=sdk.trace_id,
        spans=[sdk],
        events=[],
        malformed=False,
        has_cycle=False,
        root_span_id=sdk.span_id,
        capture_level="digest",
    )
    assert agg.execution_type == "user_activity"
    assert agg.parent_execution_id == "parent-execution"
    assert agg.parent_trace_id == "p" * 32
    assert agg.replay_of_execution_id == "original-execution"
    assert agg.invocation_source == "cli"
    row = processor._aggregate_pg_row(agg)
    assert row["parent_execution_id"] == "parent-execution"
    assert row["parent_trace_id"] == "p" * 32
