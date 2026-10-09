from __future__ import annotations

import json
from uuid import uuid4

from observe.config import CaptureMode, Settings
from observe.ingest.sanitize import sanitize_otlp_json_envelope
from observe.providers.object_store.base import LocalObjectStore


def test_secret_scrubbed_from_attributes(tmp_path) -> None:
    org = uuid4()
    project = uuid4()
    store = LocalObjectStore(str(tmp_path / "obj"))
    settings = Settings(object_store_root=str(tmp_path / "obj"), payload_encryption_key="")
    body = json.dumps(
        {
            "resourceSpans": [
                {
                    "resource": {"attributes": []},
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": "a" * 32,
                                    "spanId": "b" * 16,
                                    "name": "chat",
                                    "attributes": [
                                        {
                                            "key": "gen_ai.request.model",
                                            "value": {"stringValue": "gpt-4"},
                                        },
                                        {
                                            "key": "note",
                                            "value": {
                                                "stringValue": "api_key=supersecretvalue123456789"
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
    attrs = doc["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"]
    note = next(a for a in attrs if a["key"] == "note")
    assert "supersecret" not in note["value"]["stringValue"]
    assert "[REDACTED_SECRET]" in note["value"]["stringValue"]


def test_redacted_mode_masks_enterprise_pii_and_tokens(tmp_path) -> None:
    store = LocalObjectStore(str(tmp_path / "obj"))
    settings = Settings(
        object_store_root=str(tmp_path / "obj"),
        payload_encryption_key="7dBIPYGHnfUUUwvViWNzwhWBSjbsR7jwIlV_qFXr-KQ=",
    )
    sensitive = (
        "user jane@example.com phone 555-123-4567 ip 10.20.30.40 "
        "ssn 123-45-6789 card 4111 1111 1111 1111 "
        "token eyJhbGciOiJIUzI1NiJ9.cGF5bG9hZA.c2lnbmF0dXJl"
    )
    body = json.dumps(
        {
            "resourceSpans": [
                {
                    "resource": {"attributes": []},
                    "scopeSpans": [
                        {
                            "spans": [
                                {
                                    "traceId": "a" * 32,
                                    "spanId": "b" * 16,
                                    "name": "agent",
                                    "attributes": [
                                        {"key": "note", "value": {"stringValue": sensitive}}
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
        org_id=uuid4(),
        project_id=uuid4(),
        mode=CaptureMode.REDACTED,
        encryption_key_ref="local:test",
        body=body,
        content_type="application/json",
        envelope_kind="traces",
    )
    rendered = out.body.decode()
    for secret in (
        "jane@example.com",
        "555-123-4567",
        "10.20.30.40",
        "123-45-6789",
        "4111 1111 1111 1111",
        "eyJhbGci",
    ):
        assert secret not in rendered
