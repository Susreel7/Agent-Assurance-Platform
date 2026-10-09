"""OTLP ExportTraceServiceRequest parsing and span extraction."""

from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from google.protobuf import json_format
from opentelemetry.proto.collector.logs.v1 import logs_service_pb2
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2

from observe.errors import InvalidEnvelopeError


@dataclass(frozen=True, slots=True)
class RawSpan:
    trace_id: str
    span_id: str
    parent_span_id: str | None
    name: str
    start_time_unix_nano: int
    end_time_unix_nano: int
    status_code: str
    attributes: dict[str, Any]
    resource_attributes: dict[str, Any]
    events: list[dict[str, Any]]


def _hex_id(raw: bytes) -> str:
    return raw.hex()


def _protobuf_json_with_base64_ids(body: bytes) -> str:
    """Translate OTLP/JSON hex IDs to protobuf JSON's bytes representation."""
    document = json.loads(body)

    def convert(item: dict[str, Any], names: tuple[str, ...], hex_length: int) -> None:
        for name in names:
            value = item.get(name)
            if (
                isinstance(value, str)
                and len(value) == hex_length
                and all(ch in "0123456789abcdefABCDEF" for ch in value)
            ):
                item[name] = base64.b64encode(bytes.fromhex(value)).decode()

    resources = document.get("resourceSpans", document.get("resource_spans", []))
    for resource in resources:
        scopes = resource.get("scopeSpans", resource.get("scope_spans", []))
        for scope in scopes:
            for span in scope.get("spans", []):
                convert(span, ("traceId", "trace_id"), 32)
                convert(span, ("spanId", "span_id"), 16)
                convert(span, ("parentSpanId", "parent_span_id"), 16)
                for link in span.get("links", []):
                    convert(link, ("traceId", "trace_id"), 32)
                    convert(link, ("spanId", "span_id"), 16)
    return json.dumps(document)


