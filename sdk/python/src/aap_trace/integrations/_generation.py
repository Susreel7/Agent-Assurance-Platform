"""Vendor-shaped generation metadata without private reasoning capture."""

from __future__ import annotations

import json
from typing import Any

from opentelemetry.trace import Span

from aap_trace.capture import CaptureMode, apply_capture

_REQUEST_PARAMETERS = (
    "temperature",
    "top_p",
    "max_tokens",
    "max_completion_tokens",
    "frequency_penalty",
    "presence_penalty",
    "seed",
    "service_tier",
)


def request_attributes(kwargs: dict[str, Any]) -> dict[str, Any]:
    attrs: dict[str, Any] = {}
    for name in _REQUEST_PARAMETERS:
        value = kwargs.get(name)
        if value is not None:
            attrs[f"gen_ai.request.{name}"] = value
    tools = kwargs.get("tools")
    if tools is not None:
        attrs["gen_ai.request.tool_count"] = len(tools) if isinstance(tools, list) else 1
    return attrs


def _value(obj: Any, name: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _set(span: Span, name: str, value: Any) -> None:
    if value is not None:
        span.set_attribute(name, value)


def _capture_output(span: Span, mode: CaptureMode, value: Any) -> None:
    captured = apply_capture(mode, "gen_ai.output.messages", value) or {}
    for name, item in captured.items():
        span.set_attribute(
            name,
            item
            if isinstance(item, (str, bool, int, float))
            else json.dumps(item, default=str, separators=(",", ":"), sort_keys=True),
        )


def apply_openai_response(span: Span, response: Any, mode: CaptureMode) -> None:
    _set(span, "gen_ai.response.id", _value(response, "id"))
    _set(span, "gen_ai.response.model", _value(response, "model"))
    choices = _value(response, "choices", []) or []
    outputs: list[Any] = []
    finish_reasons: list[str] = []
    for choice in choices:
        finish_reason = _value(choice, "finish_reason")
        if finish_reason:
            finish_reasons.append(str(finish_reason))
        message = _value(choice, "message")
        if message is not None:
            outputs.append(
                {
                    "role": _value(message, "role", "assistant"),
                    "content": _value(message, "content"),
                    "tool_calls": _value(message, "tool_calls"),
                }
            )
    if finish_reasons:
        span.set_attribute("gen_ai.response.finish_reasons", finish_reasons)
    if outputs:
        _capture_output(span, mode, outputs)
    usage = _value(response, "usage")
    if usage is not None:
        _set(
            span,
            "gen_ai.usage.input_tokens",
            _value(usage, "prompt_tokens", _value(usage, "input_tokens")),
        )
        _set(
            span,
            "gen_ai.usage.output_tokens",
            _value(usage, "completion_tokens", _value(usage, "output_tokens")),
        )
        prompt_details = _value(usage, "prompt_tokens_details")
        completion_details = _value(usage, "completion_tokens_details")
        _set(span, "gen_ai.usage.cached_input_tokens", _value(prompt_details, "cached_tokens"))
        _set(
            span,
            "gen_ai.usage.reasoning_tokens",
            _value(completion_details, "reasoning_tokens"),
        )


def apply_anthropic_response(span: Span, response: Any, mode: CaptureMode) -> None:
    _set(span, "gen_ai.response.id", _value(response, "id"))
    _set(span, "gen_ai.response.model", _value(response, "model"))
    stop_reason = _value(response, "stop_reason")
    if stop_reason:
        span.set_attribute("gen_ai.response.finish_reasons", [str(stop_reason)])
    content = _value(response, "content")
    if content is not None:
        # Store provider output blocks, but deliberately omit any private/internal
        # reasoning fields. Explicit provider token counts remain metadata.
        visible: list[Any] = []
        for block in content if isinstance(content, list) else [content]:
            block_type = _value(block, "type")
            if block_type in {"text", "tool_use"}:
                visible.append(
                    {
                        "type": block_type,
                        "text": _value(block, "text"),
                        "name": _value(block, "name"),
                        "input": _value(block, "input"),
                    }
                )
        if visible:
            _capture_output(span, mode, visible)
    usage = _value(response, "usage")
    if usage is not None:
        _set(span, "gen_ai.usage.input_tokens", _value(usage, "input_tokens"))
        _set(span, "gen_ai.usage.output_tokens", _value(usage, "output_tokens"))
        _set(span, "gen_ai.usage.cached_input_tokens", _value(usage, "cache_read_input_tokens"))


class OpenAIStreamAccumulator:
    def __init__(self) -> None:
        self._text: list[str] = []
        self._tool_calls: dict[int, dict[str, str]] = {}

    def consume(self, span: Span, chunk: Any) -> None:
        apply_openai_response(span, chunk, CaptureMode.NONE)
        for choice in _value(chunk, "choices", []) or []:
            delta = _value(choice, "delta")
            content = _value(delta, "content")
            if isinstance(content, str):
                self._text.append(content)
            for tool_call in _value(delta, "tool_calls", []) or []:
                index = int(_value(tool_call, "index", 0))
                current = self._tool_calls.setdefault(
                    index, {"id": "", "name": "", "arguments": ""}
                )
                current["id"] += str(_value(tool_call, "id", "") or "")
                function = _value(tool_call, "function")
                current["name"] += str(_value(function, "name", "") or "")
                current["arguments"] += str(_value(function, "arguments", "") or "")

    def finish(self, span: Span, mode: CaptureMode) -> None:
        output: dict[str, Any] = {"role": "assistant", "content": "".join(self._text)}
        if self._tool_calls:
            output["tool_calls"] = list(self._tool_calls.values())
        _capture_output(span, mode, [output])


class AnthropicStreamAccumulator:
    def __init__(self) -> None:
        self._text: list[str] = []

    def consume(self, span: Span, event: Any) -> None:
        message = _value(event, "message")
        if message is not None:
            apply_anthropic_response(span, message, CaptureMode.NONE)
        delta = _value(event, "delta")
        text = _value(delta, "text")
        if isinstance(text, str):
            self._text.append(text)
        stop_reason = _value(delta, "stop_reason")
        if stop_reason:
            span.set_attribute("gen_ai.response.finish_reasons", [str(stop_reason)])
        usage = _value(event, "usage", _value(delta, "usage"))
        if usage is not None:
            _set(span, "gen_ai.usage.output_tokens", _value(usage, "output_tokens"))

    def finish(self, span: Span, mode: CaptureMode) -> None:
        if self._text:
            _capture_output(span, mode, [{"type": "text", "text": "".join(self._text)}])
