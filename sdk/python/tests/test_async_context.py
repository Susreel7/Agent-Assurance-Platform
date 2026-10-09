from __future__ import annotations

import asyncio

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from aap_trace.context import current_span_context
from aap_trace.spans import trace_span, traced


@pytest.mark.asyncio
async def test_async_tasks_isolate_context(
    configured_client, memory_exporter: InMemorySpanExporter
) -> None:
    results: list[str | None] = []

    async def worker(label: str) -> None:
        with trace_span(label):
            await asyncio.sleep(0.01)
            ctx = current_span_context()
            results.append(ctx.trace_id if ctx else None)

    await asyncio.gather(worker("a"), worker("b"))
    trace.get_tracer_provider().force_flush()
    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 2
    assert results[0] != results[1]


@pytest.mark.asyncio
async def test_traced_async_decorator(configured_client) -> None:
    @traced("async_fn")
    async def async_fn() -> int:
        return 42

    assert await async_fn() == 42
