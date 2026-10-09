from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest

from prompt.config import Settings
from prompt.db import repository as repo
from prompt.db.postgres import connect
from prompt.domains.playground.cancel_coordinator import StreamCancelCoordinator
from prompt.domains.playground.redis_cancel import publish_cancel


@pytest.mark.asyncio
async def test_publish_cancel_no_redis() -> None:
    assert await publish_cancel(Settings(redis_url=None), uuid4()) is False


@pytest.mark.asyncio
async def test_redis_signal_from_other_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    org_id, project_id, run_id = uuid4(), uuid4(), uuid4()
    settings = Settings(
        redis_url="redis://example:6379/0",
        playground_cancel_redis_poll_seconds=0.05,
        playground_cancel_db_poll_seconds=5.0,
        database_url="postgresql://unused",
    )
    coordinator = StreamCancelCoordinator(
        settings, org_id=org_id, project_id=project_id, run_id=run_id
    )

    async def fake_watch_redis(self: StreamCancelCoordinator) -> None:
        assert self._event is not None
        await asyncio.sleep(0.05)
        self._event.set()

    monkeypatch.setattr(StreamCancelCoordinator, "_watch_redis", fake_watch_redis)
    await coordinator.start()
    try:
        for _ in range(20):
            if coordinator.cancelled():
                break
            await asyncio.sleep(0.05)
        assert coordinator.cancelled()
    finally:
        await coordinator.stop()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_postgres_reconciler_on_signal_loss(settings: Settings, org_project: tuple) -> None:
    org_id, project_id = org_project
    with connect(settings.database_url) as conn:
        run_id = repo.insert_playground_run(
            conn,
            org_id=org_id,
            project_id=project_id,
            mode="stream",
            status="running",
            resolved_revision_ids=[],
            model_alias="m",
            variables={},
            created_by="tester",
        )

    poll_settings = settings.model_copy(update={"playground_cancel_db_poll_seconds": 0.05})
    coordinator = StreamCancelCoordinator(
        poll_settings, org_id=org_id, project_id=project_id, run_id=run_id
    )
    await coordinator.start()
    try:
        with connect(settings.database_url) as conn:
            repo.update_playground_run_status(
                conn,
                org_id=org_id,
                project_id=project_id,
                run_id=run_id,
                status="cancel_requested",
                error_message="cancel requested",
            )
        for _ in range(50):
            if coordinator.cancelled():
                break
            await asyncio.sleep(0.05)
        assert coordinator.cancelled()
    finally:
        await coordinator.stop()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_cancel_endpoint_durable_without_local_stream(
    settings: Settings, org_project: tuple
) -> None:
    from prompt.domains.playground import service as playground_service

    org_id, project_id = org_project
    with connect(settings.database_url) as conn:
        run_id = repo.insert_playground_run(
            conn,
            org_id=org_id,
            project_id=project_id,
            mode="sync",
            status="running",
            resolved_revision_ids=[],
            model_alias="m",
            variables={},
            created_by="tester",
        )
        accepted = await playground_service.cancel_playground_run(
            conn, settings, org_id, project_id, run_id
        )
        assert accepted is True
        row = repo.get_playground_run(conn, org_id, project_id, run_id)
        assert row is not None
        assert row["status"] == "cancel_requested"
