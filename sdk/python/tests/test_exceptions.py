from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from aap_trace.spans import tool_span


def test_exception_sets_error_status(
    configured_client, memory_exporter: InMemorySpanExporter
) -> None:
    with pytest.raises(ValueError):
        with tool_span(name="fail"):
            raise ValueError("boom")
    trace.get_tracer_provider().force_flush()
    span = memory_exporter.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.ERROR
