from __future__ import annotations

import base64
import gzip
import json

from google.protobuf import json_format
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2

from collector.config import CaptureMode, Settings
from collector.otlp import (
    LIFECYCLE_EVENT_ATTR,
    apply_capture_to_logs_request,
    apply_capture_to_request,
    apply_trace_sampling,
    build_minimal_json_log_request,
    build_minimal_json_request,
    count_log_records,
    count_spans,
    parse_export_request,
    parse_logs_export_request,
    serialize_logs_request,
    serialize_request,
)
from collector.sampling import SamplingPolicy


def _trace_bytes(hex_id: str) -> bytes:
    return bytes.fromhex(hex_id)


def test_json_and_protobuf_parse() -> None:
    payload = build_minimal_json_request(
        trace_id=_trace_bytes("a" * 32), span_id=_trace_bytes("b" * 16)
    )
    raw = json.dumps(payload).encode()
    req = parse_export_request(raw, "application/json")
    assert len(req.resource_spans) == 1
    pb = serialize_request(req, as_protobuf=True)
    req2 = parse_export_request(pb, "application/x-protobuf")
    valid, rejected = count_spans(req2)
    assert valid == 1
    assert rejected == 0


def test_otlp_json_hex_trace_and_span_ids() -> None:
    payload = build_minimal_json_request(
        trace_id=_trace_bytes("a" * 32), span_id=_trace_bytes("b" * 16)
    )
    span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    span["traceId"] = "a" * 32
    span["spanId"] = "b" * 16
    req = parse_export_request(json.dumps(payload).encode(), "application/json")
    parsed = req.resource_spans[0].scope_spans[0].spans[0]
    assert parsed.trace_id.hex() == "a" * 32
    assert parsed.span_id.hex() == "b" * 16


def test_gzip_ingest_decompresses_before_parse() -> None:
    payload = build_minimal_json_request(
        trace_id=_trace_bytes("c" * 32), span_id=_trace_bytes("d" * 16)
    )
    raw = gzip.compress(json.dumps(payload).encode())
    from collector.limits import decompress_if_needed

    body = decompress_if_needed(raw, "gzip", Settings())
    req = parse_export_request(body, "application/json")
    assert count_spans(req)[0] == 1


def test_standard_otlp_json_hex_ids_are_decoded() -> None:
    payload = build_minimal_json_request(
        trace_id=_trace_bytes("a" * 32), span_id=_trace_bytes("b" * 16)
    )
    span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    span["traceId"] = "a" * 32
    span["spanId"] = "b" * 16
    req = parse_export_request(json.dumps(payload).encode(), "application/json")
    parsed = req.resource_spans[0].scope_spans[0].spans[0]
    assert parsed.trace_id.hex() == "a" * 32
    assert parsed.span_id.hex() == "b" * 16


def test_capture_transform_on_span_and_unknown_span_retained() -> None:
    payload = build_minimal_json_request(
        trace_id=_trace_bytes("e" * 32), span_id=_trace_bytes("f" * 16)
    )
    payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"] = [
        {"key": "gen_ai.input.messages", "value": {"stringValue": "secret-payload"}},
        {"key": "http.method", "value": {"stringValue": "GET"}},
    ]
    payload["resourceSpans"][0]["scopeSpans"][0]["spans"].append(
        {
            "traceId": base64.b64encode(_trace_bytes("e" * 32)).decode(),
            "spanId": base64.b64encode(_trace_bytes("0123456789abcdef")).decode(),
            "name": "unknown-operation",
            "startTimeUnixNano": "1",
            "endTimeUnixNano": "2",
        }
    )
    req = trace_service_pb2.ExportTraceServiceRequest()
    json_format.Parse(json.dumps(payload), req)
    settings = Settings(capture_mode=CaptureMode.DIGEST)
    apply_capture_to_request(req, settings)
    span = req.resource_spans[0].scope_spans[0].spans[0]
    keys = {kv.key for kv in span.attributes}
    assert "gen_ai.input.messages" not in keys
    assert any(k.endswith(".digest") for k in keys)
    assert "http.method" in keys
    assert len(req.resource_spans[0].scope_spans[0].spans) == 2


