from __future__ import annotations

import asyncio
from unittest.mock import patch

import httpx
import pytest

from collector.config import Settings
from collector.forwarder import Forwarder
from collector.metrics import CollectorMetrics
from collector.spool import SpoolMetadata, SpoolStore


@pytest.mark.asyncio
async def test_outage_replay_then_delete(tmp_path) -> None:
    spool = SpoolStore(tmp_path / "spool", disk_quota_bytes=1_000_000)
    metrics = CollectorMetrics()
    settings = Settings(
        spool_dir=str(tmp_path / "spool"),
        observe_ingest_url="http://observe.test/v1/traces",
        workload_bearer_token="wk",
        forward_poll_seconds=0.01,
        forward_base_delay_seconds=0,
        poison_attempt_threshold=5,
    )
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
    spool.put_if_absent(b"{}", meta)

    calls = {"n": 0}

    async def fake_post(
        self, url: str, *, content: bytes, headers: dict[str, str]
    ) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(503, request=httpx.Request("POST", url))
        return httpx.Response(200, request=httpx.Request("POST", url))

    forwarder = Forwarder(settings, spool, metrics)
    with patch.object(httpx.AsyncClient, "post", new=fake_post):
        forwarder.start()
        for _ in range(50):
            if metrics.snapshot()["forward_success"] >= 1:
                break
            await asyncio.sleep(0.05)
        await forwarder.stop()

    assert metrics.snapshot()["forward_success"] >= 1
    assert spool.pending_count() == 0
    assert spool.quarantine_count() == 0


@pytest.mark.asyncio
async def test_poison_quarantine_no_head_of_line_block(tmp_path) -> None:
    spool = SpoolStore(tmp_path / "spool", disk_quota_bytes=1_000_000)
    metrics = CollectorMetrics()
    settings = Settings(
        spool_dir=str(tmp_path / "spool"),
        observe_ingest_url="http://observe.test/v1/traces",
        workload_bearer_token="wk",
        forward_poll_seconds=0.01,
        forward_base_delay_seconds=0,
        poison_attempt_threshold=2,
    )
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
    spool.put_if_absent(b'{"first":true}', meta)
    spool.put_if_absent(b'{"second":true}', meta)

    async def fake_post(
        self, url: str, *, content: bytes, headers: dict[str, str]
    ) -> httpx.Response:
        if b"first" in content:
            return httpx.Response(500, request=httpx.Request("POST", url))
        return httpx.Response(200, request=httpx.Request("POST", url))

    forwarder = Forwarder(settings, spool, metrics)
    with patch.object(httpx.AsyncClient, "post", new=fake_post):
        forwarder.start()
        for _ in range(80):
            snap = metrics.snapshot()
            if snap["forward_success"] >= 1 and snap["forward_poisoned"] >= 1:
                break
            await asyncio.sleep(0.05)
        await forwarder.stop()

    assert metrics.snapshot()["forward_poisoned"] >= 1
    assert metrics.snapshot()["forward_success"] >= 1
    assert spool.quarantine_count() >= 1


@pytest.mark.asyncio
async def test_forward_logs_uses_logs_ingest_url(tmp_path) -> None:
    spool = SpoolStore(tmp_path / "spool", disk_quota_bytes=1_000_000)
    metrics = CollectorMetrics()
    settings = Settings(
        spool_dir=str(tmp_path / "spool"),
        observe_ingest_url="http://observe.test/v1/traces",
        observe_logs_ingest_url="http://observe.test/v1/logs",
        workload_bearer_token="wk",
        forward_poll_seconds=0.01,
        forward_base_delay_seconds=0,
    )
    meta = SpoolMetadata(
        envelope_digest="",
        content_type="application/json",
        content_encoding="identity",
        traceparent=None,
        tracestate=None,
        span_count=0,
        rejected_span_count=0,
        created_at_unix=SpoolStore.now(),
        signal_type="logs",
        event_count=1,
        rejected_event_count=0,
    )
    spool.put_if_absent(b'{"resourceLogs":[]}', meta)

    seen: dict[str, str] = {}

    async def fake_post(
        self, url: str, *, content: bytes, headers: dict[str, str]
    ) -> httpx.Response:
        seen["url"] = url
        assert "wk" in headers.get("Authorization", "")
        assert "Bearer wk" == headers.get("Authorization")
        return httpx.Response(200, request=httpx.Request("POST", url))

    forwarder = Forwarder(settings, spool, metrics)
    with patch.object(httpx.AsyncClient, "post", new=fake_post):
        forwarder.start()
        for _ in range(50):
            if seen.get("url"):
                break
            await asyncio.sleep(0.05)
        await forwarder.stop()

    assert seen["url"] == "http://observe.test/v1/logs"
    assert metrics.snapshot()["forward_success"] >= 1
