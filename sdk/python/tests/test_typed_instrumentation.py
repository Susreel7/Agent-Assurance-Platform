from __future__ import annotations

from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from aap_trace import (
    a2a_span,
    cursor_sdk_span,
    database_span,
    http_span,
    mcp_span,
    observe_agent,
    observe_tool,
    record_sdk_result,
)


def test_sdk_http_and_database_are_typed_and_safe(
    configured_client: Any,
    memory_exporter: InMemorySpanExporter,
) -> None:
    with cursor_sdk_span("apply_patch", arguments={"token": "must-not-be-stored"}) as span:
        record_sdk_result(span, {"files": 2}, response_id="sdk-response")
    with http_span(
        method="GET",
        url="https://user:password@example.test/private/api-key?token=secret",
        route="/repos/{repo_id}",
    ):
        pass
    with database_span(
        system="postgresql",
        operation="SELECT",
        namespace="observe",
        statement="SELECT secret FROM credentials",
    ):
        pass
    trace.get_tracer_provider().force_flush()
    by_type = {
        span.attributes["aap.observation.type"]: span
        for span in memory_exporter.get_finished_spans()
    }
    sdk = by_type["sdk"]
    assert sdk.attributes["aap.sdk.operation"] == "apply_patch"
    assert sdk.attributes["aap.response.id"] == "sdk-response"
    http = by_type["http"]
    assert http.attributes["server.address"] == "example.test"
    assert http.attributes["http.route"] == "/repos/{repo_id}"
    assert "password" not in str(http.attributes)
    assert "token=secret" not in str(http.attributes)
    database = by_type["database"]
    assert database.attributes["db.system.name"] == "postgresql"
    assert "SELECT secret" not in str(database.attributes)


def test_typed_decorators_preserve_parentage(
    configured_client: Any,
    memory_exporter: InMemorySpanExporter,
) -> None:
    @observe_tool("filesystem.write")
    def write() -> None:
        return None

    @observe_agent("remediation")
    def run() -> None:
        write()

    run()
    trace.get_tracer_provider().force_flush()
    spans = {span.name: span for span in memory_exporter.get_finished_spans()}
    assert spans["tool:filesystem.write"].parent is not None
    assert spans["tool:filesystem.write"].parent.span_id == spans["remediation"].context.span_id


def test_mcp_and_a2a_are_first_class_observations(
    configured_client: Any,
    memory_exporter: InMemorySpanExporter,
) -> None:
    with mcp_span(
        server="github",
        method="tools/call",
        role="client",
        request_id="mcp-1",
        arguments={"authorization": "must-not-be-stored"},
    ):
        pass
    with a2a_span(
        target_agent_id="coding-agent",
        target_execution_id="exec-child",
        target_trace_id="f" * 32,
    ):
        pass
    trace.get_tracer_provider().force_flush()
    by_type = {
        span.attributes["aap.observation.type"]: span
        for span in memory_exporter.get_finished_spans()
    }
    mcp = by_type["mcp"]
    assert mcp.attributes["aap.mcp.role"] == "client"
    assert mcp.attributes["aap.mcp.request_id"] == "mcp-1"
    assert "must-not-be-stored" not in str(mcp.attributes)
    a2a = by_type["a2a"]
    assert a2a.attributes["aap.a2a.target_agent_id"] == "coding-agent"
    assert a2a.attributes["aap.a2a.target_execution_id"] == "exec-child"
