"""Ingest business logic: durable sanitized envelope + manifest."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from google.protobuf import json_format

from observe.auth.schemas import WorkloadPrincipal
from observe.auth.workload import assert_agent_binding
from observe.config import Settings
from observe.db import postgres as pg
from observe.db import repository as repo
from observe.errors import IdempotencyConflictError, InvalidEnvelopeError
from observe.ingest import otlp
from observe.ingest.limits import decompress_if_needed
from observe.ingest.responses import (
    export_logs_response_body,
    export_response_body,
    prefers_protobuf,
)
from observe.ingest.sanitize import SanitizedEnvelope, sanitize_otlp_json_envelope
from observe.providers.object_store.base import ObjectStore, tenant_envelope_key
from observe.redis.wake import publish_ingest_wake

log = logging.getLogger(__name__)


STORED_CONTENT_ENCODING = "identity"


def _replay_response(
    existing: repo.IngestManifest,
    *,
    as_protobuf: bool,
    envelope_kind: str,
) -> tuple[bytes, str, int]:

    if envelope_kind == "logs":
        resp = export_logs_response_body(
            rejected_records=existing.rejected_span_count,
            error_message="replayed idempotent ingest",
            as_protobuf=as_protobuf,
        )

    else:
        resp = export_response_body(
            rejected_spans=existing.rejected_span_count,
            error_message="replayed idempotent ingest",
            as_protobuf=as_protobuf,
        )

    media = "application/x-protobuf" if as_protobuf else "application/json"

    return resp, media, 200


def _ingest_envelope_sync(
    settings: Settings,
    store: ObjectStore,
    *,
    principal: WorkloadPrincipal,
    response_as_protobuf: bool,
    envelope_kind: str,
    record_count: int,
    rejected_count: int,
    source_wire_digest: str,
    sanitized: SanitizedEnvelope,
    payload_refs: list[dict[str, Any]],
) -> tuple[bytes, str, int]:
    object_key = tenant_envelope_key(
        principal.organization_id, principal.project_id, sanitized.envelope_digest
    )

    with pg.connect(
        settings.database_url,
        organization_id=principal.organization_id,
        project_id=principal.project_id,
    ) as conn:
        if source_wire_digest:
            by_source = repo.get_manifest_by_source_wire_digest(
                conn,
                principal.organization_id,
                principal.project_id,
                source_wire_digest,
            )

            if by_source is not None:
                return _replay_response(
                    by_source,
                    as_protobuf=response_as_protobuf,
                    envelope_kind=envelope_kind,
                )

        existing = repo.get_manifest_by_digest(
            conn, principal.organization_id, principal.project_id, sanitized.envelope_digest
        )

        if existing is not None:
            if existing.object_key != object_key:
                raise IdempotencyConflictError("digest conflict with different object key")

            return _replay_response(
                existing,
                as_protobuf=response_as_protobuf,
                envelope_kind=envelope_kind,
            )

        stored = store.put(object_key, sanitized.body, sanitized.content_type)

        if stored.digest != sanitized.envelope_digest:
            raise IdempotencyConflictError("stored digest mismatch")

        manifest_id = repo.insert_manifest(
            conn,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            agent_id=principal.agent_id,
            envelope_digest=sanitized.envelope_digest,
            source_wire_digest=source_wire_digest,
            object_key=object_key,
            content_encoding=STORED_CONTENT_ENCODING,
            content_type=sanitized.content_type,
            byte_size=len(sanitized.body),
            span_count=record_count if envelope_kind == "traces" else 0,
            log_record_count=record_count if envelope_kind == "logs" else 0,
            rejected_span_count=rejected_count,
            capture_mode=principal.capture_mode.value,
            payload_retention_days=principal.payload_retention_days,
            payload_encryption_key_ref=principal.payload_encryption_key_ref,
            envelope_kind=envelope_kind,
        )

        for ref in payload_refs:
            if not ref.get("object_key"):
                continue

            repo.insert_payload_ref_from_ingest(
                conn,
                org_id=principal.organization_id,
                project_id=principal.project_id,
                trace_id=str(ref["trace_id"]),
                span_id=str(ref["span_id"]),
                field_name=str(ref["field_name"]),
                digest=str(ref["digest"]),
                object_key=str(ref["object_key"]),
                byte_size=int(ref["byte_size"]),
                encryption_key_ref=str(ref.get("encryption_key_ref") or "local:fernet"),
                redaction_state=str(ref.get("redaction_state") or "unknown"),
                retention_days=principal.payload_retention_days,
            )

    publish_ingest_wake(settings, str(manifest_id))

    if envelope_kind == "logs":
        resp = export_logs_response_body(
            rejected_records=rejected_count,
            error_message="invalid records rejected" if rejected_count else "",
            as_protobuf=response_as_protobuf,
        )

    else:
        resp = export_response_body(
            rejected_spans=rejected_count,
            error_message="invalid spans rejected" if rejected_count else "",
            as_protobuf=response_as_protobuf,
        )

    media = "application/x-protobuf" if response_as_protobuf else "application/json"

    return resp, media, 200


def _sanitize_request_body(
    settings: Settings,
    store: ObjectStore,
    *,
    principal: WorkloadPrincipal,
    raw: bytes,
    content_type: str,
    envelope_kind: str,
    parse_fn: Any,
    from_request_fn: Any,
    prune_fn: Any,
) -> tuple[SanitizedEnvelope, int, int]:

    req = parse_fn(raw, content_type)

    records, rejected = from_request_fn(req)
    prune_fn(req)

    sanitize_body = json_format.MessageToJson(req).encode("utf-8")

    sanitized = sanitize_otlp_json_envelope(
        settings,
        store,
        org_id=principal.organization_id,
        project_id=principal.project_id,
        mode=principal.capture_mode,
        encryption_key_ref=principal.payload_encryption_key_ref,
        body=sanitize_body,
        content_type="application/json",
        envelope_kind=envelope_kind,
    )

    return sanitized, len(records), rejected


def ingest_traces_sync(
    settings: Settings,
    store: ObjectStore,
    *,
    principal: WorkloadPrincipal,
    body: bytes,
    content_type: str,
    content_encoding: str | None,
    accept: str | None,
) -> tuple[bytes, str, int]:
    """Returns (body bytes, media type, HTTP status)."""

    response_as_protobuf = prefers_protobuf(content_type, accept)
    raw = decompress_if_needed(body, content_encoding, settings)

    source_wire_digest = store.digest(raw)

    sanitized, record_count, rejected = _sanitize_request_body(
        settings,
        store,
        principal=principal,
        raw=raw,
        content_type=content_type,
        envelope_kind="traces",
        parse_fn=otlp.parse_export_request,
        from_request_fn=otlp.spans_from_request,
        prune_fn=otlp.drop_invalid_spans,
    )

    total_spans = record_count + rejected

    if total_spans > settings.max_spans_per_request:
        raise InvalidEnvelopeError("span count exceeds limit")
    if record_count == 0:
        body = export_response_body(
            rejected_spans=rejected,
            error_message="invalid spans rejected" if rejected else "",
            as_protobuf=response_as_protobuf,
        )
        media = "application/x-protobuf" if response_as_protobuf else "application/json"
        return body, media, 200

    req = otlp.parse_export_request(raw, content_type)

    spans, _ = otlp.spans_from_request(req)

    for span in spans:
        agent_attr = span.attributes.get("gen_ai.agent.id") or span.resource_attributes.get(
            "gen_ai.agent.id"
        )

        if agent_attr is not None:
            assert_agent_binding(principal, str(agent_attr))

    return _ingest_envelope_sync(
        settings,
        store,
        principal=principal,
        response_as_protobuf=response_as_protobuf,
        envelope_kind="traces",
        record_count=record_count,
        rejected_count=rejected,
        source_wire_digest=source_wire_digest,
        sanitized=sanitized,
        payload_refs=sanitized.payload_refs,
    )


def ingest_logs_sync(
    settings: Settings,
    store: ObjectStore,
    *,
    principal: WorkloadPrincipal,
    body: bytes,
    content_type: str,
    content_encoding: str | None,
    accept: str | None,
) -> tuple[bytes, str, int]:

    response_as_protobuf = prefers_protobuf(content_type, accept)
    raw = decompress_if_needed(body, content_encoding, settings)

    source_wire_digest = store.digest(raw)

    sanitized, record_count, rejected = _sanitize_request_body(
        settings,
        store,
        principal=principal,
        raw=raw,
        content_type=content_type,
        envelope_kind="logs",
        parse_fn=otlp.parse_logs_export_request,
        from_request_fn=otlp.logs_from_request,
        prune_fn=otlp.drop_invalid_log_records,
    )

    total = record_count + rejected

    if total > settings.max_logs_per_request:
        raise InvalidEnvelopeError("log record count exceeds limit")
    if record_count == 0:
        body = export_logs_response_body(
            rejected_records=rejected,
            error_message="invalid log records rejected" if rejected else "",
            as_protobuf=response_as_protobuf,
        )
        media = "application/x-protobuf" if response_as_protobuf else "application/json"
        return body, media, 200

    return _ingest_envelope_sync(
        settings,
        store,
        principal=principal,
        response_as_protobuf=response_as_protobuf,
        envelope_kind="logs",
        record_count=record_count,
        rejected_count=rejected,
        source_wire_digest=source_wire_digest,
        sanitized=sanitized,
        payload_refs=sanitized.payload_refs,
    )


async def ingest_traces(
    settings: Settings,
    store: ObjectStore,
    *,
    principal: WorkloadPrincipal,
    body: bytes,
    content_type: str,
    content_encoding: str | None,
    accept: str | None,
) -> tuple[bytes, str, int]:

    return await asyncio.to_thread(
        ingest_traces_sync,
        settings,
        store,
        principal=principal,
        body=body,
        content_type=content_type,
        content_encoding=content_encoding,
        accept=accept,
    )


async def ingest_logs(
    settings: Settings,
    store: ObjectStore,
    *,
    principal: WorkloadPrincipal,
    body: bytes,
    content_type: str,
    content_encoding: str | None,
    accept: str | None,
) -> tuple[bytes, str, int]:

    return await asyncio.to_thread(
        ingest_logs_sync,
        settings,
        store,
        principal=principal,
        body=body,
        content_type=content_type,
        content_encoding=content_encoding,
        accept=accept,
    )


def verify_object_matches_manifest(
    store: ObjectStore,
    *,
    org_id: UUID,
    project_id: UUID,
    digest: str,
    object_key: str,
) -> bool:

    expected = tenant_envelope_key(org_id, project_id, digest)

    if object_key != expected:
        return False

    return store.exists(object_key)
