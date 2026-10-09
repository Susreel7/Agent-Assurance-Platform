from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from aap_trace.integrations.openai_agents import AAPOpenAIAgentsProcessor


@dataclass
class FunctionSpanData:
    name: str
    input: Any
    output: Any = None


@dataclass
class GenerationSpanData:
    model: str
    input: Any
    output: Any = None
    usage: Any = None


@dataclass
class FixtureSpan:
    span_id: str
    trace_id: str
    parent_id: str | None
    span_data: Any
    error: Any = None


def test_openai_agents_processor_preserves_typed_hierarchy(
    configured_client: Any,
    memory_exporter: InMemorySpanExporter,
) -> None:
    processor = AAPOpenAIAgentsProcessor()
    trace_fixture = {
        "trace_id": "agent-execution-1",
        "name": "Remediation Agent",
        "group_id": "session-1",
    }
    processor.on_trace_start(trace_fixture)
    generation = FixtureSpan(
        "generation-1",
        "agent-execution-1",
        None,
        GenerationSpanData(
            "gpt-test",
            [{"role": "user", "content": "fix"}],
            [{"role": "assistant", "content": "patch"}],
            {"input_tokens": 2, "output_tokens": 3},
        ),
    )
    tool = FixtureSpan(
        "tool-1",
        "agent-execution-1",
        "generation-1",
        FunctionSpanData("apply_patch", {"path": "safe.py"}, {"updated": True}),
    )
    processor.on_span_start(generation)
    processor.on_span_start(tool)
    processor.on_span_end(tool)
    processor.on_span_end(generation)
    processor.on_trace_end(trace_fixture)
    trace.get_tracer_provider().force_flush()

    spans = {span.name: span for span in memory_exporter.get_finished_spans()}
    assert spans["apply_patch"].attributes["aap.observation.type"] == "tool"
    assert spans["gpt-test"].attributes["aap.observation.type"] == "generation"
    assert spans["apply_patch"].parent is not None
    assert spans["apply_patch"].parent.span_id == spans["gpt-test"].context.span_id
    assert spans["gpt-test"].parent is not None
    assert spans["gpt-test"].parent.span_id == spans["Remediation Agent"].context.span_id
