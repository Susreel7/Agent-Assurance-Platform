from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from aap_trace.context import current_span_context
from aap_trace.spans import generation_span, tool_span, trace_span


def test_parent_child_nesting(configured_client, memory_exporter: InMemorySpanExporter) -> None:
    with trace_span("root"):
        parent = current_span_context()
        assert parent is not None
        with tool_span(name="search", arguments={"q": "hello"}):
            child = current_span_context()
            assert child is not None
            assert child.trace_id == parent.trace_id
            assert child.span_id != parent.span_id

    trace.get_tracer_provider().force_flush()
    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 2
    by_name = {s.name: s for s in spans}
    tool = by_name["tool:search"]
    root = by_name["root"]
    assert tool.parent is not None
    assert tool.parent.span_id == root.context.span_id


def test_generation_span_attrs(configured_client, memory_exporter: InMemorySpanExporter) -> None:
    with generation_span(
        provider="openai", model="gpt-4o", input_messages=[{"role": "user", "content": "hi"}]
    ):
        pass
    trace.get_tracer_provider().force_flush()
    spans = memory_exporter.get_finished_spans()
    assert spans[0].attributes["gen_ai.request.model"] == "gpt-4o"
