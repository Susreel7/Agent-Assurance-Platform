"""Streaming helpers: TTFT and token accumulation on spans."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from typing import Any, TypeVar

from opentelemetry.trace import Span

T = TypeVar("T")


@dataclass
class StreamMetrics:
    first_token_ms: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    chunks: int = 0
    cancelled: bool = False

    def apply_to_span(self, span: Span) -> None:
        if self.first_token_ms is not None:
            span.set_attribute("gen_ai.response.time_to_first_token_ms", self.first_token_ms)
        if self.input_tokens:
            span.set_attribute("gen_ai.usage.input_tokens", self.input_tokens)
        if self.output_tokens:
            span.set_attribute("gen_ai.usage.output_tokens", self.output_tokens)
        span.set_attribute("gen_ai.response.streaming_chunks", self.chunks)
        if self.cancelled:
            span.add_event("gen_ai.streaming.cancelled")


@dataclass
class _StreamState:
    started: float = field(default_factory=time.perf_counter)
    metrics: StreamMetrics = field(default_factory=StreamMetrics)


def wrap_sync_stream(
    span: Span,
    stream: Iterator[T],
    *,
    count_output_tokens: bool = False,
    token_counter: Any | None = None,
) -> Iterator[T]:
    state = _StreamState()
    try:
        for chunk in stream:
            if state.metrics.first_token_ms is None:
                state.metrics.first_token_ms = (time.perf_counter() - state.started) * 1000
            state.metrics.chunks += 1
            if count_output_tokens and token_counter is not None:
                state.metrics.output_tokens += int(token_counter(chunk))
            yield chunk
    except GeneratorExit:
        state.metrics.cancelled = True
        raise
    finally:
        state.metrics.apply_to_span(span)


async def wrap_async_stream(
    span: Span,
    stream: AsyncIterator[T],
    *,
    count_output_tokens: bool = False,
    token_counter: Any | None = None,
) -> AsyncIterator[T]:
    state = _StreamState()
    try:
        async for chunk in stream:
            if state.metrics.first_token_ms is None:
                state.metrics.first_token_ms = (time.perf_counter() - state.started) * 1000
            state.metrics.chunks += 1
            if count_output_tokens and token_counter is not None:
                state.metrics.output_tokens += int(token_counter(chunk))
            yield chunk
    except (GeneratorExit, asyncio.CancelledError):
        state.metrics.cancelled = True
        raise
    finally:
        state.metrics.apply_to_span(span)
