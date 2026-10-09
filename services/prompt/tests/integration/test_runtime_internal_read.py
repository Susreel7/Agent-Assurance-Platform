from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from prompt.auth.schemas import WorkloadPrincipal
from prompt.config import Settings, reset_settings_cache
from prompt.db.postgres import connect
from prompt.domains.artifacts import service as artifact_service
from prompt.domains.artifacts.schemas import ArtifactCreate, RevisionCreate
from prompt.domains.labels import service as label_service
from prompt.domains.labels.schemas import PromoteLabelRequest
from prompt.domains.runtime import service as runtime_service


@pytest.fixture
def api_client(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("PROMPT_DATABASE_URL", settings.database_url)
    monkeypatch.setenv("PROMPT_INTERNAL_SERVICE_TOKEN", settings.internal_service_token)
    monkeypatch.setenv("PROMPT_ENCRYPTION_KEYS_JSON", settings.encryption_keys_json)
    monkeypatch.setenv("PROMPT_DEFAULT_ENCRYPTION_KEY_REF", settings.default_encryption_key_ref)
    monkeypatch.setenv("PROMPT_RUN_MIGRATIONS_ON_STARTUP", "false")
    monkeypatch.setenv("PROMPT_INTROSPECTION_URL", settings.introspection_url)
    reset_settings_cache()
    from prompt.app import create_app

    return TestClient(create_app())


def _internal_headers(settings: Settings, org_id, project_id) -> dict[str, str]:  # noqa: ANN001
    return {
        "Authorization": f"Bearer {settings.internal_service_token}",
        "X-Organization-Id": str(org_id),
        "X-Project-Id": str(project_id),
        "X-Actor": "tester",
    }


@pytest.mark.integration
def test_internal_runtime_read_matches_workload_resolution(
    settings: Settings, org_project: tuple, api_client: TestClient
) -> None:
    org_id, project_id = org_project
    with connect(settings.database_url) as conn:
        artifact_service.create_artifact(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            payload=ArtifactCreate(artifact_key="console.read", kind="prompt"),
            actor="tester",
        )
        rev = artifact_service.create_revision(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            artifact_key="console.read",
            payload=RevisionCreate(
                content={"messages": [{"role": "user", "content": "hello"}]},
                is_draft=False,
            ),
            actor="tester",
        )
        label_service.promote_label(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            artifact_key="console.read",
            payload=PromoteLabelRequest(label_name="production", revision_id=rev.id),
            actor="tester",
            scopes=["prompt:label:production"],
        )
        workload = WorkloadPrincipal(
            subject="w",
            organization_id=org_id,
            project_id=project_id,
            modules=["prompt"],
            scopes=["prompt:read"],
        )
        workload_resolved = runtime_service.resolve_runtime_artifact(
            conn,
            settings,
            principal=workload,
            org_id=org_id,
            project_id=project_id,
            artifact_key="console.read",
            label="production",
            revision_id=None,
        )

    path = f"/v1/orgs/{org_id}/projects/{project_id}/runtime/read/artifacts/console.read"
    resp = api_client.get(
        path,
        params={"label": "production"},
        headers=_internal_headers(settings, org_id, project_id),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["revision_id"] == str(workload_resolved.revision_id)
    assert body["content_digest"] == workload_resolved.content_digest
    assert resp.headers["ETag"] == runtime_service.runtime_etag(workload_resolved.content_digest)
    assert resp.headers["X-Content-Digest"] == workload_resolved.content_digest
    assert resp.headers["X-Revision-Id"] == str(workload_resolved.revision_id)


@pytest.mark.integration
def test_internal_runtime_read_if_none_match(
    settings: Settings, org_project: tuple, api_client: TestClient
) -> None:
    org_id, project_id = org_project
    with connect(settings.database_url) as conn:
        artifact_service.create_artifact(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            payload=ArtifactCreate(artifact_key="etag.me", kind="prompt"),
            actor="tester",
        )
        rev = artifact_service.create_revision(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            artifact_key="etag.me",
            payload=RevisionCreate(
                content={"messages": [{"role": "user", "content": "x"}]},
                is_draft=False,
            ),
            actor="tester",
        )

    path = f"/v1/orgs/{org_id}/projects/{project_id}/runtime/read/artifacts/etag.me"
    first = api_client.get(
        path,
        params={"pin_revision_id": str(rev.id)},
        headers=_internal_headers(settings, org_id, project_id),
    )
    assert first.status_code == 200
    digest = first.json()["content_digest"]
    second = api_client.get(
        path,
        params={"pin_revision_id": str(rev.id)},
        headers={
            **_internal_headers(settings, org_id, project_id),
            "If-None-Match": digest,
        },
    )
    assert second.status_code == 304
