from __future__ import annotations

import json
from uuid import uuid4

import pytest

from prompt.config import Settings
from prompt.domains.playground import service as playground_service


@pytest.mark.asyncio
async def test_router_sync_tool_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(router_base_url="http://router.test")

    async def fake_call(_settings, *, workload_bearer, body, stream):  # noqa: ANN001
        assert body.get("tools") is not None
        assert stream is False
        payload = {"choices": [{"message": {"role": "assistant", "content": "ok"}}]}
        return (
            200,
            {"x-request-id": "abc", "x-aap-route-reason": "primary"},
            json.dumps(payload).encode(),
        )

    monkeypatch.setattr(playground_service, "_call_router", fake_call)
    body = {
        "model": "m",
        "messages": [{"role": "user", "content": "hi"}],
        "tools": [{"type": "function", "function": {"name": "fn", "parameters": {}}}],
    }
    status, headers, raw = await playground_service._call_router(
        settings, workload_bearer="tok", body=body, stream=False
    )
    assert status == 200
    assert headers["x-aap-route-reason"] == "primary"
    assert json.loads(raw.decode())["choices"]


@pytest.mark.asyncio
async def test_router_stream_and_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = Settings(router_base_url="http://router.test")
    calls = {"n": 0}

    async def flaky_call(_settings, *, workload_bearer, body, stream):  # noqa: ANN001
        calls["n"] += 1
        if calls["n"] == 1:
            return 429, {"x-request-id": "r1"}, b'{"error":"rate"}'
        return 200, {"x-request-id": "r2"}, b"data: {}\n\n"

    monkeypatch.setattr(playground_service, "_call_router", flaky_call)
    s1, _, _ = await playground_service._call_router(
        settings, workload_bearer=None, body={"model": "m", "messages": []}, stream=False
    )
    s2, _, raw = await playground_service._call_router(
        settings, workload_bearer=None, body={"model": "m", "messages": []}, stream=True
    )
    assert s1 == 429
    assert s2 == 200
    assert b"data:" in raw


def test_request_rejects_stream_with_compare_mode() -> None:
    from pydantic import ValidationError

    from prompt.domains.playground.schemas import ArtifactRef, PlaygroundRunRequest

    with pytest.raises(ValidationError, match="mode=sync"):
        PlaygroundRunRequest(
            mode="compare",
            stream=True,
            artifacts=[ArtifactRef(revision_id=uuid4()), ArtifactRef(revision_id=uuid4())],
            model_alias="m",
        )
