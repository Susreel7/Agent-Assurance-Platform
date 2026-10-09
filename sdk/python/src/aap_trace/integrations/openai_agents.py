"""OpenAI Agents SDK tracing processor.

The adapter intentionally maps public SDK trace data only. It never inspects private
model reasoning fields.
"""

from __future__ import annotations

from typing import Any

from aap_trace.capture import apply_capture
from aap_trace.client import get_client
from aap_trace.integrations._optional import require_package
from aap_trace.spans import ManagedSpan, start_managed_span


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _data(span: Any) -> tuple[str, Any]:
    span_data = _value(span, "span_data", {})
    exported = span_data.export() if hasattr(span_data, "export") else span_data
    kind = type(span_data).__name__.removesuffix("SpanData").lower()
    if kind in {"dict", ""}:
        kind = str(_value(exported, "type", "custom")).lower()
    return kind, exported


class AAPOpenAIAgentsProcessor:
    """Maps OpenAI Agents SDK trace callbacks to typed Observe spans."""

    def __init__(self) -> None:
        self._traces: dict[str, ManagedSpan] = {}
        self._spans: dict[str, ManagedSpan] = {}

    def on_trace_start(self, trace: Any) -> None:
        trace_id = str(_value(trace, "trace_id"))
        name = str(_value(trace, "name", "OpenAI Agent"))
        self._traces[trace_id] = start_managed_span(
            name,
            **{
                "gen_ai.operation.name": "invoke_agent",
                "aap.observation.type": "agent",
                "aap.execution.type": "agent",
                "aap.execution.id": trace_id,
                "aap.framework.name": "openai-agents",
                "aap.framework.trace_id": trace_id,
                "gen_ai.agent.name": name,
                "gen_ai.conversation.id": _value(trace, "group_id"),
            },
        )

    def on_trace_end(self, trace: Any) -> None:
        managed = self._traces.pop(str(_value(trace, "trace_id")), None)
        if managed is not None:
            managed.finish()

    def on_span_start(self, span: Any) -> None:
        span_id = str(_value(span, "span_id"))
        trace_id = str(_value(span, "trace_id"))
        parent_id = _value(span, "parent_id")
        kind, data = _data(span)
        parent = self._spans.get(str(parent_id)) if parent_id else self._traces.get(trace_id)
        observation_type, operation = {
            "agent": ("agent", "invoke_agent"),
            "function": ("tool", "execute_tool"),
            "generation": ("generation", "chat"),
            "response": ("generation", "chat"),
            "handoff": ("a2a", "handoff"),
            "guardrail": ("guardrail", "guardrail"),
        }.get(kind, ("sdk", "execute_sdk"))
        name = (
            _value(data, "name")
            or _value(data, "model")
            or _value(data, "to_agent")
            or f"openai-agents:{kind}"
        )
        attrs: dict[str, Any] = {
            "gen_ai.operation.name": operation,
            "aap.observation.type": observation_type,
            "aap.framework.name": "openai-agents",
            "aap.framework.span_id": span_id,
            "aap.framework.parent_span_id": str(parent_id) if parent_id else None,
            "gen_ai.request.model": _value(data, "model"),
            "gen_ai.tool.name": _value(data, "name") if kind == "function" else None,
            "gen_ai.handoff.target": _value(data, "to_agent"),
        }
        mode = get_client().config.capture_mode
        if kind in {"function", "generation", "response"}:
            field = "gen_ai.tool.call.arguments" if kind == "function" else "gen_ai.input.messages"
            attrs.update(apply_capture(mode, field, _value(data, "input")) or {})
        self._spans[span_id] = start_managed_span(
            str(name),
            parent_span=parent.span if parent is not None else None,
            **attrs,
        )

    def on_span_end(self, span: Any) -> None:
        managed = self._spans.pop(str(_value(span, "span_id")), None)
        if managed is None:
            return
        kind, data = _data(span)
        mode = get_client().config.capture_mode
        output_field = "gen_ai.tool.call.result" if kind == "function" else "gen_ai.output.messages"
        output = _value(data, "output")
        for key, value in (apply_capture(mode, output_field, output) or {}).items():
            managed.span.set_attribute(key, str(value))
        usage = _value(data, "usage")
        input_tokens = _value(usage, "input_tokens")
        output_tokens = _value(usage, "output_tokens")
        if input_tokens is not None:
            managed.span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
        if output_tokens is not None:
            managed.span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
        error = _value(span, "error")
        if error:
            managed.finish(RuntimeError(str(error)))
        else:
            managed.finish()

    def shutdown(self) -> None:
        for managed in [*self._spans.values(), *self._traces.values()]:
            managed.finish(RuntimeError("OpenAI Agents trace processor shutdown"))
        self._spans.clear()
        self._traces.clear()

    def force_flush(self) -> None:
        try:
            get_client().flush()
        except RuntimeError:
            return


def instrument_openai_agents() -> AAPOpenAIAgentsProcessor:
    """Register and return the processor with an installed OpenAI Agents SDK."""
    agents = require_package("agents", "openai-agents")
    processor = AAPOpenAIAgentsProcessor()
    add_processor = getattr(agents, "add_trace_processor", None)
    if add_processor is None:
        tracing = require_package("agents.tracing", "openai-agents")
        add_processor = tracing.add_trace_processor
    add_processor(processor)
    return processor
