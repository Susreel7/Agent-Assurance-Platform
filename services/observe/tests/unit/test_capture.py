from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from observe.config import CaptureMode, Settings
from observe.ingest.otlp import RawSpan
from observe.providers.object_store.base import LocalObjectStore
from observe.worker.capture import process_capture_for_manifest
from observe.worker.normalizer import normalize_span


def test_digest_mode_no_object_writes(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "obj")
    settings = Settings(object_store_root=str(tmp_path))
    span = RawSpan(
        trace_id="t" * 32,
        span_id="s" * 16,
        parent_span_id=None,
        name="chat",
        start_time_unix_nano=0,
        end_time_unix_nano=1000,
        status_code="ok",
        attributes={"gen_ai.input.messages": [{"role": "user", "content": "hi"}]},
        resource_attributes={},
        events=[],
    )
    ns = normalize_span(span)
    writes = process_capture_for_manifest(
        settings,
        store,
        org_id=uuid4(),
        project_id=uuid4(),
        mode=CaptureMode.DIGEST,
        encryption_key_ref="kms:1",
        retention_days=7,
        ns=ns,
    )
    assert len(writes) == 1
    assert writes[0].object_key == ""
    assert writes[0].digest.startswith("sha256:")
