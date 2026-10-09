"""Ingest handler: parse, capture, durable spool, OTLP response."""

from __future__ import annotations

from collector.config import Settings
from collector.errors import InvalidEnvelopeError, SpoolQuotaError
from collector.limits import decompress_if_needed
from collector.metrics import CollectorMetrics
from collector.otlp import (
    apply_capture_to_logs_request,
    apply_capture_to_request,
    apply_trace_sampling,
    count_log_records,
    count_spans,
    drop_invalid_log_records,
    drop_invalid_spans,
    envelope_media_type,
    parse_export_request,
    parse_logs_export_request,
    serialize_logs_request,
    serialize_request,
    trace_scope,
)
from collector.responses import export_logs_response_body, export_response_body, prefers_protobuf
from collector.sampling import SamplingPolicyCache
from collector.spool import SpoolMetadata, SpoolStore


def handle_ingest(
    settings: Settings,
    spool: SpoolStore,
    metrics: CollectorMetrics,
    *,
    body: bytes,
    content_type: str,
    content_encoding: str | None,
    accept: str | None,
    traceparent: str | None,
    tracestate: str | None,
    sampling: SamplingPolicyCache | None = None,
) -> tuple[bytes, str, int]:
    as_protobuf = prefers_protobuf(content_type, accept)
    raw = decompress_if_needed(body, content_encoding, settings)
    req = parse_export_request(raw, content_type)
    valid, rejected = count_spans(req)
    total = valid + rejected
    if total > settings.max_spans_per_request:
        raise InvalidEnvelopeError("span count exceeds limit")
    if valid == 0:
        media = envelope_media_type(as_protobuf)
        return (
            export_response_body(
                rejected_spans=rejected,
                error_message="invalid spans rejected",
                as_protobuf=as_protobuf,
            ),
            media,
            200,
        )

    drop_invalid_spans(req)
    if sampling is not None:
        organization_id, project_id = trace_scope(req)
        policy = sampling.get(organization_id, project_id)
        dropped = apply_trace_sampling(
            req,
            policy,
            rate_allow=lambda trace_id: sampling.allow_trace(
                organization_id,
                project_id,
                trace_id,
                policy.max_traces_per_minute,
            ),
        )
        if dropped:
            metrics.inc("sampled_spans_dropped", dropped)
        kept, _ = count_spans(req)
        if kept == 0:
            return (
                export_response_body(as_protobuf=as_protobuf),
                envelope_media_type(as_protobuf),
                200,
            )
        valid = kept
    apply_capture_to_request(req, settings)
    envelope = serialize_request(req, as_protobuf=as_protobuf)
    outbound_encoding = "identity"
    media = envelope_media_type(as_protobuf)

    meta = SpoolMetadata(
        envelope_digest="",
        content_type=media,
        content_encoding=outbound_encoding,
        traceparent=traceparent,
        tracestate=tracestate,
        span_count=valid,
        rejected_span_count=rejected,
        created_at_unix=SpoolStore.now(),
    )
    try:
        created, _digest = spool.put_if_absent(envelope, meta)
    except SpoolQuotaError:
        metrics.inc("ingest_quota_denied")
        raise

    if created:
        metrics.inc("ingest_accepted")
    else:
        metrics.inc("ingest_idempotent_replay")

    resp = export_response_body(
        rejected_spans=rejected,
        error_message="invalid spans rejected" if rejected else "",
        as_protobuf=as_protobuf,
    )
    return resp, media, 200


def handle_logs_ingest(
    settings: Settings,
    spool: SpoolStore,
    metrics: CollectorMetrics,
    *,
    body: bytes,
    content_type: str,
    content_encoding: str | None,
    accept: str | None,
    traceparent: str | None,
    tracestate: str | None,
    sampling: SamplingPolicyCache | None = None,
) -> tuple[bytes, str, int]:
    as_protobuf = prefers_protobuf(content_type, accept)
    raw = decompress_if_needed(body, content_encoding, settings)
    req = parse_logs_export_request(raw, content_type)
    valid, rejected = count_log_records(req)
    total = valid + rejected
    if total > settings.max_logs_per_request:
        raise InvalidEnvelopeError("log record count exceeds limit")
    if valid == 0:
        media = envelope_media_type(as_protobuf)
        return (
            export_logs_response_body(
                rejected_log_records=rejected,
                error_message="invalid log records rejected",
                as_protobuf=as_protobuf,
            ),
            media,
            200,
        )

    drop_invalid_log_records(req)
    apply_capture_to_logs_request(req, settings)
    envelope = serialize_logs_request(req, as_protobuf=as_protobuf)
    outbound_encoding = "identity"
    media = envelope_media_type(as_protobuf)

    meta = SpoolMetadata(
        envelope_digest="",
        content_type=media,
        content_encoding=outbound_encoding,
        traceparent=traceparent,
        tracestate=tracestate,
        span_count=0,
        rejected_span_count=0,
        created_at_unix=SpoolStore.now(),
        signal_type="logs",
        event_count=valid,
        rejected_event_count=rejected,
    )
    try:
        created, _digest = spool.put_if_absent(envelope, meta)
    except SpoolQuotaError:
        metrics.inc("ingest_quota_denied")
        raise

    if created:
        metrics.inc("ingest_accepted")
    else:
        metrics.inc("ingest_idempotent_replay")

    resp = export_logs_response_body(
        rejected_log_records=rejected,
        error_message="invalid log records rejected" if rejected else "",
        as_protobuf=as_protobuf,
    )
    return resp, media, 200
