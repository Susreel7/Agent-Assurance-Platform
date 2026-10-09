from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from google.protobuf import json_format

from observe.auth.schemas import WorkloadPrincipal
from observe.config import CaptureMode, Settings, reset_settings_cache
from observe.ingest.app import create_app
from observe.providers.object_store.base import LocalObjectStore
from tests.unit.test_otlp import _sample_request


@pytest.fixture
def ingest_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    org = uuid4()
    project = uuid4()
    root = tmp_path / "obj"
    root.mkdir()
    settings = Settings(
        database_url="postgresql://127.0.0.1:1/none",
        run_migrations_on_startup=False,
        object_store_root=str(root),
        introspection_url="http://test/introspect",
    )
    reset_settings_cache()
    monkeypatch.setattr("observe.ingest.app.get_settings", lambda: settings)

    async def fake_introspect(_settings, authorization: str | None):  # noqa: ANN001
        return WorkloadPrincipal(
            subject=str(uuid4()),
            organization_id=org,
            project_id=project,
            modules=["observe"],
            scopes=["observe:ingest"],
            capture_mode=CaptureMode.DIGEST,
            payload_retention_days=30,
        )

    monkeypatch.setattr("observe.ingest.app.workload_auth.introspect_bearer", fake_introspect)

    class FakeConn:
        def cursor(self):  # noqa: ANN001
            return self

        def __enter__(self):  # noqa: ANN001
            return self

        def __exit__(self, *args):  # noqa: ANN001
            return False

        def execute(self, *args, **kwargs):  # noqa: ANN001
            return None

        def fetchone(self):  # noqa: ANN001
            return None

        def fetchall(self):  # noqa: ANN001
            return []

        def commit(self):  # noqa: ANN001
            return None

    def fake_connect(_url: str, **_context: object):  # noqa: ANN001
        from contextlib import contextmanager

        @contextmanager
        def cm():
            yield FakeConn()

        return cm()

    monkeypatch.setattr("observe.ingest.service.pg.connect", fake_connect)
    monkeypatch.setattr("observe.ingest.service.repo.get_manifest_by_digest", lambda *a, **k: None)
    monkeypatch.setattr(
        "observe.ingest.service.repo.insert_manifest",
        lambda *a, **k: uuid4(),
    )
    monkeypatch.setattr("observe.ingest.service.publish_ingest_wake", lambda *a, **k: None)

    store = LocalObjectStore(root)
    monkeypatch.setattr("observe.ingest.app.build_object_store", lambda _s: store)

    return TestClient(create_app())


def test_ingest_json_otlp(ingest_client: TestClient) -> None:
    req = _sample_request()
    body = json_format.MessageToJson(req).encode("utf-8")
    resp = ingest_client.post(
        "/v1/traces",
        content=body,
        headers={
            "Authorization": "Bearer test",
            "Content-Type": "application/json",
        },
    )
    assert resp.status_code == 200
    assert resp.json() == {}


def test_healthz(ingest_client: TestClient) -> None:
    assert ingest_client.get("/healthz").json()["status"] == "alive"
