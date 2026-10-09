from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from observe.config import Settings
from observe.providers.object_store.base import LocalObjectStore
from observe.worker import retention


def test_retention_sweep_deletes_shared_object_once(
    monkeypatch,
    tmp_path: Path,
) -> None:
    store = LocalObjectStore(tmp_path)
    key = "org/project/payloads/aa/payload.enc"
    store.put(key, b"encrypted", "application/octet-stream")
    org_id = uuid4()
    project_id = uuid4()
    fake_conn = object()
    marked: list[str] = []

    @contextmanager
    def fake_connect(*_args, **_kwargs):
        yield fake_conn

    monkeypatch.setattr(retention.pg, "connect", fake_connect)
    monkeypatch.setattr(
        retention.repo,
        "claim_expired_payload_objects",
        lambda _conn, *, limit: [
            {
                "organization_id": org_id,
                "project_id": project_id,
                "object_key": key,
            },
            {
                "organization_id": org_id,
                "project_id": project_id,
                "object_key": key,
            },
        ],
    )

    def mark(_conn, *, org_id, project_id, object_key):
        assert org_id is not None and project_id is not None
        marked.append(object_key)
        return 2

    monkeypatch.setattr(retention.repo, "mark_payload_object_retention_deleted", mark)
    deleted = retention.sweep_expired_payloads(Settings(), store, limit=10)

    assert deleted == 2
    assert marked == [key]
    assert not store.exists(key)


def test_air_gap_rejects_external_projection_endpoint() -> None:
    with pytest.raises(ValidationError):
        Settings(
            air_gap_mode=True,
            operations_projection_url="https://external.example/v1/runs",
        )
