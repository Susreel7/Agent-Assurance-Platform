"""OTLP parse, capture transform, and span accounting."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable
from typing import Any, cast

from google.protobuf import json_format
from opentelemetry.proto.collector.logs.v1 import logs_service_pb2
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2
from opentelemetry.proto.common.v1 import common_pb2
from opentelemetry.proto.logs.v1 import logs_pb2

from collector.capture import CONTENT_ATTR_KEYS, apply_capture
from collector.config import CaptureMode, Settings
from collector.errors import InvalidEnvelopeError
from collector.sampling import SamplingPolicy


def _convert_hex_id_fields(item: dict[str, Any], names: tuple[str, ...], hex_length: int) -> None:
    for name in names:
        value = item.get(name)
        if (
            isinstance(value, str)
            and len(value) == hex_length
            and all(ch in "0123456789abcdefABCDEF" for ch in value)
        ):
            item[name] = base64.b64encode(bytes.fromhex(value)).decode()


def _protobuf_json_traces_with_base64_ids(body: bytes) -> str:
    """Translate OTLP/JSON hex IDs to protobuf JSON's bytes representation."""
    document = json.loads(body)
    resources = document.get("resourceSpans", document.get("resource_spans", []))
    for resource in resources:
        scopes = resource.get("scopeSpans", resource.get("scope_spans", []))
        for scope in scopes:
            for span in scope.get("spans", []):
                _convert_hex_id_fields(span, ("traceId", "trace_id"), 32)
                _convert_hex_id_fields(span, ("spanId", "span_id"), 16)
                _convert_hex_id_fields(span, ("parentSpanId", "parent_span_id"), 16)
                for link in span.get("links", []):
                    _convert_hex_id_fields(link, ("traceId", "trace_id"), 32)
                    _convert_hex_id_fields(link, ("spanId", "span_id"), 16)
    return json.dumps(document)


def _protobuf_json_logs_with_base64_ids(body: bytes) -> str:
    document = json.loads(body)
    resources = document.get("resourceLogs", document.get("resource_logs", []))
    for resource in resources:
        scopes = resource.get("scopeLogs", resource.get("scope_logs", []))
        for scope in scopes:
            for record in scope.get("logRecords", scope.get("log_records", [])):
                _convert_hex_id_fields(record, ("traceId", "trace_id"), 32)
                _convert_hex_id_fields(record, ("spanId", "span_id"), 16)
    return json.dumps(document)


def parse_export_request(
    body: bytes, content_type: str
) -> trace_service_pb2.ExportTraceServiceRequest:
    req = trace_service_pb2.ExportTraceServiceRequest()
    ct = content_type.split(";")[0].strip().lower()
    try:
        if ct == "application/json":
            json_format.Parse(_protobuf_json_traces_with_base64_ids(body), req)
        elif ct in ("application/x-protobuf", "application/protobuf"):
            req.ParseFromString(body)
        else:
            raise InvalidEnvelopeError(f"unsupported content type: {content_type}")
    except InvalidEnvelopeError:
        raise
    except Exception as exc:
        raise InvalidEnvelopeError("failed to parse ExportTraceServiceRequest") from exc
    return req


def _any_value_to_python(v: common_pb2.AnyValue) -> Any:
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
        return [_any_value_to_python(x) for x in v.array_value.values]
    if kind == "kvlist_value":
        return {kv.key: _any_value_to_python(kv.value) for kv in v.kvlist_value.values}
    return None


def _python_to_any_value(value: Any) -> common_pb2.AnyValue:
    av = common_pb2.AnyValue()
    if isinstance(value, bool):
        av.bool_value = value
    elif isinstance(value, int):
        av.int_value = value
    elif isinstance(value, float):
        av.double_value = value
    elif isinstance(value, (bytes, bytearray)):
        av.bytes_value = bytes(value)
    elif isinstance(value, str):
        av.string_value = value
    elif isinstance(value, list):
        for item in value:
            av.array_value.values.append(_python_to_any_value(item))
    elif isinstance(value, dict):
        for key, item in value.items():
            kv = av.kvlist_value.values.add()
            kv.key = str(key)
            kv.value.CopyFrom(_python_to_any_value(item))
    else:
        av.string_value = json.dumps(value, default=str)
    return av


def _rewrite_attributes(
    attrs: Any,
    mode: CaptureMode,
    settings: Settings,
) -> None:
    original = list(attrs)
    del attrs[:]
    for kv in original:
        if kv.key not in CONTENT_ATTR_KEYS:
            attrs.append(kv)
            continue
        value = _any_value_to_python(kv.value)
        replacement = apply_capture(mode, kv.key, value, settings)
        if replacement is None:
            continue
        for new_key, new_val in replacement.items():
            new_kv = common_pb2.KeyValue()
            new_kv.key = new_key
            new_kv.value.CopyFrom(_python_to_any_value(new_val))
            attrs.append(new_kv)