def _attr_map(attrs: list[Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for item in attrs:
        key = item.get("key") if isinstance(item, dict) else getattr(item, "key", None)
        if not key:
            continue
        value = item.get("value") if isinstance(item, dict) else item.value
        out[key] = _any_value(value)
    return out


def _any_value(v: Any) -> Any:
    if isinstance(v, dict):
        if "stringValue" in v:
            return v["stringValue"]
        if "intValue" in v:
            return int(v["intValue"])
        if "doubleValue" in v:
            return float(v["doubleValue"])
        if "boolValue" in v:
            return bool(v["boolValue"])
        if "arrayValue" in v:
            return [_any_value(x) for x in v["arrayValue"].get("values", [])]
        if "bytesValue" in v:
            raw = v["bytesValue"]
            if isinstance(raw, str):
                return base64.b64decode(raw)
            return raw
        return v
    # protobuf AnyValue
    if hasattr(v, "WhichOneof"):
        kind = v.WhichOneof("value")
        if kind == "string_value":
            return v.string_value
        if kind == "int_value":
            return v.int_value
        if kind == "double_value":
            return v.double_value
        if kind == "bool_value":
            return v.bool_value
        if kind == "bytes_value":
            return v.bytes_value
        if kind == "array_value":
            return [_any_value(x) for x in v.array_value.values]
    return None


def parse_export_request(
    body: bytes, content_type: str
) -> trace_service_pb2.ExportTraceServiceRequest:
    req = trace_service_pb2.ExportTraceServiceRequest()
    ct = content_type.split(";")[0].strip().lower()
    try:
        if ct == "application/json":
            json_format.Parse(_protobuf_json_with_base64_ids(body), req)
        elif ct in ("application/x-protobuf", "application/protobuf"):
            req.ParseFromString(body)
        else:
            raise InvalidEnvelopeError(f"unsupported content type: {content_type}")
    except InvalidEnvelopeError:
        raise
    except Exception as exc:
        raise InvalidEnvelopeError("failed to parse ExportTraceServiceRequest") from exc
    return req


def spans_from_request(
    req: trace_service_pb2.ExportTraceServiceRequest,
) -> tuple[list[RawSpan], int]:
    """Returns (valid_spans, rejected_count)."""
    valid: list[RawSpan] = []
    rejected = 0
    for rs in req.resource_spans:
        resource_attrs = _attr_map(list(rs.resource.attributes))
        for ss in rs.scope_spans:
            for span in ss.spans:
                try:
                    if not span.trace_id or not span.span_id:
                        rejected += 1
                        continue
                    parent = _hex_id(span.parent_span_id) if span.parent_span_id else None
                    if parent == "0000000000000000":
                        parent = None
                    status = "unset"
                    if span.status.code == 1:
                        status = "ok"
                    elif span.status.code == 2:
                        status = "error"
                    events = []
                    for ev in span.events:
                        events.append(
                            {
                                "name": ev.name,
                                "time_unix_nano": ev.time_unix_nano,
                                "attributes": _attr_map(list(ev.attributes)),
                            }
                        )
                    valid.append(
                        RawSpan(
                            trace_id=_hex_id(span.trace_id),
                            span_id=_hex_id(span.span_id),
                            parent_span_id=parent,
                            name=span.name,
                            start_time_unix_nano=span.start_time_unix_nano,
                            end_time_unix_nano=span.end_time_unix_nano,
                            status_code=status,
                            attributes=_attr_map(list(span.attributes)),
                            resource_attributes=resource_attrs,
                            events=events,
                        )
                    )
                except Exception:  # noqa: BLE001 — per-span rejection
                    rejected += 1
    return valid, rejected


def spans_from_json_dict(data: dict[str, Any]) -> tuple[list[RawSpan], int]:
    req = trace_service_pb2.ExportTraceServiceRequest()
    json_format.Parse(json.dumps(data), req)
    return spans_from_request(req)


def partial_success_response(*, rejected_spans: int, error_message: str) -> dict[str, Any]:
    return {
        "partialSuccess": {
            "rejectedSpans": rejected_spans,
            "errorMessage": error_message[:512],
        }
    }


def export_response(*, rejected_spans: int = 0, error_message: str = "") -> dict[str, Any]:
    if rejected_spans:
        return partial_success_response(
            rejected_spans=rejected_spans, error_message=error_message or "rejected spans"
        )
    return {}


@dataclass(frozen=True, slots=True)
class RawLogRecord:
    trace_id: str
    span_id: str | None
    time_unix_nano: int
    event_name: str | None
    body: str | None
    attributes: dict[str, Any]
    resource_attributes: dict[str, Any]
    log_record_uid: str


EXECUTION_LEVEL_LIFECYCLE_EVENTS = frozenset(
    {
        "execution.started",
        "execution.completed",
        "execution.failed",
        "execution.timed_out",
        "execution.cancelled",
        "execution.refused",
    }
)


def _log_record_valid(record: Any) -> bool:
    if not record.time_unix_nano:
        return False
    attrs = _attr_map(list(record.attributes))
    event_type = attrs.get("aap.event.type")
    if not event_type:
        return True
    if not record.trace_id:
        return False
    if event_type not in EXECUTION_LEVEL_LIFECYCLE_EVENTS:
        return bool(record.span_id)
    return True


def drop_invalid_log_records(req: logs_service_pb2.ExportLogsServiceRequest) -> None:
    for rl in req.resource_logs:
        for sl in rl.scope_logs:
            valid = [record for record in sl.log_records if _log_record_valid(record)]
            del sl.log_records[:]
            sl.log_records.extend(valid)


def drop_invalid_spans(req: trace_service_pb2.ExportTraceServiceRequest) -> None:
    for rs in req.resource_spans:
        for ss in rs.scope_spans:
            valid = [span for span in ss.spans if span.trace_id and span.span_id]
            del ss.spans[:]
            ss.spans.extend(valid)


def _protobuf_json_logs_with_base64_ids(body: bytes) -> str:
    document = json.loads(body)

    def convert(item: dict[str, Any], names: tuple[str, ...], hex_length: int) -> None:
        for name in names:
            value = item.get(name)
            if (
                isinstance(value, str)
                and len(value) == hex_length
                and all(ch in "0123456789abcdefABCDEF" for ch in value)
            ):
                item[name] = base64.b64encode(bytes.fromhex(value)).decode()

    resources = document.get("resourceLogs", document.get("resource_logs", []))
    for resource in resources:
        scopes = resource.get("scopeLogs", resource.get("scope_logs", []))
        for scope in scopes:
            for record in scope.get("logRecords", scope.get("log_records", [])):
                convert(record, ("traceId", "trace_id"), 32)
                convert(record, ("spanId", "span_id"), 16)
    return json.dumps(document)


def parse_logs_export_request(
    body: bytes, content_type: str
) -> logs_service_pb2.ExportLogsServiceRequest:
    req = logs_service_pb2.ExportLogsServiceRequest()
    ct = content_type.split(";")[0].strip().lower()
    try:
        if ct == "application/json":
            json_format.Parse(_protobuf_json_logs_with_base64_ids(body), req)
        elif ct in ("application/x-protobuf", "application/protobuf"):
            req.ParseFromString(body)
        else:
            raise InvalidEnvelopeError(f"unsupported content type: {content_type}")
    except InvalidEnvelopeError:
        raise
    except Exception as exc:
        raise InvalidEnvelopeError("failed to parse ExportLogsServiceRequest") from exc
    return req


def logs_from_request(
    req: logs_service_pb2.ExportLogsServiceRequest,
) -> tuple[list[RawLogRecord], int]:
    valid: list[RawLogRecord] = []
    rejected = 0
    for rl in req.resource_logs:
        resource_attrs = _attr_map(list(rl.resource.attributes))
        for sl in rl.scope_logs:
            for record in sl.log_records:
                try:
                    if not _log_record_valid(record):
                        rejected += 1
                        continue
                    trace_id = _hex_id(record.trace_id)
                    span_id = _hex_id(record.span_id) if record.span_id else None
                    body_text: str | None = None
                    if record.body.WhichOneof("value") == "string_value":
                        body_text = record.body.string_value
                    attrs = _attr_map(list(record.attributes))
                    identity = json.dumps(
                        {
                            "trace_id": trace_id,
                            "span_id": span_id,
                            "time_unix_nano": record.time_unix_nano,
                            "event_name": record.event_name or None,
                            "body": body_text,
                            "attributes": attrs,
                        },
                        default=str,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    uid = "sha256:" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
                    valid.append(
                        RawLogRecord(
                            trace_id=trace_id,
                            span_id=span_id,
                            time_unix_nano=record.time_unix_nano,
                            event_name=record.event_name or None,
                            body=body_text,
                            attributes=attrs,
                            resource_attributes=resource_attrs,
                            log_record_uid=uid,
                        )
                    )
                except Exception:  # noqa: BLE001
                    rejected += 1
    return valid, rejected


def partial_success_logs_response(*, rejected_records: int, error_message: str) -> dict[str, Any]:
    return {
        "partialSuccess": {
            "rejectedLogRecords": rejected_records,
            "errorMessage": error_message[:512],
        }
    }


def export_logs_response(*, rejected_records: int = 0, error_message: str = "") -> dict[str, Any]:
    if rejected_records:
        return partial_success_logs_response(
            rejected_records=rejected_records, error_message=error_message or "rejected records"
        )
    return {}
