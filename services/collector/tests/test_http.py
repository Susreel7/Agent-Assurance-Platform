from __future__ import annotations

import gzip
import json
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from opentelemetry.proto.collector.logs.v1 import logs_service_pb2
from opentelemetry.proto.collector.trace.v1 import trace_service_pb2

from collector.config import get_settings
from collector.main import create_app
from collector.otlp import build_minimal_json_log_request, build_minimal_json_request


@pytest.fixture
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("COLLECTOR_SPOOL_DIR", str(tmp_path / "spool"))
    monkeypatch.setenv("COLLECTOR_CAPTURE_MODE", "digest")
    monkeypatch.setenv("COLLECTOR_WORKLOAD_BEARER_TOKEN", "wk-outbound")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def _span_payload() -> dict:
    trace = bytes.fromhex("a" * 32)
    span = bytes.fromhex("b" * 16)
    body = build_minimal_json_request(trace_id=trace, span_id=span)
    body["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["attributes"] = [
        {"key": "gen_ai.input.messages", "value": {"stringValue": "top-secret"}},
    ]
    return body


def test_json_200_and_no_content_leak(client: TestClient) -> None:
    resp = client.post("/v1/traces", json=_span_payload())
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert "top-secret" not in resp.text
    ready = client.get("/readyz")
    assert ready.json()["spool_pending"] == 1


def test_protobuf_response(client: TestClient) -> None:
    req = trace_service_pb2.ExportTraceServiceRequest()
    trace = bytes.fromhex("c" * 32)
    span = bytes.fromhex("d" * 16)
    rs = req.resource_spans.add()
    rs.resource.attributes.add(key="service.name").value.string_value = "svc"
    ss = rs.scope_spans.add()
    sp = ss.spans.add()
    sp.trace_id = trace
    sp.span_id = span
    sp.name = "op"
    sp.start_time_unix_nano = 1
    sp.end_time_unix_nano = 2
    resp = client.post(
        "/v1/traces",
        content=req.SerializeToString(),
        headers={"Content-Type": "application/x-protobuf", "Accept": "application/x-protobuf"},
    )
    assert resp.status_code == 200
    out = trace_service_pb2.ExportTraceServiceResponse()
    out.ParseFromString(resp.content)
    assert out.partial_success.rejected_spans == 0


def test_gzip_request(client: TestClient) -> None:
    raw = json.dumps(_span_payload()).encode()
    resp = client.post(
        "/v1/traces",
        content=gzip.compress(raw),
        headers={"Content-Type": "application/json", "Content-Encoding": "gzip"},
    )
    assert resp.status_code == 200


def test_oversize_rejected(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("COLLECTOR_MAX_COMPRESSED_BYTES", "10")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as c:
        resp = c.post(
            "/v1/traces", content=b"x" * 100, headers={"Content-Type": "application/json"}
        )
        assert resp.status_code == 413
    get_settings.cache_clear()


def test_quota_507(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLLECTOR_DISK_QUOTA_BYTES", "512")
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as c:
        resp = c.post("/v1/traces", json=_span_payload())
        assert resp.status_code == 507
    get_settings.cache_clear()


def _log_payload() -> dict:
    body = build_minimal_json_log_request(body="top-secret-log")
    body["resourceLogs"][0]["scopeLogs"][0]["logRecords"][0]["attributes"] = [
        {"key": "gen_ai.input.messages", "value": {"stringValue": "top-secret"}},
    ]
    return body


def test_logs_json_200_and_no_content_leak(client: TestClient) -> None:
    resp = client.post("/v1/logs", json=_log_payload())
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    assert "top-secret" not in resp.text
    ready = client.get("/readyz")
    assert ready.json()["spool_pending"] == 1


def test_logs_protobuf_response(client: TestClient) -> None:
    req = logs_service_pb2.ExportLogsServiceRequest()
    rl = req.resource_logs.add()
    rl.resource.attributes.add(key="service.name").value.string_value = "svc"
    sl = rl.scope_logs.add()
    record = sl.log_records.add()
    record.time_unix_nano = 1
    record.body.string_value = "event"
    resp = client.post(
        "/v1/logs",
        content=req.SerializeToString(),
        headers={"Content-Type": "application/x-protobuf", "Accept": "application/x-protobuf"},
    )
    assert resp.status_code == 200
    out = logs_service_pb2.ExportLogsServiceResponse()
    out.ParseFromString(resp.content)
    assert out.partial_success.rejected_log_records == 0


def test_malformed_json_400(client: TestClient) -> None:
    resp = client.post(
        "/v1/traces", content=b"{not-json", headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_forward_uses_workload_bearer_not_incoming_auth(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("COLLECTOR_SPOOL_DIR", str(tmp_path / "spool2"))
    monkeypatch.setenv("COLLECTOR_WORKLOAD_BEARER_TOKEN", "wk-outbound-only")
    monkeypatch.setenv("COLLECTOR_OBSERVE_INGEST_URL", "http://observe.test/v1/traces")
    monkeypatch.setenv("COLLECTOR_FORWARD_POLL_SECONDS", "0.01")
    monkeypatch.setenv("COLLECTOR_FORWARD_BASE_DELAY_SECONDS", "0")
    get_settings.cache_clear()

    captured: dict[str, str] = {}

    async def fake_post(
        self, url: str, *, content: bytes, headers: dict[str, str]
    ) -> httpx.Response:
        captured["authorization"] = headers.get("Authorization", "")
        captured["traceparent"] = headers.get("traceparent", "")
        return httpx.Response(200, request=httpx.Request("POST", url))

    with patch.object(httpx.AsyncClient, "post", new=fake_post):
        app = create_app()
        with TestClient(app) as client:
            resp = client.post(
                "/v1/traces",
                json=_span_payload(),
                headers={
                    "Authorization": "Bearer customer-secret",
                    "traceparent": "00-abc-def-01",
                },
            )
            assert resp.status_code == 200
            import asyncio

            for _ in range(30):
                if captured.get("authorization"):
                    break
                await asyncio.sleep(0.05)
    assert captured["authorization"] == "Bearer wk-outbound-only"
    assert captured["traceparent"] == "00-abc-def-01"
    get_settings.cache_clear()
