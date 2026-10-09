from __future__ import annotations

from unittest.mock import MagicMock, patch

from aap_trace.client import TraceClient, _normalize_traces_endpoint
from aap_trace.config import TraceConfig


def test_normalize_endpoint() -> None:
    assert _normalize_traces_endpoint("https://x") == "https://x/v1/traces"
    assert _normalize_traces_endpoint("https://x/v1/traces") == "https://x/v1/traces"


def test_bearer_header_on_exporter() -> None:
    config = TraceConfig(
        endpoint="https://observe.example",
        bearer_token="aap_wk_org.1.secret",
        organization_id="o",
        project_id="p",
        enabled=True,
    )
    with patch("aap_trace.client.OTLPSpanExporter") as exporter_cls:
        exporter_cls.return_value = MagicMock()
        TraceClient(config)
        _, kwargs = exporter_cls.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer aap_wk_org.1.secret"


def test_retry_via_batch_processor() -> None:
    """BatchSpanProcessor delegates retry to OTLP exporter (stdlib)."""
    config = TraceConfig(
        endpoint="https://observe.example/v1/traces",
        bearer_token="token",
        organization_id="o",
        project_id="p",
        enabled=True,
    )
    client = TraceClient(config)
    assert client._processor is not None
    client.shutdown()