def apply_capture_to_request(
    req: trace_service_pb2.ExportTraceServiceRequest, settings: Settings
) -> None:
    mode = settings.capture_mode
    for rs in req.resource_spans:
        for ss in rs.scope_spans:
            for span in ss.spans:
                _rewrite_attributes(span.attributes, mode, settings)
                for event in span.events:
                    _rewrite_attributes(event.attributes, mode, settings)


def trace_scope(
    req: trace_service_pb2.ExportTraceServiceRequest,
) -> tuple[str | None, str | None]:
    for resource_spans in req.resource_spans:
        attrs = resource_spans.resource.attributes
        organization_id = _attribute_string(attrs, "aap.organization.id") or _attribute_string(
            attrs, "aap.organization_id"
        )
        project_id = _attribute_string(attrs, "aap.project.id") or _attribute_string(
            attrs, "aap.project_id"
        )
        if organization_id or project_id:
            return organization_id, project_id
    return None, None


def _attribute_number(attrs: Any, key: str) -> float | None:
    for kv in attrs:
        if kv.key != key:
            continue
        value = _any_value_to_python(kv.value)
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


def _head_sampled(trace_id: bytes, rate: float) -> bool:
    if rate >= 1:
        return True
    if rate <= 0:
        return False
    digest = hashlib.sha256(trace_id).digest()
    return int.from_bytes(digest[:8], "big") / 2**64 < rate


def apply_trace_sampling(
    req: trace_service_pb2.ExportTraceServiceRequest,
    policy: SamplingPolicy,
    rate_allow: Callable[[bytes], bool] | None = None,
) -> int:
    """Apply deterministic head sampling with batch-local tail preservation.

    The root span normally ends last, so standard batch processors send the failure,
    retry, or high-latency signal with the final trace batch. Collectors fail open when
    policy is unavailable; sampling must never break the observed application.
    """

    spans_by_trace: dict[bytes, list[Any]] = {}
    for resource_spans in req.resource_spans:
        for scope_spans in resource_spans.scope_spans:
            for span in scope_spans.spans:
                spans_by_trace.setdefault(bytes(span.trace_id), []).append(span)

    decisions: dict[bytes, bool] = {}
    threshold_nano = int(policy.high_latency_ms * 1_000_000)
    for trace_id, spans in spans_by_trace.items():
        has_error = any(span.status.code == 2 for span in spans)
        has_retry = any(
            (_attribute_number(span.attributes, "aap.retry.attempt") or 0) > 0
            or (_attribute_number(span.attributes, "aap.node.iteration") or 0) > 1
            for span in spans
        )
        has_high_latency = any(
            span.end_time_unix_nano > span.start_time_unix_nano
            and span.end_time_unix_nano - span.start_time_unix_nano >= threshold_nano
            for span in spans
        )
        preserve = (
            (policy.tail_keep_errors and has_error)
            or (policy.tail_keep_retries and has_retry)
            or (policy.tail_keep_high_latency and has_high_latency)
        )
        within_limit = rate_allow(trace_id) if rate_allow is not None else True
        decisions[trace_id] = preserve or (
            within_limit and _head_sampled(trace_id, policy.head_sample_rate)
        )

    dropped = 0
    for resource_spans in req.resource_spans:
        for scope_spans in resource_spans.scope_spans:
            kept = [span for span in scope_spans.spans if decisions.get(bytes(span.trace_id), True)]
            dropped += len(scope_spans.spans) - len(kept)
            del scope_spans.spans[:]
            scope_spans.spans.extend(kept)
    return dropped


LIFECYCLE_EVENT_ATTR = "aap.event.type"
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


def _attribute_string(attrs: Any, key: str) -> str | None:
    for kv in attrs:
        if kv.key != key:
            continue
        value = _any_value_to_python(kv.value)
        if isinstance(value, str):
            return value
    return None


def _rewrite_log_body(record: logs_pb2.LogRecord, mode: CaptureMode, settings: Settings) -> None:
    kind = record.body.WhichOneof("value")
    if kind is None:
        return
    raw = _any_value_to_python(record.body)
    replacement = apply_capture(mode, "log.body", raw, settings)
    record.body.Clear()
    if replacement is None:
        return
    for new_key, new_val in replacement.items():
        new_kv = record.attributes.add()
        new_kv.key = new_key
        new_kv.value.CopyFrom(_python_to_any_value(new_val))


