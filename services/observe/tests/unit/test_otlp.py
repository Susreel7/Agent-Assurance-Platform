from __future__ import annotations

import json

from google.protobuf import json_format
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2

from observe.ingest import otlp


def _sample_request() -> trace_service_pb2.ExportTraceServiceRequest:
    req = trace_service_pb2.ExportTraceServiceRequest()
    rs = req.resource_spans.add()
    attr = rs.resource.attributes.add()
    attr.key = "service.name"
    attr.value.string_value = "demo"
    ss = rs.scope_spans.add()
    span = ss.spans.add()
    span.trace_id = bytes.fromhex("0102030405060708090a0b0c0d0e0f10")
    span.span_id = bytes.fromhex("0102030405060708")
    span.name = "chat"
    span.start_time_unix_nano = 1_000_000_000
    span.end_time_unix_nano = 2_000_000_000
    op = span.attributes.add()
    op.key = "gen_ai.operation.name"
    op.value.string_value = "chat"
    agent = span.attributes.add()
    agent.key = "gen_ai.agent.id"
    agent.value.string_value = "agent-1"
    return req


def test_parse_protobuf_and_extract_spans() -> None:
    req = _sample_request()
    body = req.SerializeToString()
    parsed = otlp.parse_export_request(body, "application/x-protobuf")
    spans, rejected = otlp.spans_from_request(parsed)
    assert rejected == 0
    assert len(spans) == 1
    assert spans[0].trace_id == "0102030405060708090a0b0c0d0e0f10"
    assert spans[0].attributes["gen_ai.operation.name"] == "chat"


def test_parse_json_export_request() -> None:
    req = _sample_request()
    body = json_format.MessageToJson(req).encode("utf-8")
    parsed = otlp.parse_export_request(body, "application/json")
    spans, _ = otlp.spans_from_request(parsed)
    assert len(spans) == 1


def test_parse_standard_otlp_json_hex_ids() -> None:
    body = json.dumps(
        {
            "resourceSpans": [
                {
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": "01" * 16,
                                    "spanId": "02" * 8,
                                    "name": "chat",
                                    "startTimeUnixNano": "1",
                                    "endTimeUnixNano": "2",
                                }
                            ]
                        }
                    ]
                }
            ]
        }
    ).encode()
    parsed = otlp.parse_export_request(body, "application/json")
    spans, rejected = otlp.spans_from_request(parsed)
    assert rejected == 0
    assert spans[0].trace_id == "01" * 16
    assert spans[0].span_id == "02" * 8


def test_partial_success_shape() -> None:
    resp = otlp.export_response(rejected_spans=2, error_message="bad spans")
    assert resp["partialSuccess"]["rejectedSpans"] == 2
