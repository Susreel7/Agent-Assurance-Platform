from __future__ import annotations

from uuid import uuid4

import httpx
import pytest

from evaluate.config import Settings
from evaluate.db.postgres import connect
from evaluate.domains.annotation import service as annotation_service
from evaluate.domains.datasets import service as dataset_service
from evaluate.domains.evaluators import service as evaluator_service
from evaluate.domains.experiments import service as experiment_service
from evaluate.domains.online_rules import service as online_service
from evaluate.domains.scores import service as score_service
from evaluate.domains.scores.schemas import ScoreCreate
from evaluate.errors import ConflictError, NotFoundError, ValidationError
from evaluate.util import digest_json

pytestmark = pytest.mark.integration


@pytest.fixture
def org_project() -> tuple:
    return uuid4(), uuid4()


def test_dataset_immutability_and_encryption(settings: Settings, org_project: tuple) -> None:
    org_id, project_id = org_project
    with connect(settings.database_url) as conn:
        dataset_service.create_dataset(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            dataset_key="demo",
            display_name="Demo",
            description="",
            tags=[],
            actor="tester",
        )
        rev1 = dataset_service.create_revision(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            dataset_key="demo",
            payload_examples=[
                {
                    "example_key": "e1",
                    "input": {"q": "hello"},
                    "reference_output": {"a": "world"},
                    "metadata": {},
                }
            ],
            copy_from_revision_id=None,
            actor="tester",
        )
        rev2 = dataset_service.create_revision(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            dataset_key="demo",
            payload_examples=[],
            copy_from_revision_id=rev1["id"],
            actor="tester",
        )
        assert rev2["revision_number"] == rev1["revision_number"] + 1
        large = {"blob": "x" * (settings.inline_content_max_bytes + 10)}
        rev3 = dataset_service.create_revision(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            dataset_key="demo",
            payload_examples=[{"example_key": "big", "input": large, "metadata": {}}],
            copy_from_revision_id=None,
            actor="tester",
        )
        from evaluate.db import repository as repo

        examples = repo.list_examples_for_revision(conn, org_id, rev3["id"])
        assert examples[0]["has_encrypted_payload"] is True


def test_cross_tenant_isolation(settings: Settings, org_project: tuple) -> None:
    org_id, project_id = org_project
    other = uuid4()
    with connect(settings.database_url) as conn:
        dataset_service.create_dataset(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            dataset_key="tenant",
            display_name="",
            description="",
            tags=[],
            actor="tester",
        )
        with pytest.raises(NotFoundError):
            dataset_service.export_revision_jsonl(conn, other, uuid4())


def test_experiment_pinning_and_cancel(settings: Settings, org_project: tuple) -> None:
    org_id, project_id = org_project
    with connect(settings.database_url) as conn:
        dataset_service.create_dataset(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            dataset_key="exp-data",
            display_name="",
            description="",
            tags=[],
            actor="tester",
        )
        rev = dataset_service.create_revision(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            dataset_key="exp-data",
            payload_examples=[{"example_key": "1", "input": {"x": 1}, "metadata": {}}],
            copy_from_revision_id=None,
            actor="tester",
        )
        spec = {
            "dataset_revision_id": str(rev["id"]),
            "evaluator_revision_ids": [],
            "model_route_alias": "mock",
        }
        exp = experiment_service.create_experiment(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            experiment_key="run-1",
            display_name="",
            spec=spec,
            baseline_experiment_id=None,
            seed=42,
            repetitions=1,
            concurrency=1,
            budget_usd=None,
            actor="tester",
        )
        assert exp["spec_digest"] == digest_json(spec)
        experiment_service.start_experiment(
            conn, settings, org_id=org_id, project_id=project_id, experiment_id=exp["id"]
        )
        cancelled = experiment_service.cancel_experiment(conn, org_id, project_id, exp["id"])
        assert cancelled["status"] == "cancelled"


def test_score_correction_audit(settings: Settings, org_project: tuple) -> None:
    org_id, project_id = org_project
    with connect(settings.database_url) as conn:
        sid = score_service.create_score(
            conn,
            org_id=org_id,
            project_id=project_id,
            payload=ScoreCreate(
                target_type="trace",
                target_id="t-1",
                name="quality",
                value_type="numeric",
                value_numeric=0.5,
                source="automated",
            ),
            actor="tester",
        )
        cid = score_service.correct_score(
            conn,
            org_id=org_id,
            project_id=project_id,
            original_score_id=sid,
            payload=ScoreCreate(
                target_type="trace",
                target_id="t-1",
                name="quality",
                value_type="numeric",
                value_numeric=0.9,
                source="human",
            ),
            reason="label fix",
            actor="reviewer",
        )
        assert cid != sid
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS c FROM evaluate.score_corrections WHERE original_score_id = %s",
                (sid,),
            )
            assert cur.fetchone()["c"] == 1


