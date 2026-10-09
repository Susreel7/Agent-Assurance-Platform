"""OTLP ExportTraceServiceResponse content negotiation."""

from __future__ import annotations

import json
from typing import cast

from opentelemetry.proto.collector.logs.v1 import logs_service_pb2
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2


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
        return cast(bytes, msg.SerializeToString())
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


def export_logs_response_body(
    *,
    rejected_log_records: int = 0,
    error_message: str = "",
    as_protobuf: bool,
) -> bytes:
    msg = logs_service_pb2.ExportLogsServiceResponse()
    if rejected_log_records:
        msg.partial_success.rejected_log_records = rejected_log_records
        msg.partial_success.error_message = (error_message or "rejected log records")[:512]
    if as_protobuf:
        return cast(bytes, msg.SerializeToString())
    if rejected_log_records:
        return json.dumps(
            {
                "partialSuccess": {
                    "rejectedLogRecords": rejected_log_records,
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
    signal: str = "traces",
) -> tuple[bytes, str, int]:
    if as_protobuf and status_code in (400, 413, 507):
        if signal == "logs":
            body = export_logs_response_body(
                rejected_log_records=0, error_message=message, as_protobuf=True
            )
        else:
            body = export_response_body(rejected_spans=0, error_message=message, as_protobuf=True)
        return body, "application/x-protobuf", status_code
    payload = {"code": code, "message": message[:512]}
    return json.dumps(payload).encode("utf-8"), "application/json", status_code
