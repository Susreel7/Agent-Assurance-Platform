from __future__ import annotations

from dataclasses import replace

from observe.ingest.otlp import RawSpan
from observe.worker import normalizer


def test_genai_chat_maps_to_inference() -> None:
    span = RawSpan(
        trace_id="t" * 32,
        span_id="s" * 16,
        parent_span_id=None,
        name="chat",
        start_time_unix_nano=0,
        end_time_unix_nano=1_000_000,
        status_code="ok",
        attributes={"gen_ai.operation.name": "chat", "gen_ai.request.model": "gpt-4"},
        resource_attributes={"service.name": "svc"},
        events=[],
    )
    ns = normalizer.normalize_span(span)
    assert ns.kind == "inference"
    assert ns.observation_type == "generation"
    assert ns.source_convention == "otel_genai_1.37"
    assert ns.model == "gpt-4"


def test_langgraph_node_maps_to_node_observation() -> None:
    span = RawSpan(
        trace_id="t" * 32,
        span_id="s" * 16,
        parent_span_id=None,
        name="node_run",
        start_time_unix_nano=0,
        end_time_unix_nano=1,
        status_code="ok",
        attributes={"langgraph.node": "research"},
        resource_attributes={},
        events=[],
    )
    ns = normalizer.normalize_span(span)
    assert ns.observation_type == "node"


def test_user_id_and_enduser_fallback() -> None:
    span = RawSpan(
        trace_id="t" * 32,
        span_id="s" * 16,
        parent_span_id=None,
        name="run",
        start_time_unix_nano=0,
        end_time_unix_nano=1,
        status_code="ok",
        attributes={
            "aap.execution.id": "exec-abc",
            "aap.user.session_id": "sess-1",
            "enduser.id": "fallback-user",
        },
        resource_attributes={},
        events=[],
    )
    ns = normalizer.normalize_span(span)
    assert ns.execution_id == "exec-abc"
    assert ns.user_session_id == "sess-1"
    assert ns.initiating_user_id == "fallback-user"

    explicit = RawSpan(
        trace_id=span.trace_id,
        span_id="x" * 16,
        parent_span_id=None,
        name="run",
        start_time_unix_nano=0,
        end_time_unix_nano=1,
        status_code="ok",
        attributes={"aap.user.id": "primary-user", "enduser.id": "fallback-user"},
        resource_attributes={},
        events=[],
    )
    ns2 = normalizer.normalize_span(explicit)
    assert ns2.initiating_user_id == "primary-user"


def test_explicit_observation_type_taxonomy() -> None:
    span = RawSpan(
        trace_id="t" * 32,
        span_id="s" * 16,
        parent_span_id=None,
        name="guard",
        start_time_unix_nano=0,
        end_time_unix_nano=1,
        status_code="ok",
        attributes={"aap.observation.type": "guardrail"},
        resource_attributes={},
        events=[],
    )
    assert normalizer.normalize_span(span).observation_type == "guardrail"


def test_mcp_and_a2a_correlation_attributes_are_preserved() -> None:
    span = RawSpan(
        trace_id="t" * 32,
        span_id="s" * 16,
        parent_span_id=None,
        name="mcp:github:tools/call",
        start_time_unix_nano=0,
        end_time_unix_nano=1,
        status_code="ok",
        attributes={
            "aap.observation.type": "mcp",
            "aap.mcp.server": "github",
            "aap.mcp.method": "tools/call",
            "aap.mcp.role": "server",
            "aap.mcp.request_id": "mcp-1",
            "aap.a2a.target_agent_id": "coding-agent",
            "aap.a2a.target_execution_id": "exec-child",
            "aap.a2a.target_trace_id": "f" * 32,
        },
        resource_attributes={},
        events=[],
    )
    normalized = normalizer.normalize_span(span)
    assert normalized.mcp_role == "server"
    assert normalized.mcp_request_id == "mcp-1"
    assert normalized.a2a_target_agent_id == "coding-agent"
    assert normalized.a2a_target_execution_id == "exec-child"
    assert normalized.a2a_target_trace_id == "f" * 32


def test_unknown_operation_retained() -> None:
    span = RawSpan(
        trace_id="t" * 32,
        span_id="s" * 16,
        parent_span_id=None,
        name="weird",
        start_time_unix_nano=0,
        end_time_unix_nano=0,
        status_code="unset",
        attributes={"gen_ai.operation.name": "custom_future_op"},
        resource_attributes={},
        events=[],
    )
    ns = normalizer.normalize_span(span)
    assert ns.kind == "unknown"


def test_span_event_preserves_typed_attributes_from_parsed_otlp() -> None:
    span = RawSpan(
        trace_id="t" * 32,
        span_id="s" * 16,
        parent_span_id=None,
        name="coding",
        start_time_unix_nano=1,
        end_time_unix_nano=2,
        status_code="ok",
        attributes={"aap.execution.id": "exec-1"},
        resource_attributes={},
        events=[],
    )

    event = normalizer.normalize_span_otlp_event(
        span,
        {
            "name": "state.transition",
            "time_unix_nano": 2,
            "attributes": {
                "aap.event.type": "state.transition",
                "aap.observation.type": "state_transition",
                "aap.state.to": "coding",
                "aap.observation.sequence": 4,
            },
        },
    )

    assert event.execution_id == "exec-1"
    assert event.event_type == "state.transition"
    assert event.observation_type == "state_transition"
    assert event.sequence == 4
    assert event.attributes["aap.state.to"] == "coding"


def _minimal_span(
    *, trace_id: str, span_id: str, parent_span_id: str | None
) -> normalizer.NormalizedSpan:
    return normalizer.NormalizedSpan(
        trace_id=trace_id,
        span_id=span_id,
        parent_span_id=parent_span_id,
        execution_id=None,
        parent_execution_id=None,
        execution_type=None,
        session_id=None,
        user_session_id=None,
        environment_id=None,
        service_name=None,
        agent_id=None,
        agent_name=None,
        agent_version_id=None,
        kind="unknown",
        observation_type="unknown",
        operation_name=span_id[0],
        source_convention="unknown",
        mapping_revision=1,
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
        initiating_user_id=None,
        effective_actor_id=None,
        effective_actor_type=None,
        start_time_unix_nano=0,
        end_time_unix_nano=1,
        duration_ms=0,
        input_tokens=0,
        output_tokens=0,
        cost_micros=0,
        clock_skew_flag=False,
        is_terminal=True,
        tags=[],
        search_text="",
        content_fingerprint="sha256:abc",
        payload_fields={},
    )


def test_cycle_detection() -> None:
    trace_id = "t" * 32
    a = _minimal_span(trace_id=trace_id, span_id="a" * 16, parent_span_id="b" * 16)
    b = replace(
        _minimal_span(trace_id=trace_id, span_id="b" * 16, parent_span_id="a" * 16),
        operation_name="b",
        content_fingerprint="sha256:def",
    )
    malformed, has_cycle, _root = normalizer.detect_graph_flags([a, b])
    assert has_cycle is True
    assert malformed is True