def test_online_sampling_and_budget(settings: Settings, org_project: tuple) -> None:
    org_id, project_id = org_project
    with connect(settings.database_url) as conn:
        rule_id = online_service.create_rule(
            conn,
            org_id=org_id,
            project_id=project_id,
            payload={
                "rule_key": "sample",
                "sample_rate": 1.0,
                "sample_hash_salt": "fixed",
                "evaluator_revision_ids": [],
                "budget_usd": 0.0,
                "max_concurrency": 1,
                "actions": [],
            },
        )
        with pytest.raises(ValidationError):
            online_service.ingest_trace_event(
                conn,
                settings,
                org_id=org_id,
                project_id=project_id,
                rule_id=rule_id,
                trace_id="trace-a",
                metadata={},
            )
        rule_id2 = online_service.create_rule(
            conn,
            org_id=org_id,
            project_id=project_id,
            payload={
                "rule_key": "sample2",
                "sample_rate": 0.0,
                "sample_hash_salt": "fixed",
                "evaluator_revision_ids": [],
                "actions": [],
            },
        )
        assert (
            online_service.ingest_trace_event(
                conn,
                settings,
                org_id=org_id,
                project_id=project_id,
                rule_id=rule_id2,
                trace_id="trace-b",
                metadata={},
            )
            is None
        )


def test_annotation_lease_and_export(settings: Settings, org_project: tuple) -> None:
    org_id, project_id = org_project
    with connect(settings.database_url) as conn:
        qid = annotation_service.create_queue(
            conn,
            org_id=org_id,
            project_id=project_id,
            queue_key="q1",
            display_name="",
            item_filter={},
            rubric={"rating": "1-5"},
            reviewers_required=2,
            actor="tester",
        )
        item_id = annotation_service.add_item(
            conn,
            org_id=org_id,
            project_id=project_id,
            queue_id=qid,
            item_type="trace",
            reference_id="trace-9",
            pairwise_reference_id=None,
            metadata={},
        )
        annotation_service.claim_item(
            conn,
            org_id=org_id,
            item_id=item_id,
            assignee="alice",
            expected_version=0,
            lease_seconds=60,
        )
        with pytest.raises(ConflictError):
            annotation_service.claim_item(
                conn,
                org_id=org_id,
                item_id=item_id,
                assignee="alice",
                expected_version=0,
                lease_seconds=60,
            )
        annotation_service.submit(
            conn,
            org_id=org_id,
            project_id=project_id,
            item_id=item_id,
            assignee="alice",
            action="submit",
            scores={"rating": 4},
            comments="ok",
            rubric_version=1,
        )
        annotation_service.submit(
            conn,
            org_id=org_id,
            project_id=project_id,
            item_id=item_id,
            assignee="bob",
            action="submit",
            scores={"rating": 2},
            comments="low",
            rubric_version=1,
        )
        metrics = annotation_service.consensus_metrics(conn, item_id)
        assert metrics["disagreement"] is True
        rev = annotation_service.export_item_to_dataset(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            item_id=item_id,
            dataset_key="from-annotation",
            actor="tester",
        )
        assert rev["example_count"] >= 1


@pytest.mark.asyncio
async def test_evaluator_dry_run_exact(settings: Settings, org_project: tuple) -> None:
    org_id, project_id = org_project
    with connect(settings.database_url) as conn:
        _, rev = evaluator_service.create_evaluator(
            conn,
            org_id=org_id,
            project_id=project_id,
            evaluator_key="exact",
            display_name="",
            kind="exact_match",
            config={},
            actor="tester",
        )
        out = await evaluator_service.dry_run(
            settings,
            conn=conn,
            org_id=org_id,
            revision_id=rev["id"],
            kind=None,
            config=None,
            context={"output": "a", "reference": "a"},
            authorization="",
        )
        assert out["passed"] is True


@pytest.mark.asyncio
async def test_mocked_router_experiment_worker(settings: Settings, org_project: tuple) -> None:
    org_id, project_id = org_project

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(
                200,
                json={
                    "id": "trace-mock-1",
                    "choices": [{"message": {"content": "answer"}}],
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    from evaluate.clients.router import RouterClient
    from evaluate.worker.runner import _run_single_result

    with connect(settings.database_url) as conn:
        dataset_service.create_dataset(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            dataset_key="worker",
            display_name="",
            description="",
            tags=[],
            actor="tester",
        )
        rev = dataset_service.create_revision(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            dataset_key="worker",
            payload_examples=[{"example_key": "1", "input": {"q": "?"}, "metadata": {}}],
            copy_from_revision_id=None,
            actor="tester",
        )
        _, ev_rev = evaluator_service.create_evaluator(
            conn,
            org_id=org_id,
            project_id=project_id,
            evaluator_key="exact",
            display_name="",
            kind="exact_match",
            config={},
            actor="tester",
        )
        spec = {
            "dataset_revision_id": str(rev["id"]),
            "evaluator_revision_ids": [str(ev_rev["id"])],
            "model_route_alias": "mock",
        }
        exp = experiment_service.create_experiment(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            experiment_key="w1",
            display_name="",
            spec=spec,
            baseline_experiment_id=None,
            seed=1,
            repetitions=1,
            concurrency=1,
            budget_usd=None,
            actor="tester",
        )
        experiment_service.start_experiment(
            conn, settings, org_id=org_id, project_id=project_id, experiment_id=exp["id"]
        )
        from evaluate.db import repository as repo

        results = repo.list_experiment_results(conn, org_id, exp["id"])
        exp_id = exp["id"]

    router = RouterClient(settings, transport=transport)
    await _run_single_result(
        settings,
        org_id=org_id,
        project_id=project_id,
        experiment_id=exp_id,
        result_row=results[0],
        spec=spec,
        router=router,
    )
    with connect(settings.database_url) as conn2:
        results2 = repo.list_experiment_results(conn2, org_id, exp_id)
        assert results2[0]["status"] == "completed"
