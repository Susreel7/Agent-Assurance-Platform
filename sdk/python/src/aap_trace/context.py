"""W3C trace context helpers and span identity accessors."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, MutableMapping
from contextvars import ContextVar, Token
from dataclasses import dataclass
from itertools import count
from threading import Lock
from typing import Any

from opentelemetry import context as otel_context
from opentelemetry import propagate, trace
from opentelemetry.trace import Span, StatusCode


@dataclass(frozen=True, slots=True)
class SpanContext:
    trace_id: str
    span_id: str
    trace_flags: int

    @classmethod
    def from_span(cls, span: Span) -> SpanContext | None:
        ctx = span.get_span_context()
        if not ctx.is_valid:
            return None
        return cls(
            trace_id=format(ctx.trace_id, "032x"),
            span_id=format(ctx.span_id, "016x"),
            trace_flags=ctx.trace_flags,
        )


@dataclass(slots=True)
class ExecutionContext:
    execution_id: str
    _sequence: Iterator[int]
    _lock: Lock

    @classmethod
    def create(cls, execution_id: str) -> ExecutionContext:
        return cls(execution_id=execution_id, _sequence=count(1), _lock=Lock())

    def next_sequence(self) -> int:
        with self._lock:
            return next(self._sequence)


_execution_context: ContextVar[ExecutionContext | None] = ContextVar(
    "aap_execution_context",
    default=None,
)


def current_execution_context() -> ExecutionContext | None:
    return _execution_context.get()


def attach_execution(execution_id: str) -> Token[ExecutionContext | None]:
    return _execution_context.set(ExecutionContext.create(execution_id))


def detach_execution(token: Token[ExecutionContext | None]) -> None:
    _execution_context.reset(token)


def current_span_context() -> SpanContext | None:
    span = trace.get_current_span()
    if span is None:
        return None
    return SpanContext.from_span(span)


def inject_headers(carrier: MutableMapping[str, str]) -> None:
    propagate.inject(carrier)


def extract_headers(carrier: Mapping[str, str]) -> otel_context.Context:
    return propagate.extract(carrier)


def inject_mcp_context(
    message: MutableMapping[str, Any],
    *,
    metadata_key: str = "_meta",
) -> None:
    """Inject W3C context into an MCP JSON-RPC metadata object."""

    carrier: dict[str, str] = {}
    inject_headers(carrier)
    metadata = message.get(metadata_key)
    if not isinstance(metadata, MutableMapping):
        metadata = {}
        message[metadata_key] = metadata
    for key in ("traceparent", "tracestate", "baggage"):
        if key in carrier:
            metadata[key] = carrier[key]


def extract_mcp_context(
    message: Mapping[str, Any],
    *,
    metadata_key: str = "_meta",
) -> otel_context.Context:
    metadata = message.get(metadata_key)
    if not isinstance(metadata, Mapping):
        return extract_headers({})
    carrier = {
        key: value
        for key, value in metadata.items()
        if key in {"traceparent", "tracestate", "baggage"} and isinstance(value, str)
    }
    return extract_headers(carrier)


def set_span_error(span: Span, exc: BaseException) -> None:
    span.record_exception(exc)
    span.set_status(StatusCode.ERROR, type(exc).__name__)