def test_zero_rate_drops_normal_trace_but_tail_preserves_failure() -> None:
    payload = build_minimal_json_request(
        trace_id=_trace_bytes("1" * 32), span_id=_trace_bytes("2" * 16)
    )
    normal = parse_export_request(json.dumps(payload).encode(), "application/json")
    policy = SamplingPolicy(
        head_sample_rate=0,
        tail_keep_errors=True,
        tail_keep_retries=False,
        tail_keep_high_latency=False,
    )
    assert apply_trace_sampling(normal, policy) == 1
    assert count_spans(normal)[0] == 0

    failed = parse_export_request(json.dumps(payload).encode(), "application/json")
    failed.resource_spans[0].scope_spans[0].spans[0].status.code = 2
    assert apply_trace_sampling(failed, policy) == 0
    assert count_spans(failed)[0] == 1


def test_logs_json_and_protobuf_parse() -> None:
    payload = build_minimal_json_log_request(body="ping")
    raw = json.dumps(payload).encode()
    req = parse_logs_export_request(raw, "application/json")
    assert len(req.resource_logs) == 1
    pb = serialize_logs_request(req, as_protobuf=True)
    req2 = parse_logs_export_request(pb, "application/x-protobuf")
    valid, rejected = count_log_records(req2)
    assert valid == 1
    assert rejected == 0


def test_logs_json_hex_trace_and_span_ids() -> None:
    payload = build_minimal_json_log_request()
    record = payload["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]
    record["traceId"] = "a" * 32
    record["spanId"] = "b" * 16
    req = parse_logs_export_request(json.dumps(payload).encode(), "application/json")
    parsed = req.resource_logs[0].scope_logs[0].log_records[0]
    assert parsed.trace_id.hex() == "a" * 32
    assert parsed.span_id.hex() == "b" * 16


def test_logs_lifecycle_correlation_validation() -> None:
    trace = _trace_bytes("a" * 32)
    span = _trace_bytes("b" * 16)
    uncorrelated = build_minimal_json_log_request(body="plain")
    lifecycle_exec = build_minimal_json_log_request(
        trace_id=trace,
        attributes=[
            {"key": LIFECYCLE_EVENT_ATTR, "value": {"stringValue": "execution.started"}},
        ],
    )
    lifecycle_obs_missing_span = build_minimal_json_log_request(
        trace_id=trace,
        attributes=[
            {"key": LIFECYCLE_EVENT_ATTR, "value": {"stringValue": "observation.started"}},
        ],
    )
    lifecycle_obs_ok = build_minimal_json_log_request(
        trace_id=trace,
        span_id=span,
        attributes=[
            {"key": LIFECYCLE_EVENT_ATTR, "value": {"stringValue": "observation.started"}},
        ],
    )
    for payload in (uncorrelated, lifecycle_exec, lifecycle_obs_ok):
        req = parse_logs_export_request(json.dumps(payload).encode(), "application/json")
        valid, rejected = count_log_records(req)
        assert valid == 1
        assert rejected == 0
    bad = parse_logs_export_request(
        json.dumps(lifecycle_obs_missing_span).encode(), "application/json"
    )
    valid, rejected = count_log_records(bad)
    assert valid == 0
    assert rejected == 1


def test_logs_capture_transform_on_body_and_attributes() -> None:
    payload = build_minimal_json_log_request(
        body="secret-log-body",
        attributes=[
            {"key": "gen_ai.input.messages", "value": {"stringValue": "secret-attr"}},
            {"key": "http.method", "value": {"stringValue": "GET"}},
        ],
    )
    req = parse_logs_export_request(json.dumps(payload).encode(), "application/json")
    settings = Settings(capture_mode=CaptureMode.DIGEST)
    apply_capture_to_logs_request(req, settings)
    record = req.resource_logs[0].scope_logs[0].log_records[0]
    keys = {kv.key for kv in record.attributes}
    assert "gen_ai.input.messages" not in keys
    assert any(k.startswith("log.body.") for k in keys)
    assert "http.method" in keys
    assert record.body.WhichOneof("value") is None
