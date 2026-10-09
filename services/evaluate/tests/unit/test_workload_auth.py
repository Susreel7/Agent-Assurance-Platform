from __future__ import annotations

import httpx
import pytest

from evaluate.auth.workload import introspect_bearer
from evaluate.config import Settings
from evaluate.errors import AuthorizationError

_RealAsyncClient = httpx.AsyncClient


@pytest.mark.asyncio
async def test_introspect_bearer_requires_evaluate_score_for_workload_scores(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        introspection_url="http://introspect.test/v1/workload-credentials/-/introspect",
        required_workload_module="evaluate",
        required_workload_scope="evaluate:write",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("authorization") == "Bearer token-1"
        return httpx.Response(
            200,
            json={
                "active": True,
                "subject": "workload:agent",
                "organization_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                "project_id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
                "modules": ["evaluate"],
                "scopes": ["evaluate:write"],
            },
        )

    transport = httpx.MockTransport(handler)

    def fake_async_client(**kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return _RealAsyncClient(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("evaluate.auth.workload.httpx.AsyncClient", fake_async_client)

    with pytest.raises(AuthorizationError, match="missing evaluate scope"):
        await introspect_bearer(
            settings, "Bearer token-1", required_scope="evaluate:score"
        )


@pytest.mark.asyncio
async def test_introspect_bearer_accepts_evaluate_score_when_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        introspection_url="http://introspect.test/v1/workload-credentials/-/introspect",
    )

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "active": True,
                "subject": "workload:agent",
                "organization_id": "dddddddd-dddd-dddd-dddd-dddddddddddd",
                "project_id": "eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee",
                "modules": ["evaluate"],
                "scopes": ["evaluate:score"],
            },
        )

    transport = httpx.MockTransport(handler)

    def fake_async_client(**kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = transport
        return _RealAsyncClient(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr("evaluate.auth.workload.httpx.AsyncClient", fake_async_client)

    principal = await introspect_bearer(
        settings, "Bearer token-1", required_scope="evaluate:score"
    )
    assert principal.subject == "workload:agent"
