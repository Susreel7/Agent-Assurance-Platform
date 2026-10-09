from __future__ import annotations

from uuid import uuid4

import pytest

from evaluate.clients.observe import ObserveClient
from evaluate.config import Settings
from evaluate.db import repository as repo
from evaluate.db.postgres import connect
from evaluate.domains.evaluators import service as evaluator_service
from evaluate.domains.online_rules import service as online_service
from evaluate.worker.alert_dispatch import process_alert_batch, schedule_webhook_action
from evaluate.worker.observe_poller import poll_observe_for_project
from evaluate.worker.online_eval import process_online_eval_job

pytestmark = pytest.mark.integration


@pytest.fixture
def org_project() -> tuple:
    return uuid4(), uuid4()


@pytest.mark.asyncio
async def test_process_online_eval_scores_trace_and_schedules_webhook(
    settings: Settings, org_project: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    org_id, project_id = org_project
    trace_id = "trace-online-1"
    webhook_url = "https://hooks.test/eval"

    with connect(settings.database_url) as conn:
        _, ev_rev = evaluator_service.create_evaluator(
            conn,
            org_id=org_id,
            project_id=project_id,
            evaluator_key="out-regex",
            display_name="",
            kind="regex",
            config={"pattern": "expected-output"},
            actor="tester",
        )
        rule_id = online_service.create_rule(
            conn,
            org_id=org_id,
            project_id=project_id,
            payload={
                "rule_key": "full-online",
                "sample_rate": 1.0,
                "sample_hash_salt": "salt",
                "evaluator_revision_ids": [str(ev_rev["id"])],
                "budget_usd": 10.0,
                "max_concurrency": 2,
                "actions": [{"type": "webhook", "url": webhook_url}],
            },
        )
        job_id = online_service.ingest_trace_event(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            rule_id=rule_id,
            trace_id=trace_id,
            metadata={"environment": "prod"},
        )
        assert job_id is not None

    async def fake_trace_summary(self: ObserveClient, **kwargs: object) -> dict[str, object]:
        return {
            "output": "expected-output",
            "input": "question",
            "root_span_id": "span-root-9",
            "latency_ms": 12,
        }

    monkeypatch.setattr(ObserveClient, "get_trace_summary", fake_trace_summary)

    await process_online_eval_job(
        settings,
        {"online_job_id": str(job_id), "rule_id": str(rule_id)},
    )

    with connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, span_id FROM evaluate.online_eval_jobs WHERE id = %s",
                (job_id,),
            )
            job_row = cur.fetchone()
            assert job_row["status"] == "completed"
            assert job_row["span_id"] == "span-root-9"
            cur.execute(
                """
                SELECT value_numeric FROM evaluate.scores
                WHERE organization_id = %s AND target_id = %s AND name = %s
                """,
                (org_id, trace_id, "out-regex"),
            )
            score = cur.fetchone()
            assert score is not None
            assert float(score["value_numeric"]) == 1.0
            cur.execute(
                """
                SELECT status FROM evaluate.alert_deliveries
                WHERE organization_id = %s AND target = %s
                """,
                (org_id, webhook_url),
            )
            alert = cur.fetchone()
            assert alert is not None
            assert alert["status"] == "pending"


