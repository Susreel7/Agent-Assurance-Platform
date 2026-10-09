from __future__ import annotations

from observe.worker import execution_reducer, normalizer


def test_out_of_order_lifecycle_then_terminal_span() -> None:
    trace_id = "t" * 32
    spans = [
        normalizer.NormalizedSpan(
            trace_id=trace_id,
            span_id="s" * 16,
            parent_span_id=None,
            execution_id="exec-1",
            parent_execution_id=None,
            execution_type="agent",
            session_id=None,
            user_session_id=None,
            environment_id=None,
            service_name=None,
            agent_id="agent-1",
            agent_name=None,
            agent_version_id=None,
            kind="agent",
            observation_type="agent",
            operation_name="run",
            source_convention="unknown",
            mapping_revision=2,
            status_code="ok",
            outcome="success",
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
            initiating_user_id="user-1",
            effective_actor_id="user-1",
            effective_actor_type="user",
            start_time_unix_nano=2_000_000_000,
            end_time_unix_nano=3_000_000_000,
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
    ]
    events = [
        normalizer.NormalizedLogEvent(
            trace_id=trace_id,
            span_id=None,
            log_record_uid="u1",
            execution_id="exec-1",
            event_type="execution.started",
            observation_type="event",
            event_time_unix_nano=1_000_000_000,
            status="info",
            initiating_user_id="user-1",
            effective_actor_id="user-1",
            agent_id="agent-1",
            model=None,
            tool_name=None,
            sdk_name=None,
            sdk_operation=None,
            mcp_server=None,
            mcp_method=None,
            sequence=1,
            attributes={},
            content_fingerprint="y",
        )
    ]
    agg = execution_reducer.reduce_execution(
        trace_id=trace_id,
        spans=spans,
        events=events,
        malformed=False,
        has_cycle=False,
        root_span_id="s" * 16,
        capture_level="digest",
    )
    assert agg.status == "succeeded"
    assert agg.has_late_data is False
    assert execution_reducer.is_terminal_execution(agg)


def _event(event_type: str, *, execution_id: str = "exec-event") -> normalizer.NormalizedLogEvent:
    return normalizer.NormalizedLogEvent(
        trace_id="t" * 32,
        span_id="s" * 16,
        log_record_uid=f"uid:{event_type}",
        execution_id=execution_id,
        event_type=event_type,
        observation_type="event",
        event_time_unix_nano=1_000_000_000,
        status="info",
        initiating_user_id="user-1",
        effective_actor_id="user-1",
        agent_id="agent-1",
        model=None,
        tool_name=None,
        sdk_name=None,
        sdk_operation=None,
        mcp_server=None,
        mcp_method=None,
        sequence=1,
        attributes={},
        content_fingerprint="event",
    )


def test_child_observation_completion_does_not_close_execution() -> None:
    aggregate = execution_reducer.reduce_execution(
        trace_id="t" * 32,
        spans=[],
        events=[_event("observation.completed")],
        malformed=False,
        has_cycle=False,
        root_span_id=None,
        capture_level="digest",
    )

    assert aggregate.execution_id == "exec-event"
    assert aggregate.is_live is True
    assert aggregate.status == "open"


def test_execution_failure_event_closes_log_only_execution() -> None:
    aggregate = execution_reducer.reduce_execution(
        trace_id="t" * 32,
        spans=[],
        events=[_event("execution.failed")],
        malformed=False,
        has_cycle=False,
        root_span_id=None,
        capture_level="digest",
    )

    assert aggregate.execution_id == "exec-event"
    assert aggregate.is_live is False
    assert aggregate.status == "failed"
