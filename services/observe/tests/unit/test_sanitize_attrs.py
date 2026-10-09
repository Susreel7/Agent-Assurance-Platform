from __future__ import annotations

import base64
import json
from uuid import uuid4

from observe.config import CaptureMode, Settings
from observe.ingest.sanitize import sanitize_otlp_json_envelope
from observe.providers.object_store.base import LocalObjectStore


def test_array_and_kvlist_attributes_preserved(tmp_path) -> None:
    org = uuid4()
    project = uuid4()
    store = LocalObjectStore(tmp_path / "obj")
    settings = Settings(object_store_root=str(tmp_path / "obj"), payload_encryption_key="")
    trace_hex = "a" * 32
    span_hex = "b" * 16
    body = json.dumps(
        {
            "resourceSpans": [
                {
                    "resource": {"attributes": []},
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": base64.b64encode(bytes.fromhex(trace_hex)).decode(),
                                    "spanId": base64.b64encode(bytes.fromhex(span_hex)).decode(),
                                    "name": "x",
                                    "attributes": [
                                        {
                                            "key": "tags",
                                            "value": {
                                                "arrayValue": {"values": [{"stringValue": "alpha"}]}
                                            },
                                        },
                                        {
                                            "key": "meta",
                                            "value": {
                                                "kvlistValue": {
                                                    "values": [
                                                        {
                                                            "key": "tier",
                                                            "value": {"stringValue": "prod"},
                                                        }
                                                    ]
                                                }
                                            },
                                        },
                                    ],
                                }
                            ]
                        }
                    ],
                }
            ]
        }
    ).encode()
    out = sanitize_otlp_json_envelope(
        settings,
        store,
        org_id=org,
        project_id=project,
        mode=CaptureMode.NONE,
        encryption_key_ref=None,
        body=body,
        content_type="application/json",
        envelope_kind="traces",
    )
    doc = json.loads(out.body)
    span = doc["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert span["traceId"] == trace_hex
    assert span["spanId"] == span_hex
    attrs = {a["key"]: a["value"] for a in span["attributes"]}
    assert "arrayValue" in attrs["tags"]
    assert attrs["tags"]["arrayValue"]["values"][0]["stringValue"] == "alpha"
    assert attrs["meta"]["kvlistValue"]["values"][0]["key"] == "tier"


def test_payload_ref_ids_are_canonical_hex(tmp_path) -> None:
    org = uuid4()
    project = uuid4()
    store = LocalObjectStore(tmp_path / "obj")
    settings = Settings(
        object_store_root=str(tmp_path / "obj"),
        payload_encryption_key="fTahKxdyPMkxj-Al0tykQiAIl0hjf1f1CZS65nEzTPM=",
    )
    trace_hex = "c" * 32
    span_hex = "d" * 16
    body = json.dumps(
        {
            "resourceSpans": [
                {
                    "resource": {"attributes": []},
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": trace_hex,
                                    "spanId": span_hex,
                                    "attributes": [
                                        {
                                            "key": "gen_ai.input.messages",
                                            "value": {"stringValue": "hello"},
                                        }
                                    ],
                                }
                            ]
                        }
                    ],
                }
            ]
        }
    ).encode()
    out = sanitize_otlp_json_envelope(
        settings,
        store,
        org_id=org,
        project_id=project,
        mode=CaptureMode.FULL,
        encryption_key_ref="local:fernet",
        body=body,
        content_type="application/json",
        envelope_kind="traces",
    )
    assert len(out.payload_refs) == 1
    assert out.payload_refs[0]["trace_id"] == trace_hex
    assert out.payload_refs[0]["span_id"] == span_hex
