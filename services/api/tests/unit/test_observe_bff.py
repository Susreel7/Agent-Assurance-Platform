"""Contract tests for the authenticated Observe control-plane boundary."""

from __future__ import annotations

from uuid import UUID, uuid4

import httpx
import pytest

from app.config import Settings
from app.domains.observe import service


def _settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://aap:x@localhost:5432/aap",
        environment="test",
        observe_query_url="http://observe.test",
        observe_internal_service_token="observe-secret",
        _env_file=None,
    )


def _install_transport(
    monkeypatch: pytest.MonkeyPatch,
    handler: httpx.MockTransport,
) -> None:
    client_type = httpx.AsyncClient

    def client_factory(*args: object, **kwargs: object) -> httpx.AsyncClient:
        kwargs["transport"] = handler
        return client_type(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(service.httpx, "AsyncClient", client_factory)
    monkeypatch.setattr(service, "get_settings", _settings)


@pytest.mark.asyncio
async def test_execution_query_is_tenant_scoped_and_typed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = UUID("11111111-1111-1111-1111-111111111111")
    project_id = UUID("22222222-2222-2222-2222-222222222222")
    captured: httpx.Request | None = None

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "execution_id": "exec-1",
                        "execution_type": "agent",
                        "trace_id": "a" * 32,
                        "status": "succeeded",
                        "node_count": 3,
                        "sdk_count": 1,
                    }
                ],
                "limit": 25,
                "offset": 0,
                "total": 1,
            },
        )

    _install_transport(monkeypatch, httpx.MockTransport(respond))
    result = await service.list_executions(
        org_id,
        project_id,
        limit=25,
        offset=0,
        initiating_user_id="user-1",
        status="succeeded",
    )

    assert result.items[0].execution_id == "exec-1"
    assert result.items[0].sdk_count == 1
    assert captured is not None
    assert captured.headers["authorization"] == "Bearer observe-secret"
    assert captured.url.params["organization_id"] == str(org_id)
    assert captured.url.params["project_id"] == str(project_id)
    assert captured.url.params["initiating_user_id"] == "user-1"


@pytest.mark.asyncio
async def test_trace_query_forwards_verified_user_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = uuid4()
    project_id = uuid4()
    captured: httpx.Request | None = None

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return httpx.Response(
            200,
            json={"items": [], "limit": 50, "offset": 0, "total": 0},
        )

    _install_transport(monkeypatch, httpx.MockTransport(respond))
    await service.list_traces(
        org_id,
        project_id,
        limit=50,
        offset=0,
        filters={"initiating_user_id": "entra-user-1"},
    )

    assert captured is not None
    assert captured.url.params["initiating_user_id"] == "entra-user-1"


@pytest.mark.asyncio
async def test_payload_content_forwards_human_actor_for_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload_id = uuid4()
    captured: httpx.Request | None = None

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        captured = request
        return httpx.Response(
            200,
            json={
                "payload_id": str(payload_id),
                "media_type": "application/json",
                "byte_size": 2,
                "redaction_state": "redacted",
                "content_base64": "e30=",
            },
        )

    _install_transport(monkeypatch, httpx.MockTransport(respond))
    result = await service.get_payload_content(
        uuid4(),
        uuid4(),
        payload_id,
        actor_subject="reviewer@example.com",
    )

    assert result.payload_id == payload_id
    assert captured is not None
    assert captured.headers["x-actor-subject"] == "reviewer@example.com"
