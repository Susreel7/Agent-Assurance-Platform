from __future__ import annotations

import json

import httpx
import pytest

from aap_trace.config import TraceConfig
from aap_trace.scores import ScoreClient, ScoreRecord

_RealHttpxClient = httpx.Client


def test_score_client_posts_evaluate_workload_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["json"] = json.loads(request.content.decode())
        return httpx.Response(201, json={"id": "00000000-0000-0000-0000-000000000001"})

    transport = httpx.MockTransport(handler)

    def fake_client(**kwargs: object) -> httpx.Client:
        kwargs["transport"] = transport
        return _RealHttpxClient(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("aap_trace.scores.httpx.Client", fake_client)

    config = TraceConfig(
        endpoint="https://observe.example/v1/traces",
        bearer_token="secret",
        organization_id="o",
        project_id="p",
        score_base_url="https://control.example",
    )
    ScoreClient(config).submit(
        ScoreRecord(name="quality", value=0.9, trace_id="trace-1", comment="ok")
    )

    assert captured["url"] == "https://control.example/v1/evaluate/workload/scores"
    assert captured["json"] == {
        "target_type": "trace",
        "target_id": "trace-1",
        "name": "quality",
        "value_type": "numeric",
        "value_numeric": 0.9,
        "source": "human",
        "explanation": "ok",
    }


def test_score_client_defaults_base_from_trace_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(201, json={})

    transport = httpx.MockTransport(handler)

    def fake_client(**kwargs: object) -> httpx.Client:
        kwargs["transport"] = transport
        return _RealHttpxClient(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("aap_trace.scores.httpx.Client", fake_client)

    config = TraceConfig(
        endpoint="https://gateway.example/v1/traces",
        bearer_token="secret",
        organization_id="o",
        project_id="p",
    )
    ScoreClient(config).submit(ScoreRecord(name="n", value=1.0, span_id="span-1"))

    assert captured["url"] == "https://gateway.example/v1/evaluate/workload/scores"


def test_from_otel_env_reads_score_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "https://observe/v1/traces")
    monkeypatch.setenv("AAP_WORKLOAD_TOKEN", "t")
    monkeypatch.setenv("AAP_ORGANIZATION_ID", "o")
    monkeypatch.setenv("AAP_PROJECT_ID", "p")
    monkeypatch.setenv("AAP_SCORE_BASE_URL", "https://control.example")
    cfg = TraceConfig.from_otel_env()
    assert cfg.score_base_url == "https://control.example"
