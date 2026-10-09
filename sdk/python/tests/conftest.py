"""Shared fixtures using in-memory span export."""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from aap_trace.capture import CaptureMode
from aap_trace.client import TraceClient, configure, shutdown
from aap_trace.config import TraceConfig


def install_test_tracer_provider(exporter: InMemorySpanExporter) -> TracerProvider:
    """Install a tracer provider for unit tests (OTel global singleton bypass)."""
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace._TRACER_PROVIDER = provider  # type: ignore[attr-defined]
    return provider


@pytest.fixture
def memory_exporter() -> InMemorySpanExporter:
    return InMemorySpanExporter()


@pytest.fixture
def trace_config() -> TraceConfig:
    return TraceConfig(
        endpoint="https://observe.example/v1/traces",
        bearer_token="aap_wk_test.token.secret",
        organization_id="org-1",
        project_id="proj-1",
        agent_id="agent-1",
        session_id="sess-1",
        enabled=False,
        capture_mode=CaptureMode.DIGEST,
    )


@pytest.fixture
def configured_client(
    trace_config: TraceConfig, memory_exporter: InMemorySpanExporter
) -> TraceClient:
    shutdown()
    install_test_tracer_provider(memory_exporter)
    client = configure(trace_config)
    yield client
    shutdown()
    memory_exporter.clear()