def apply_capture_to_logs_request(
    req: logs_service_pb2.ExportLogsServiceRequest, settings: Settings
) -> None:
    mode = settings.capture_mode
    for rl in req.resource_logs:
        for sl in rl.scope_logs:
            for record in sl.log_records:
                _rewrite_attributes(record.attributes, mode, settings)
                _rewrite_log_body(record, mode, settings)


def _log_record_lifecycle_valid(record: logs_pb2.LogRecord) -> bool:
    if not record.time_unix_nano:
        return False
    event_type = _attribute_string(record.attributes, LIFECYCLE_EVENT_ATTR)
    if event_type is None:
        return True
    if not record.trace_id:
        return False
    if event_type in EXECUTION_LEVEL_LIFECYCLE_EVENTS:
        return True
    return bool(record.span_id)


def drop_invalid_log_records(req: logs_service_pb2.ExportLogsServiceRequest) -> None:
    for rl in req.resource_logs:
        for sl in rl.scope_logs:
            valid = [record for record in sl.log_records if _log_record_lifecycle_valid(record)]
            del sl.log_records[:]
            sl.log_records.extend(valid)


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


def count_log_records(req: logs_service_pb2.ExportLogsServiceRequest) -> tuple[int, int]:
    """Returns (valid_log_count, rejected_log_count)."""
    valid = 0
    rejected = 0
    for rl in req.resource_logs:
        for sl in rl.scope_logs:
            for record in sl.log_records:
                if _log_record_lifecycle_valid(record):
                    valid += 1
                else:
                    rejected += 1
    return valid, rejected


def serialize_logs_request(
    req: logs_service_pb2.ExportLogsServiceRequest,
    *,
    as_protobuf: bool,
) -> bytes:
    if as_protobuf:
        return cast(bytes, req.SerializeToString())
    return cast(
        bytes,
        json_format.MessageToJson(req, preserving_proto_field_name=True).encode("utf-8"),
    )


def count_spans(req: trace_service_pb2.ExportTraceServiceRequest) -> tuple[int, int]:
    """Returns (valid_span_count, rejected_span_count)."""
    valid = 0
    rejected = 0
    for rs in req.resource_spans:
        for ss in rs.scope_spans:
            for span in ss.spans:
                if not span.trace_id or not span.span_id:
                    rejected += 1
                else:
                    valid += 1
    return valid, rejected


def drop_invalid_spans(req: trace_service_pb2.ExportTraceServiceRequest) -> None:
    for rs in req.resource_spans:
        for ss in rs.scope_spans:
            valid = [span for span in ss.spans if span.trace_id and span.span_id]
            del ss.spans[:]
            ss.spans.extend(valid)


def serialize_request(
    req: trace_service_pb2.ExportTraceServiceRequest,
    *,
    as_protobuf: bool,
) -> bytes:
    if as_protobuf:
        return cast(bytes, req.SerializeToString())
    return cast(
        bytes,
        json_format.MessageToJson(req, preserving_proto_field_name=True).encode("utf-8"),
    )


def envelope_media_type(as_protobuf: bool) -> str:
    return "application/x-protobuf" if as_protobuf else "application/json"


def digest_bytes(data: bytes) -> str:
    import hashlib

    return "sha256:" + hashlib.sha256(data).hexdigest()


def build_minimal_json_log_request(
    *,
    trace_id: bytes | None = None,
    span_id: bytes | None = None,
    body: str = "hello",
    attributes: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "timeUnixNano": "1",
        "body": {"stringValue": body},
    }
    if trace_id is not None:
        record["traceId"] = base64.b64encode(trace_id).decode()
    if span_id is not None:
        record["spanId"] = base64.b64encode(span_id).decode()
    if attributes:
        record["attributes"] = attributes
    return {
        "resourceLogs": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": "svc"}}]
                },
                "scopeLogs": [{"scope": {"name": "test"}, "logRecords": [record]}],
            }
        ]
    }


def build_minimal_json_request(
    *, trace_id: bytes, span_id: bytes, name: str = "test"
) -> dict[str, Any]:
    return {
        "resourceSpans": [
            {
                "resource": {
                    "attributes": [{"key": "service.name", "value": {"stringValue": "svc"}}]
                },
                "scopeSpans": [
                    {
                        "scope": {"name": "test"},
                        "spans": [
                            {
                                "traceId": base64.b64encode(trace_id).decode(),
                                "spanId": base64.b64encode(span_id).decode(),
                                "name": name,
                                "startTimeUnixNano": "1",
                                "endTimeUnixNano": "2",
                            }
                        ],
                    }
                ],
            }
        ]
    }
