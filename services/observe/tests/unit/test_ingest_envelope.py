from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

from google.protobuf import json_format
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2
from opentelemetry.proto.common.v1 import common_pb2
from opentelemetry.proto.trace.v1 import trace_pb2

from observe.auth.schemas import WorkloadPrincipal
from observe.config import CaptureMode, Settings
from observe.db.repository import IngestManifest
from observe.ingest import service as ingest_service
from observe.providers.object_store.base import LocalObjectStore


def _minimal_trace_export_bytes() -> bytes:
    req = trace_service_pb2.ExportTraceServiceRequest(
        resource_spans=[
            trace_pb2.ResourceSpans(
                scope_spans=[
                    trace_pb2.ScopeSpans(
                        spans=[
                            trace_pb2.Span(
                                trace_id=bytes.fromhex("a" * 32),
                                span_id=bytes.fromhex("b" * 16),
                                name="test",
                            )
                        ]
                    )
                ]
            )
        ]
    )
    return req.SerializeToString()


def _principal() -> WorkloadPrincipal:
    return WorkloadPrincipal(
        subject="test-workload",
        organization_id=uuid4(),
        project_id=uuid4(),
        agent_id=uuid4(),
        capture_mode=CaptureMode.NONE,
        payload_retention_days=30,
        payload_encryption_key_ref=None,
    )


def test_protobuf_ingest_stores_sanitized_json_metadata(tmp_path) -> None:
    store = LocalObjectStore(tmp_path / "obj")
    settings = Settings(object_store_root=str(tmp_path / "obj"), payload_encryption_key="")
    principal = _principal()
    body = _minimal_trace_export_bytes()

    manifest_id = uuid4()
    conn = MagicMock()

    with (
        patch("observe.ingest.service.pg.connect") as mock_connect,
        patch("observe.ingest.service.repo.get_manifest_by_source_wire_digest", return_value=None),
        patch("observe.ingest.service.repo.get_manifest_by_digest", return_value=None),
        patch("observe.ingest.service.repo.insert_manifest", return_value=manifest_id) as insert,
        patch("observe.ingest.service.repo.insert_payload_ref_from_ingest") as insert_ref,
        patch("observe.ingest.service.publish_ingest_wake"),
    ):
        mock_connect.return_value.__enter__.return_value = conn
        ingest_service.ingest_traces_sync(
            settings,
            store,
            principal=principal,
            body=body,
            content_type="application/x-protobuf",
            content_encoding=None,
            accept="application/json",
        )

    insert.assert_called_once()
    kwargs = insert.call_args.kwargs
    assert kwargs["content_type"] == "application/json"
    assert kwargs["content_encoding"] == "identity"
    assert kwargs["source_wire_digest"].startswith("sha256:")
    assert kwargs["envelope_digest"].startswith("sha256:")
    assert kwargs["source_wire_digest"] != kwargs["envelope_digest"]
    insert_ref.assert_not_called()


def test_source_wire_digest_replay_skips_object_write(tmp_path) -> None:
    store = LocalObjectStore(tmp_path / "obj")
    settings = Settings(object_store_root=str(tmp_path / "obj"), payload_encryption_key="")
    principal = _principal()
    body = _minimal_trace_export_bytes()
    wire_digest = store.digest(body)

    existing = IngestManifest(
        id=uuid4(),
        organization_id=principal.organization_id,
        project_id=principal.project_id,
        agent_id=principal.agent_id,
        envelope_digest="sha256:dead",
        object_key="k",
        content_encoding="identity",
        content_type="application/json",
        byte_size=1,
        span_count=1,
        rejected_span_count=0,
        capture_mode="none",
        status="done",
        attempt_count=1,
        source_wire_digest=wire_digest,
    )

    with (
        patch("observe.ingest.service.pg.connect") as mock_connect,
        patch(
            "observe.ingest.service.repo.get_manifest_by_source_wire_digest",
            return_value=existing,
        ),
        patch.object(store, "put") as put_mock,
    ):
        mock_connect.return_value.__enter__.return_value = MagicMock()
        payload, media, status = ingest_service.ingest_traces_sync(
            settings,
            store,
            principal=principal,
            body=body,
            content_type="application/x-protobuf",
            content_encoding=None,
            accept="application/json",
        )

    put_mock.assert_not_called()
    assert status == 200
    assert media == "application/json"
    assert payload


def test_sanitize_protobuf_json_roundtrip_scrubs_secrets(tmp_path) -> None:
    store = LocalObjectStore(tmp_path / "obj")
    settings = Settings(object_store_root=str(tmp_path / "obj"), payload_encryption_key="")
    req = trace_service_pb2.ExportTraceServiceRequest(
        resource_spans=[
            trace_pb2.ResourceSpans(
                scope_spans=[
                    trace_pb2.ScopeSpans(
                        spans=[
                            trace_pb2.Span(
                                trace_id=bytes.fromhex("f" * 32),
                                span_id=bytes.fromhex("e" * 16),
                                name="n",
                                attributes=[
                                    common_pb2.KeyValue(
                                        key="note",
                                        value=common_pb2.AnyValue(
                                            string_value="token=supersecretvalue123456789"
                                        ),
                                    )
                                ],
                            )
                        ]
                    )
                ]
            )
        ]
    )
    json_body = json_format.MessageToJson(req).encode("utf-8")
    from observe.ingest.sanitize import sanitize_otlp_json_envelope

    out = sanitize_otlp_json_envelope(
        settings,
        store,
        org_id=uuid4(),
        project_id=uuid4(),
        mode=CaptureMode.NONE,
        encryption_key_ref=None,
        body=json_body,
        content_type="application/json",
        envelope_kind="traces",
    )
    assert b"supersecret" not in out.body
    assert b"[REDACTED_SECRET]" in out.body
