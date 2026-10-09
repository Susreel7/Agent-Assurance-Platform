from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from evaluate.app import create_app
from evaluate.config import Settings, reset_settings_cache
from evaluate.db import repository as repo
from evaluate.db.postgres import connect
from evaluate.domains.annotation import service as annotation_service
from evaluate.domains.datasets import service as dataset_service
from evaluate.domains.evaluators import service as evaluator_service
from evaluate.domains.experiments import service as experiment_service
from evaluate.domains.online_rules import service as online_service
from evaluate.domains.release_gate import service as release_gate_service
from evaluate.domains.scores import service as score_service
from evaluate.domains.scores.schemas import ScoreCreate

pytestmark = pytest.mark.integration


@pytest.fixture
def client(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    reset_settings_cache()
    monkeypatch.setattr("evaluate.config.get_settings", lambda: settings)
    monkeypatch.setattr("evaluate.app.get_settings", lambda: settings)
    monkeypatch.setattr("evaluate.api.deps.get_settings", lambda: settings)
    monkeypatch.setattr("evaluate.auth.internal.get_settings", lambda: settings)
    return TestClient(create_app())


def _headers(org_id, project_id) -> dict[str, str]:
    return {
        "Authorization": "Bearer test-internal-token",
        "X-Organization-Id": str(org_id),
        "X-Project-Id": str(project_id),
        "X-Actor": "tester",
    }


def test_read_endpoints_pagination_and_no_inline_leak(
    settings: Settings, client: TestClient
) -> None:
    org_id, project_id = uuid4(), uuid4()
    base = f"/v1/orgs/{org_id}/projects/{project_id}"
    headers = _headers(org_id, project_id)

    with connect(settings.database_url) as conn:
        dataset_service.create_dataset(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            dataset_key="read-demo",
            display_name="Read",
            description="",
            tags=["t"],
            actor="tester",
        )
        rev = dataset_service.create_revision(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            dataset_key="read-demo",
            payload_examples=[
                {
                    "example_key": "e1",
                    "input": {"secret": "do-not-leak"},
                    "reference_output": {"a": 1},
                    "metadata": {"k": "v"},
                }
            ],
            copy_from_revision_id=None,
            actor="tester",
        )
        _, ev_rev = evaluator_service.create_evaluator(
            conn,
            org_id=org_id,
            project_id=project_id,
            evaluator_key="em",
            display_name="",
            kind="exact_match",
            config={"field": "output"},
            actor="tester",
        )
        exp = experiment_service.create_experiment(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            experiment_key="exp-read",
            display_name="",
            spec={
                "dataset_revision_id": str(rev["id"]),
                "evaluator_revision_ids": [str(ev_rev["id"])],
            },
            baseline_experiment_id=None,
            seed=1,
            repetitions=1,
            concurrency=1,
            budget_usd=None,
            actor="tester",
        )
        rule_id = online_service.create_rule(
            conn,
            org_id=org_id,
            project_id=project_id,
            payload={
                "rule_key": "r1",
                "evaluator_revision_ids": [ev_rev["id"]],
                "filter": {},
                "actions": [],
            },
        )
        score_id = score_service.create_score(
            conn,
            org_id=org_id,
            project_id=project_id,
            payload=ScoreCreate(
                target_type="trace",
                target_id="trace-1",
                name="quality",
                value_type="numeric",
                value_numeric=1.0,
                source="automated",
            ),
            actor="tester",
        )

    ds_list = client.get(f"{base}/datasets", headers=headers)
    assert ds_list.status_code == 200
    body = ds_list.json()
    assert body["meta"]["total"] == 1
    assert body["items"][0]["dataset_key"] == "read-demo"

    ds_get = client.get(f"{base}/datasets/read-demo", headers=headers)
    assert ds_get.status_code == 200

    rev_list = client.get(f"{base}/datasets/read-demo/revisions", headers=headers)
    assert rev_list.status_code == 200
    assert rev_list.json()["meta"]["total"] == 1

    rev_get = client.get(
        f"{base}/datasets/read-demo/revisions/{rev['id']}",
        headers=headers,
    )
    assert rev_get.status_code == 200

    ex_resp = client.get(
        f"{base}/datasets/read-demo/revisions/{rev['id']}/examples",
        headers=headers,
    )
    assert ex_resp.status_code == 200
    ex_body = ex_resp.json()
    assert ex_body["meta"]["total"] == 1
    example = ex_body["items"][0]
    example_id = example["id"]
    assert "input_inline" not in example
    assert "ciphertext" not in example
    assert "secret" not in str(example)

    ex_one = client.get(
        f"{base}/datasets/read-demo/revisions/{rev['id']}/examples/{example_id}",
        headers=headers,
    )
    assert ex_one.status_code == 200
    assert "secret" not in str(ex_one.json())

    ex_search = client.get(
        f"{base}/datasets/read-demo/revisions/{rev['id']}/examples?q=e1",
        headers=headers,
    )
    assert ex_search.status_code == 200
    assert ex_search.json()["meta"]["total"] == 1

    ds_search = client.get(f"{base}/datasets?q=read", headers=headers)
    assert ds_search.status_code == 200
    assert ds_search.json()["meta"]["total"] == 1

    exp_list = client.get(f"{base}/experiments", headers=headers)
    assert exp_list.status_code == 200
    assert exp_list.json()["meta"]["total"] == 1

    exp_get = client.get(f"{base}/experiments/{exp['id']}", headers=headers)
    assert exp_get.status_code == 200
    assert "spec" not in exp_get.json()

    exp_by_key = client.get(f"{base}/experiments/by-key/exp-read", headers=headers)
    assert exp_by_key.status_code == 200

    ev_list = client.get(f"{base}/evaluators", headers=headers)
    assert ev_list.status_code == 200
    assert ev_list.json()["meta"]["total"] == 1

    ev_rev_get = client.get(
        f"{base}/evaluators/em/revisions/{ev_rev['id']}",
        headers=headers,
    )
    assert ev_rev_get.status_code == 200
    assert "config" not in ev_rev_get.json()

    scores = client.get(f"{base}/scores?target_type=trace", headers=headers)
    assert scores.status_code == 200
    assert scores.json()["meta"]["total"] >= 1

    score_get = client.get(f"{base}/scores/{score_id}", headers=headers)
    assert score_get.status_code == 200

    rules = client.get(f"{base}/online-rules", headers=headers)
    assert rules.status_code == 200
    assert rules.json()["meta"]["total"] == 1

    rule_get = client.get(f"{base}/online-rules/{rule_id}", headers=headers)
    assert rule_get.status_code == 200

    alerts = client.get(f"{base}/online-rules/alerts", headers=headers)
    assert alerts.status_code == 200
    assert "meta" in alerts.json()

    wrong_org = uuid4()
    assert (
        client.get(
            f"/v1/orgs/{wrong_org}/projects/{project_id}/datasets/read-demo",
            headers=_headers(wrong_org, project_id),
        ).status_code
        == 404
    )

    assert client.get(f"{base}/datasets/missing-dataset", headers=headers).status_code == 404


def test_alerts_annotation_and_release_gate_reads(
    settings: Settings, client: TestClient
) -> None:
    org_id, project_id = uuid4(), uuid4()
    base = f"/v1/orgs/{org_id}/projects/{project_id}"
    headers = _headers(org_id, project_id)

    with connect(settings.database_url) as conn:
        rule_id = online_service.create_rule(
            conn,
            org_id=org_id,
            project_id=project_id,
            payload={
                "rule_key": "alert-rule",
                "evaluator_revision_ids": [],
                "filter": {},
                "actions": [],
            },
        )
        alert_id = repo.enqueue_alert_delivery(
            conn,
            org_id=org_id,
            project_id=project_id,
            rule_id=rule_id,
            action_type="webhook",
            target="https://example.test/hook",
            payload_digest="abc",
            payload={"trace_id": "trace-99", "score": 0.5, "secret_body": "x"},
            idempotency_key=f"idem-{uuid4()}",
            max_attempts=3,
        )
        assert alert_id

    alert_list = client.get(f"{base}/online-rules/alerts", headers=headers)
    assert alert_list.status_code == 200
    assert alert_list.json()["meta"]["total"] == 1
    listed = alert_list.json()["items"][0]
    assert listed["payload_trace_id"] == "trace-99"
    assert "payload" not in listed
    assert "secret_body" not in str(listed)

    alert_get = client.get(f"{base}/online-rules/alerts/{alert_id}", headers=headers)
    assert alert_get.status_code == 200
    assert alert_get.json()["payload_trace_id"] == "trace-99"
    assert "secret_body" not in str(alert_get.json())

    ack = client.post(f"{base}/online-rules/alerts/{alert_id}/acknowledge", headers=headers)
    assert ack.status_code == 200
    assert ack.json()["acknowledged_at"] is not None

    retry = client.post(f"{base}/online-rules/alerts/{alert_id}/retry", headers=headers)
    assert retry.status_code == 200
    assert retry.json()["status"] == "pending"
    assert retry.json()["attempts"] == 0

    with connect(settings.database_url) as conn:
        queue_id = annotation_service.create_queue(
            conn,
            org_id=org_id,
            project_id=project_id,
            queue_key="q1",
            display_name="Q",
            item_filter={},
            rubric={},
            reviewers_required=1,
            actor="tester",
        )
        item_id = annotation_service.add_item(
            conn,
            org_id=org_id,
            project_id=project_id,
            queue_id=queue_id,
            item_type="trace",
            reference_id="trace-1",
            pairwise_reference_id=None,
            metadata={},
        )

    queues = client.get(f"{base}/annotation-queues", headers=headers)
    assert queues.status_code == 200
    assert queues.json()["meta"]["total"] == 1

    queue_get = client.get(f"{base}/annotation-queues/{queue_id}", headers=headers)
    assert queue_get.status_code == 200

    items = client.get(f"{base}/annotation-queues/{queue_id}/items", headers=headers)
    assert items.status_code == 200
    assert items.json()["meta"]["total"] == 1

    item_get = client.get(f"{base}/annotation-queues/items/{item_id}", headers=headers)
    assert item_get.status_code == 200

    with connect(settings.database_url) as conn:
        dataset_service.create_dataset(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            dataset_key="gate-ds",
            display_name="",
            description="",
            tags=[],
            actor="tester",
        )
        gate_rev = dataset_service.create_revision(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            dataset_key="gate-ds",
            payload_examples=[],
            copy_from_revision_id=None,
            actor="tester",
        )
        exp = experiment_service.create_experiment(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            experiment_key="gate-base",
            display_name="",
            spec={
                "dataset_revision_id": str(gate_rev["id"]),
                "evaluator_revision_ids": [],
            },
            baseline_experiment_id=None,
            seed=1,
            repetitions=1,
            concurrency=1,
            budget_usd=None,
            actor="tester",
        )
        gate_id = release_gate_service.create_gate(
            conn,
            org_id=org_id,
            project_id=project_id,
            gate_key="g1",
            baseline_experiment_id=exp["id"],
            thresholds={},
            actor="tester",
        )

    gates = client.get(f"{base}/release-gates", headers=headers)
    assert gates.status_code == 200
    assert gates.json()["meta"]["total"] == 1

    gate_get = client.get(f"{base}/release-gates/{gate_id}", headers=headers)
    assert gate_get.status_code == 200

    eval_hist = client.get(f"{base}/release-gates/{gate_id}/evaluations", headers=headers)
    assert eval_hist.status_code == 200
    assert eval_hist.json()["meta"]["total"] == 0
