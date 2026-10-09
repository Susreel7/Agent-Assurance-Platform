from __future__ import annotations

from opentelemetry import trace

from aap_trace.context import (
    extract_headers,
    extract_mcp_context,
    inject_headers,
    inject_mcp_context,
)
from aap_trace.spans import trace_span


def test_w3c_inject_extract_roundtrip(configured_client) -> None:
    carrier: dict[str, str] = {}
    with trace_span("http"):
        inject_headers(carrier)
    assert "traceparent" in carrier
    ctx = extract_headers(carrier)
    assert ctx is not None


def test_mcp_json_rpc_context_roundtrip(configured_client) -> None:
    message: dict[str, object] = {"jsonrpc": "2.0", "id": "request-1"}
    with trace_span("mcp-client"):
        expected = trace.get_current_span().get_span_context()
        inject_mcp_context(message)
    metadata = message["_meta"]
    assert isinstance(metadata, dict)
    assert str(metadata["traceparent"]).startswith("00-")
    extracted = trace.get_current_span(extract_mcp_context(message)).get_span_context()
    assert extracted.trace_id == expected.trace_id
    assert extracted.span_id == expected.span_id
