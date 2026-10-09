from __future__ import annotations

from pathlib import Path

import pytest

from collector.errors import SpoolQuotaError
from collector.spool import SpoolMetadata, SpoolStore


def test_atomic_put_and_idempotent(tmp_spool: SpoolStore) -> None:
    meta = SpoolMetadata(
        envelope_digest="",
        content_type="application/json",
        content_encoding="identity",
        traceparent=None,
        tracestate=None,
        span_count=1,
        rejected_span_count=0,
        created_at_unix=SpoolStore.now(),
    )
    created, digest = tmp_spool.put_if_absent(b'{"resourceSpans":[]}', meta)
    assert created
    again, digest2 = tmp_spool.put_if_absent(b'{"resourceSpans":[]}', meta)
    assert not again
    assert digest == digest2
    assert tmp_spool.pending_count() == 1


def test_crash_recovery_moves_inflight_to_pending(tmp_spool: SpoolStore) -> None:
    meta = SpoolMetadata(
        envelope_digest="",
        content_type="application/json",
        content_encoding="identity",
        traceparent=None,
        tracestate=None,
        span_count=1,
        rejected_span_count=0,
        created_at_unix=SpoolStore.now(),
    )
    _, digest = tmp_spool.put_if_absent(b"envelope-bytes", meta)
    assert tmp_spool.claim(digest) is not None
    assert tmp_spool.pending_count() == 0
    assert tmp_spool.recover_after_crash() == 1
    assert tmp_spool.pending_count() == 1


def test_quota_enforced(tmp_path: Path) -> None:
    spool = SpoolStore(tmp_path / "small", disk_quota_bytes=50)
    meta = SpoolMetadata(
        envelope_digest="",
        content_type="application/json",
        content_encoding="identity",
        traceparent=None,
        tracestate=None,
        span_count=1,
        rejected_span_count=0,
        created_at_unix=SpoolStore.now(),
    )
    with pytest.raises(SpoolQuotaError):
        spool.put_if_absent(b"x" * 100, meta)


def test_success_deletes_inflight_only_after_release(tmp_spool: SpoolStore) -> None:
    meta = SpoolMetadata(
        envelope_digest="",
        content_type="application/json",
        content_encoding="identity",
        traceparent=None,
        tracestate=None,
        span_count=1,
        rejected_span_count=0,
        created_at_unix=SpoolStore.now(),
    )
    _, digest = tmp_spool.put_if_absent(b"payload", meta)
    tmp_spool.claim(digest)
    inflight_bin, _ = tmp_spool._pair_paths(tmp_spool.inflight, digest)
    assert inflight_bin.exists()
    tmp_spool.release_success(digest)
    assert not inflight_bin.exists()


def test_spool_metadata_backwards_compatible_defaults(tmp_spool: SpoolStore) -> None:
    legacy = (
        '{"attempt_count":0,"content_encoding":"identity","content_type":"application/json",'
        '"created_at_unix":1.0,"envelope_digest":"sha256:abc","rejected_span_count":0,'
        '"span_count":1,"traceparent":null,"tracestate":null}'
    )
    meta = SpoolMetadata.from_json(legacy)
    assert meta.signal_type == "traces"
    assert meta.event_count == 0
    assert meta.rejected_event_count == 0
