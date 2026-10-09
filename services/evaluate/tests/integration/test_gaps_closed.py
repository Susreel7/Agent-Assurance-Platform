from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest

from evaluate.clients.prompt import PromptClient
from evaluate.clients.router import RouterClient
from evaluate.config import Settings
from evaluate.db.postgres import connect
from evaluate.domains.datasets import attachments as att
from evaluate.domains.datasets import service as dataset_service
from evaluate.domains.experiments import service as experiment_service
from evaluate.worker.runner import _run_single_result

pytestmark = pytest.mark.integration


@pytest.fixture
def org_project() -> tuple:
    return uuid4(), uuid4()


def test_csv_import(settings: Settings, org_project: tuple) -> None:
    org_id, project_id = org_project
    csv_body = 'example_key,split,input,reference_output\ne1,train,"{""q"":1}","{""a"":2}"\n'
    with connect(settings.database_url) as conn:
        dataset_service.create_dataset(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            dataset_key="csv-data",
            display_name="",
            description="",
            tags=[],
            actor="tester",
        )
        rev = dataset_service.import_csv(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            dataset_key="csv-data",
            content=csv_body,
            actor="tester",
        )
        assert rev["example_count"] == 1


def test_attachment_roundtrip(settings: Settings, org_project: tuple) -> None:
    org_id, project_id = org_project
    payload = json.dumps({"secret": "value"}).encode("utf-8")
    with connect(settings.database_url) as conn:
        ref_id = att.store_attachment(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            purpose="dataset_input",
            plaintext=payload,
            mime_type="application/json",
        )
        loaded = att.load_attachment_bytes(
            conn, settings, org_id=org_id, project_id=project_id, ref_id=ref_id
        )
        assert json.loads(loaded.decode()) == {"secret": "value"}


@pytest.mark.asyncio
async def test_experiment_prompt_pins_and_trace_headers(
    settings: Settings, org_project: tuple
) -> None:
    org_id, project_id = org_project
    revision_id = uuid4()
    digest = "abc123"

    def handler(request: httpx.Request) -> httpx.Response:
        if "/artifacts/demo/revisions/" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "id": str(revision_id),
                    "content_digest": digest,
                    "kind": "prompt",
                    "content": {"messages": [{"role": "user", "content": "{{q}}"}]},
                },
            )
        if "/runtime/artifacts/demo" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "artifact_key": "demo",
                    "kind": "prompt",
                    "revision_id": str(revision_id),
                    "revision_number": 1,
                    "content_digest": digest,
                    "content": {"messages": [{"role": "user", "content": "{{q}}"}]},
                },
            )
        if request.url.path.endswith("/chat/completions"):
            return httpx.Response(
                200,
                json={"id": "body-trace", "choices": [{"message": {"content": "ok"}}]},
                headers={
                    "x-trace-id": "trace-header-1",
                    "x-span-id": "span-header-1",
                    "traceparent": "00-abc-def-01",
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    with connect(settings.database_url) as conn:
        dataset_service.create_dataset(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            dataset_key="pin",
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
            dataset_key="pin",
            payload_examples=[{"example_key": "1", "input": {"q": "hi"}, "metadata": {}}],
            copy_from_revision_id=None,
            actor="tester",
        )
        spec = {
            "dataset_revision_id": str(rev["id"]),
            "prompt_revision_pins": {"demo": str(revision_id)},
            "evaluator_revision_ids": [],
            "model_route_alias": "mock",
        }
        exp = experiment_service.create_experiment(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            experiment_key="pinned",
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

    await _run_single_result(
        settings,
        org_id=org_id,
        project_id=project_id,
        experiment_id=exp_id,
        result_row=results[0],
        spec=spec,
        prompt=PromptClient(settings, transport=transport),
        router=RouterClient(settings, transport=transport),
    )
    with connect(settings.database_url) as conn:
        row = repo.list_experiment_results(conn, org_id, exp_id)[0]
        assert row["trace_id"] == "trace-header-1"
        assert row["span_id"] == "span-header-1"
        link = (
            row["trace_link"]
            if isinstance(row["trace_link"], dict)
            else json.loads(row["trace_link"])
        )
        assert link.get("traceparent") == "00-abc-def-01"
        assert "prompt:demo" in (row["scores"] or {}).get("prompt_digests", {})