@pytest.mark.asyncio
async def test_observe_poller_updates_cursor_and_idempotent_jobs(
    settings: Settings, org_project: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    org_id, project_id = org_project

    with connect(settings.database_url) as conn:
        rule_id = online_service.create_rule(
            conn,
            org_id=org_id,
            project_id=project_id,
            payload={
                "rule_key": "poll-rule",
                "sample_rate": 1.0,
                "sample_hash_salt": "poll",
                "evaluator_revision_ids": [],
                "actions": [],
            },
        )

    events_payload = {
        "events": [
            {"trace_id": "poll-trace-1", "metadata": {}},
            {"trace_id": "poll-trace-1", "metadata": {}},
        ],
        "next_cursor": "cursor-v2",
    }

    async def fake_poll(self: ObserveClient, **kwargs: object) -> dict[str, object]:
        return events_payload

    monkeypatch.setattr(ObserveClient, "poll_events", fake_poll)

    enqueued = await poll_observe_for_project(settings, org_id=org_id, project_id=project_id)
    assert enqueued == 1

    with connect(settings.database_url) as conn:
        cursor = repo.get_observe_cursor(conn, org_id, project_id)
        assert cursor == "cursor-v2"
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) AS c FROM evaluate.online_eval_jobs
                WHERE rule_id = %s AND trace_id = %s
                """,
                (rule_id, "poll-trace-1"),
            )
            assert cur.fetchone()["c"] == 1


def test_online_rate_limit_per_hour(settings: Settings, org_project: tuple) -> None:
    org_id, project_id = org_project
    with connect(settings.database_url) as conn:
        rule_id = online_service.create_rule(
            conn,
            org_id=org_id,
            project_id=project_id,
            payload={
                "rule_key": "rate-cap",
                "sample_rate": 1.0,
                "sample_hash_salt": "r",
                "evaluator_revision_ids": [],
                "filter": {"max_jobs_per_hour": 1},
                "actions": [],
            },
        )
        first = online_service.ingest_trace_event(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            rule_id=rule_id,
            trace_id="rate-1",
            metadata={},
        )
        second = online_service.ingest_trace_event(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            rule_id=rule_id,
            trace_id="rate-2",
            metadata={},
        )
        assert first is not None
        assert second is None


@pytest.mark.asyncio
async def test_alert_dispatch_delivers_and_marks_dead(
    settings: Settings, org_project: tuple, monkeypatch: pytest.MonkeyPatch
) -> None:
    org_id, project_id = org_project
    target = "https://hooks.test/alert"

    with connect(settings.database_url) as conn:
        schedule_webhook_action(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            rule_id=None,
            target=target,
            payload={"trace_id": "t1", "scores": {"k": 1}},
            idempotency_key="alert:test:1",
        )

    calls: list[str] = []

    payloads: list[dict] = []

    async def ok_webhook(settings_arg: Settings, *, target: str, payload: dict) -> None:
        calls.append(target)
        payloads.append(payload)

    monkeypatch.setattr(
        "evaluate.worker.alert_dispatch.deliver_webhook",
        ok_webhook,
    )
    await process_alert_batch(settings, limit=5)
    assert target in calls
    with connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status FROM evaluate.alert_deliveries
                WHERE organization_id = %s AND idempotency_key = %s
                """,
                (org_id, "alert:test:1"),
            )
            delivered = cur.fetchone()
            assert delivered is not None
            assert delivered["status"] == "delivered"
    matching = [p for p in payloads if p.get("trace_id") == "t1"]
    assert matching and matching[0].get("scores") == {"k": 1}

    settings_fail = settings.model_copy(update={"worker_max_attempts": 1})
    with connect(settings.database_url) as conn:
        schedule_webhook_action(
            conn,
            settings_fail,
            org_id=org_id,
            project_id=project_id,
            rule_id=None,
            target=target,
            payload={"trace_id": "t2"},
            idempotency_key="alert:test:2",
        )

    async def fail_webhook(settings_arg: Settings, *, target: str, payload: dict) -> None:
        raise RuntimeError("webhook status 503")

    monkeypatch.setattr(
        "evaluate.worker.alert_dispatch.deliver_webhook",
        fail_webhook,
    )
    await process_alert_batch(settings_fail, limit=10, organization_id=org_id)
    with connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT status FROM evaluate.alert_deliveries
                WHERE organization_id = %s AND idempotency_key = %s
                """,
                (org_id, "alert:test:2"),
            )
            row = cur.fetchone()
    assert row is not None
    assert row["status"] == "dead"
