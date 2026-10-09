from __future__ import annotations

import pytest
from opentelemetry import trace

from aap_trace.client import TraceClient, shutdown
from aap_trace.config import TraceConfig
from aap_trace.context import inject_headers
from aap_trace.spans import trace_span


def test_disabled_no_export() -> None:
    shutdown()
    config = TraceConfig(
        endpoint="",
        bearer_token="",
        organization_id="o",
        project_id="p",
        enabled=False,
    )
    client = TraceClient(config)
    with trace_span("noop"):
        pass
    assert client.flush() is True
    inject_headers({})
    assert trace.get_tracer_provider() is not None
    client.shutdown()


def test_sample_rate_is_bounded() -> None:
    with pytest.raises(ValueError, match="sample_rate"):
        TraceConfig(
            endpoint="",
            bearer_token="",
            organization_id="o",
            project_id="p",
            sample_rate=1.01,
        )
