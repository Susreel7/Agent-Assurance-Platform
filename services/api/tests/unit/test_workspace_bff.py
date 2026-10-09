"""Control-plane BFF tests for prompt and evaluate workspace proxies."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import httpx
import pytest

from app.config import DeploymentMode, Settings, get_settings
from app.domains.artifact_workspace import service as prompt_bff
from app.domains.modules import service as modules_service
from app.domains.modules.schemas import ModuleCapability
from app.licensing import reset_license_cache


def _license_keypair(tmp_path: Path) -> tuple[Path, Path]:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
        PublicFormat,
    )

    private_key = ec.generate_private_key(ec.SECP256R1())
    private_pem = private_key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    public_pem = private_key.public_key().public_bytes(
        Encoding.PEM, PublicFormat.SubjectPublicKeyInfo
    )
    key_path = tmp_path / "license-key.pem"
    pub_path = tmp_path / "license-pub.pem"
    key_path.write_bytes(private_pem)
    pub_path.write_bytes(public_pem)
    return key_path, pub_path


def _prompt_disabled_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Settings:
    from tests.unit.test_licensing_modules import _license_file

    keypair = _license_keypair(tmp_path)
    lic_path = _license_file(
        tmp_path,
        keypair,
        expires_at=datetime(2030, 1, 1, tzinfo=UTC),
        modules={
            "router": {"enabled": True, "limits": {}},
            "observe": {"enabled": True, "limits": {}},
            "prompt": {"enabled": False, "limits": {}},
            "evaluate": {"enabled": True, "limits": {}},
        },
    )
    _, pub_path = keypair
    settings = Settings(
        deployment_mode=DeploymentMode.BYOC,
        tenancy="single",
        license_file=lic_path,
        license_public_key_path=pub_path,
        environment="development",
        _env_file=None,
    )
    get_settings.cache_clear()
    reset_license_cache()
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.licensing.get_settings", lambda: settings)
    monkeypatch.setattr("app.api.deps.get_settings", lambda: settings)
    return settings


def _settings(**kw: object) -> Settings:
    base: dict[str, object] = {
        "database_url": "postgresql+psycopg://aap:x@localhost:5432/aap",
        "environment": "test",
        "_env_file": None,
        "prompt_service_url": "http://prompt.test",
        "prompt_internal_service_token": "prompt-secret",
        "evaluate_service_url": "http://evaluate.test",
        "evaluate_internal_service_token": "evaluate-secret",
    }
    return Settings(**(base | kw))  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _clear_client_factory() -> None:
    prompt_bff._client_factory = None
    from app.domains.evaluation_workspace import service as evaluate_bff

    evaluate_bff._client_factory = None
    yield
    prompt_bff._client_factory = None
    evaluate_bff._client_factory = None


def test_prompt_service_url_requires_token() -> None:
    with pytest.raises(ValueError, match="PROMPT_SERVICE_URL"):
        _settings(prompt_service_url="http://prompt", prompt_internal_service_token=None)


def test_evaluate_service_url_requires_token() -> None:
    with pytest.raises(ValueError, match="EVALUATE_SERVICE_URL"):
        _settings(evaluate_service_url="http://evaluate", evaluate_internal_service_token=None)


@pytest.mark.asyncio
async def test_prompt_bff_injects_internal_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}
    org_id = UUID("11111111-1111-1111-1111-111111111111")
    project_id = UUID("22222222-2222-2222-2222-222222222222")

    def handler(request: httpx.Request) -> httpx.Response:
        for key, value in request.headers.items():
            captured[key.lower()] = value
        body = {
            "items": [],
            "next_cursor": None,
        }
        return httpx.Response(200, json=body)

    settings = _settings()
    get_settings.cache_clear()
    monkeypatch.setattr("app.config.get_settings", lambda: settings)
    monkeypatch.setattr("app.domains.artifact_workspace.service.get_settings", lambda: settings)
    prompt_bff._client_factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))

    await prompt_bff.list_artifacts(
        org_id,
        project_id,
        actor="reviewer@example.com",
        kind=None,
        query=None,
        label=None,
        cursor=None,
        limit=10,
    )

    assert captured["authorization"] == "Bearer prompt-secret"
    assert captured["x-organization-id"] == str(org_id)
    assert captured["x-project-id"] == str(project_id)
    assert captured["x-actor"] == "reviewer@example.com"
    assert captured["x-internal-roles"] == "console:read"
    assert "x-internal-scopes" not in captured


@pytest.mark.asyncio
async def test_prompt_bff_configure_injects_label_scopes(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}
    org_id = uuid4()
    project_id = uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        for key, value in request.headers.items():
            captured[key.lower()] = value
        return httpx.Response(
            201,
            json={
                "id": str(uuid4()),
                "organization_id": str(org_id),
                "project_id": str(project_id),
                "artifact_key": "demo",
                "kind": "prompt",
                "display_name": "",
                "description": "",
                "tags": [],
                "created_at": datetime.now(tz=UTC).isoformat(),
                "created_by": "actor",
                "updated_at": datetime.now(tz=UTC).isoformat(),
            },
        )

    settings = _settings()
    get_settings.cache_clear()
    monkeypatch.setattr("app.domains.artifact_workspace.service.get_settings", lambda: settings)
    prompt_bff._client_factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))

    from app.domains.artifact_workspace.schemas import ArtifactCreate

    await prompt_bff.create_artifact(
        org_id,
        project_id,
        actor="actor",
        payload=ArtifactCreate(artifact_key="demo", kind="prompt"),
    )

    assert "prompt:label:production" in captured["x-internal-scopes"]
    assert captured["x-internal-roles"] == "console:configure"


@pytest.mark.asyncio
async def test_prompt_bff_refuses_forged_upstream_org(monkeypatch: pytest.MonkeyPatch) -> None:
    """BFF always passes VerifiedOrg into headers — never a browser-supplied org."""
    org_id = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    project_id = uuid4()
    seen_path = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_path
        seen_path = str(request.url)
        assert request.headers["x-organization-id"] == str(org_id)
        return httpx.Response(200, json={"items": [], "next_cursor": None})

    settings = _settings()
    monkeypatch.setattr("app.domains.artifact_workspace.service.get_settings", lambda: settings)
    prompt_bff._client_factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))

    await prompt_bff.list_artifacts(
        org_id,
        project_id,
        actor="actor",
        kind=None,
        query=None,
        label=None,
        cursor=None,
        limit=5,
    )
    assert f"/orgs/{org_id}/projects/{project_id}/" in seen_path


@pytest.mark.asyncio
async def test_prompt_bff_maps_upstream_404(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    monkeypatch.setattr("app.domains.artifact_workspace.service.get_settings", lambda: settings)
    prompt_bff._client_factory = lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _r: httpx.Response(
                404, json={"detail": {"code": "not_found", "message": "missing"}}
            )
        )
    )

    with pytest.raises(prompt_bff.PromptRequestError) as exc:
        await prompt_bff.get_artifact(uuid4(), uuid4(), actor="a", artifact_key="x")
    assert exc.value.status_code == 404
    assert "missing" in str(exc.value)


@pytest.mark.asyncio
async def test_prompt_bff_stream_stops_on_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _settings()
    monkeypatch.setattr("app.domains.artifact_workspace.service.get_settings", lambda: settings)

    def stream_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"event: token\ndata: {}\n\n" * 50)

    prompt_bff._client_factory = lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(stream_handler)
    )

    from app.domains.artifact_workspace.schemas import ArtifactRef, PlaygroundRunRequest

    calls = 0

    async def disconnect() -> bool:
        nonlocal calls
        calls += 1
        return calls > 1

    chunks: list[bytes] = []
    async for chunk in prompt_bff.stream_playground_run(
        uuid4(),
        uuid4(),
        actor="actor",
        payload=PlaygroundRunRequest(
            artifacts=[ArtifactRef(artifact_key="a", label="latest")],
            model_alias="fast",
            stream=True,
        ),
        workload_authorization=None,
        disconnect=disconnect,
    ):
        chunks.append(chunk)

    assert len(chunks) == 1
    assert calls >= 1


@pytest.mark.asyncio
async def test_evaluate_bff_injects_actor_header(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        for key, value in request.headers.items():
            captured[key.lower()] = value
        return httpx.Response(
            201,
            json={
                "id": str(uuid4()),
                "dataset_key": "ds",
                "display_name": "",
                "description": "",
                "tags": [],
                "created_at": datetime.now(tz=UTC).isoformat(),
                "created_by": "actor",
            },
        )

    settings = _settings()
    monkeypatch.setattr("app.domains.evaluation_workspace.service.get_settings", lambda: settings)
    from app.domains.evaluation_workspace import service as evaluate_bff

    evaluate_bff._client_factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))

    from app.domains.evaluation_workspace.schemas import DatasetCreate

    await evaluate_bff.create_dataset(
        uuid4(), uuid4(), actor="human@example.com", payload=DatasetCreate(dataset_key="ds")
    )
    assert captured["authorization"] == "Bearer evaluate-secret"
    assert captured["x-actor"] == "human@example.com"


def test_module_entitlement_blocks_prompt_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _prompt_disabled_settings(monkeypatch, tmp_path)
    with pytest.raises(modules_service.ModuleNotEntitledError):
        modules_service.assert_module_capability("prompt", ModuleCapability.READ)


@pytest.mark.asyncio
async def test_artifacts_route_requires_prompt_entitlement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from httpx import ASGITransport, AsyncClient

    from app.api.deps import Authenticated, assert_org_exists, authenticate, get_session
    from app.auth import Principal
    from app.domains.workload_identity import service as workload_service
    from app.main import create_app

    _prompt_disabled_settings(monkeypatch, tmp_path)

    async def _fake_org() -> UUID:
        return UUID("00000000-0000-0000-0000-000000000001")

    async def _fake_project(*_a: object, **_k: object) -> object:
        class _P:
            id = uuid4()

        return _P()

    monkeypatch.setattr("app.api.deps.resolve_single_tenant_org", _fake_org)
    monkeypatch.setattr(workload_service, "get_project", _fake_project)

    app = create_app()

    async def _fake_session() -> AsyncIterator[object]:
        yield object()

    app.dependency_overrides[get_session] = _fake_session
    app.dependency_overrides[assert_org_exists] = _fake_org
    # Authentication is overridden, not supplied. This test is about the licence refusing
    # a module, and it used to reach the route via the `X-Org-Id` header plus the
    # development bypass — neither of which is a credential any more.
    app.dependency_overrides[authenticate] = lambda: Authenticated(
        principal=Principal(subject="user-1", issuer="https://idp.example", email=None),
        claims={},
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/v1/artifacts/projects/{uuid4()}/artifacts")
    assert response.status_code == 403, response.text
    assert "module_not_entitled" in response.text


@pytest.mark.asyncio
async def test_evaluate_online_event_overwrites_org_from_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
    project_id = uuid4()
    posted: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        posted.update(json.loads(request.content.decode()))
        return httpx.Response(202, json={"job_id": str(uuid4())})

    settings = _settings()
    monkeypatch.setattr("app.domains.evaluation_workspace.service.get_settings", lambda: settings)
    from app.domains.evaluation_workspace import service as evaluate_bff

    evaluate_bff._client_factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))

    from app.domains.evaluation_workspace.schemas import ObserveWebhookEvent

    forged_org = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")
    await evaluate_bff.ingest_online_rule_event(
        org_id,
        project_id,
        actor="actor",
        rule_id=uuid4(),
        event=ObserveWebhookEvent(
            trace_id="t1",
            organization_id=forged_org,
            project_id=project_id,
        ),
    )
    assert posted["organization_id"] == str(org_id)


@pytest.mark.asyncio
async def test_evaluate_bff_list_datasets_maps_upstream_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = uuid4()
    project_id = uuid4()
    seen_url = ""

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal seen_url
        seen_url = str(request.url)
        return httpx.Response(
            200,
            json={
                "items": [],
                "meta": {"total": 0, "limit": 10, "next_cursor": None},
            },
        )

    settings = _settings()
    monkeypatch.setattr("app.domains.evaluation_workspace.service.get_settings", lambda: settings)
    from app.domains.evaluation_workspace import service as evaluate_bff

    evaluate_bff._client_factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))

    page = await evaluate_bff.list_datasets(
        org_id, project_id, actor="reader", q="demo", limit=10, cursor=None
    )
    assert page.meta.total == 0
    assert page.items == []
    assert f"/orgs/{org_id}/projects/{project_id}/datasets" in seen_url
    assert "q=demo" in seen_url


@pytest.mark.asyncio
async def test_evaluate_bff_rejects_paged_contract_with_extra_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    monkeypatch.setattr("app.domains.evaluation_workspace.service.get_settings", lambda: settings)
    from app.domains.evaluation_workspace import service as evaluate_bff

    evaluate_bff._client_factory = lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _r: httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": str(uuid4()),
                            "dataset_key": "ds",
                            "display_name": "",
                            "description": "",
                            "tags": [],
                            "created_at": datetime.now(tz=UTC).isoformat(),
                            "created_by": "x",
                            "unexpected": True,
                        }
                    ],
                    "meta": {"total": 1, "limit": 1, "next_cursor": None},
                },
            )
        )
    )

    with pytest.raises(evaluate_bff.EvaluateUnavailableError, match="invalid contract"):
        await evaluate_bff.list_datasets(uuid4(), uuid4(), actor="a", q=None, limit=1, cursor=None)


@pytest.mark.asyncio
async def test_prompt_bff_runtime_read_forwards_etag_and_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = uuid4()
    project_id = uuid4()
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["if_none_match"] = request.headers.get("if-none-match")
        return httpx.Response(
            200,
            json={
                "artifact_key": "my-prompt",
                "kind": "prompt",
                "revision_id": str(uuid4()),
                "revision_number": 1,
                "label": "production",
                "pinned_revision": False,
                "content_digest": "abc",
                "schema_digest": None,
                "config_digest": None,
                "content": {"messages": []},
                "input_schema": None,
                "config": None,
                "resolved_at": datetime.now(tz=UTC).isoformat(),
            },
            headers={"ETag": '"abc"', "Cache-Control": "private, max-age=60"},
        )

    settings = _settings()
    monkeypatch.setattr("app.domains.artifact_workspace.service.get_settings", lambda: settings)
    prompt_bff._client_factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))

    result = await prompt_bff.read_runtime_artifact(
        org_id,
        project_id,
        actor="runtime-reader",
        artifact_key="my-prompt",
        label="production",
        revision_id=None,
        pin_revision_id=None,
        if_none_match='"abc"',
    )
    assert result.status_code == 200
    assert result.body is not None
    assert result.body.artifact_key == "my-prompt"
    assert result.headers.get("etag") == '"abc"'
    url = str(seen["url"])
    assert "/runtime/read/artifacts/my-prompt" in url
    assert "label=production" in url
    assert seen["if_none_match"] == '"abc"'


@pytest.mark.asyncio
async def test_prompt_bff_runtime_read_propagates_304(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    monkeypatch.setattr("app.domains.artifact_workspace.service.get_settings", lambda: settings)
    prompt_bff._client_factory = lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _r: httpx.Response(304, headers={"ETag": '"unchanged"'})
        )
    )

    result = await prompt_bff.read_runtime_artifact(
        uuid4(),
        uuid4(),
        actor="a",
        artifact_key="k",
        label=None,
        revision_id=None,
        pin_revision_id=None,
        if_none_match='"unchanged"',
    )
    assert result.status_code == 304
    assert result.body is None
    assert result.headers.get("etag") == '"unchanged"'


@pytest.mark.asyncio
async def test_workload_score_bridge_forwards_bearer_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    org_id = UUID("dddddddd-dddd-dddd-dddd-dddddddddddd")
    project_id = UUID("eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee")
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers.get("authorization")
        lowered = {k.lower() for k in request.headers}
        assert "x-actor" not in lowered
        assert "x-organization-id" not in lowered
        assert "x-project-id" not in lowered
        assert "x-internal-roles" not in lowered
        return httpx.Response(
            201,
            json={
                "id": str(uuid4()),
                "target_type": "trace",
                "target_id": "t1",
                "name": "quality",
                "value_type": "numeric",
                "source": "automated",
                "created_at": datetime.now(tz=UTC).isoformat(),
                "created_by": "workload:agent",
            },
        )

    settings = _settings()
    monkeypatch.setattr("app.domains.evaluation_workspace.service.get_settings", lambda: settings)
    from app.domains.evaluation_workspace import service as evaluate_bff

    evaluate_bff._client_factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))

    from app.domains.evaluation_workspace.schemas import ScoreCreate

    bearer = "Bearer aap_wk_test-token"
    out = await evaluate_bff.create_workload_score(
        org_id,
        project_id,
        authorization=bearer,
        payload=ScoreCreate(
            target_type="trace",
            target_id="t1",
            name="quality",
            value_type="numeric",
            value_numeric=0.9,
            source="automated",
        ),
    )
    assert out.name == "quality"
    assert captured["authorization"] == bearer
    url = str(captured["url"])
    assert f"/orgs/{org_id}/projects/{project_id}/scores/workload" in url


@pytest.mark.asyncio
async def test_workload_score_bridge_rejects_invalid_upstream_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _settings()
    monkeypatch.setattr("app.domains.evaluation_workspace.service.get_settings", lambda: settings)
    from app.domains.evaluation_workspace import service as evaluate_bff

    evaluate_bff._client_factory = lambda: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _r: httpx.Response(201, json={"unexpected": True}))
    )

    from app.domains.evaluation_workspace.schemas import ScoreCreate

    with pytest.raises(evaluate_bff.EvaluateUnavailableError, match="invalid contract"):
        await evaluate_bff.create_workload_score(
            uuid4(),
            uuid4(),
            authorization="Bearer aap_wk_x",
            payload=ScoreCreate(
                target_type="trace",
                target_id="t1",
                name="quality",
                value_type="numeric",
                value_numeric=1.0,
                source="automated",
            ),
        )
