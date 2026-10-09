from __future__ import annotations

from observe.ingest.responses import export_response_body, prefers_protobuf


def test_prefers_protobuf_from_content_type() -> None:
    assert prefers_protobuf("application/x-protobuf", None) is True
    assert prefers_protobuf("application/json", None) is False


def test_export_response_json_empty() -> None:
    body = export_response_body(as_protobuf=False)
    assert body == b"{}"


def test_export_response_protobuf_partial() -> None:
    from opentelemetry.proto.collector.trace.v1 import trace_service_pb2

    body = export_response_body(rejected_spans=3, error_message="bad", as_protobuf=True)
    msg = trace_service_pb2.ExportTraceServiceResponse()
    msg.ParseFromString(body)
    assert msg.partial_success.rejected_spans == 3
