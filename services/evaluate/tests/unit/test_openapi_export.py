from __future__ import annotations

from evaluate.app import create_app
from evaluate.entrypoints import export_openapi

BFF_READ_PATH_FRAGMENTS = (
    "/datasets",
    "/datasets/{dataset_key}",
    "/datasets/{dataset_key}/revisions/{revision_id}/examples",
    "/experiments",
    "/experiments/{experiment_id}",
    "/evaluators",
    "/evaluators/{evaluator_key}/revisions/{revision_id}",
    "/scores",
    "/online-rules",
    "/online-rules/alerts",
    "/online-rules/alerts/{alert_id}/acknowledge",
    "/annotation-queues",
    "/annotation-queues/{queue_id}/items",
    "/release-gates",
    "/release-gates/{gate_id}/evaluations",
)


def test_openapi_schema_has_bff_read_paths() -> None:
    schema = create_app().openapi()
    assert "paths" in schema
    assert schema["info"]["title"]
    paths = schema["paths"]
    for fragment in BFF_READ_PATH_FRAGMENTS:
        assert any(fragment in p for p in paths), f"missing OpenAPI path containing {fragment!r}"


def test_export_openapi_writes_json(capsys) -> None:
    export_openapi()
    out = capsys.readouterr().out
    assert '"openapi"' in out
    assert '"paths"' in out
