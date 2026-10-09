"""OTLP ExportTraceServiceResponse content negotiation."""

from __future__ import annotations

import json
from typing import Any

from opentelemetry.proto.collector.logs.v1 import logs_service_pb2
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2

from observe.errors import InvalidEnvelopeError


def prefers_protobuf(content_type: str | None, accept: str | None) -> bool:
    acc = (accept or "").lower()
    if "application/x-protobuf" in acc or "application/protobuf" in acc:
        return True
    if "application/json" in acc:
        return False
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in ("application/x-protobuf", "application/protobuf"):
        return True
    if ct == "application/json":
        return False
    return True


def export_response_body(
    *,
    rejected_spans: int = 0,
    error_message: str = "",
    as_protobuf: bool,
) -> bytes:
    msg = trace_service_pb2.ExportTraceServiceResponse()
    if rejected_spans:
        msg.partial_success.rejected_spans = rejected_spans
        msg.partial_success.error_message = (error_message or "rejected spans")[:512]
    if as_protobuf:
        out: bytes = msg.SerializeToString()
        return out
    if rejected_spans:
        return json.dumps(
            {
                "partialSuccess": {
                    "rejectedSpans": rejected_spans,
                    "errorMessage": msg.partial_success.error_message,
                }
            }
        ).encode("utf-8")
    return b"{}"


def parse_accept_export(content_type: str) -> bool:
    ct = content_type.split(";")[0].strip().lower()
    if ct not in ("application/json", "application/x-protobuf", "application/protobuf"):
        raise InvalidEnvelopeError(f"unsupported response content type: {content_type}")
    return ct != "application/json"


def export_logs_response_body(
    *,
    rejected_records: int = 0,
    error_message: str = "",
    as_protobuf: bool,
) -> bytes:
    msg = logs_service_pb2.ExportLogsServiceResponse()
    if rejected_records:
        msg.partial_success.rejected_log_records = rejected_records
        msg.partial_success.error_message = (error_message or "rejected records")[:512]
    if as_protobuf:
        out: bytes = msg.SerializeToString()
        return out
    if rejected_records:
        return json.dumps(
            {
                "partialSuccess": {
                    "rejectedLogRecords": rejected_records,
                    "errorMessage": msg.partial_success.error_message,
                }
            }
        ).encode("utf-8")
    return b"{}"


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    as_protobuf: bool,
) -> tuple[bytes, str, int]:
    if as_protobuf and status_code in (400, 413):
        body = export_response_body(
            rejected_spans=0,
            error_message=message,
            as_protobuf=True,
        )
        return body, "application/x-protobuf", status_code
    payload: dict[str, Any] = {"code": code, "message": message[:512]}
    return json.dumps(payload).encode("utf-8"), "application/json", status_code
