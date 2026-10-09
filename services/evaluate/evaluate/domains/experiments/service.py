"""Experiment orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from evaluate.config import Settings
from evaluate.db import repository as repo
from evaluate.db.postgres import PgConn
from evaluate.errors import ConflictError, NotFoundError, ValidationError
from evaluate.queue.redis_wake import publish_wake
from evaluate.stats import aggregates as stats
from evaluate.util import digest_json


def create_experiment(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    experiment_key: str,
    display_name: str,
    spec: dict[str, Any],
    baseline_experiment_id: UUID | None,
    seed: int,
    repetitions: int,
    concurrency: int,
    budget_usd: float | None,
    actor: str,
) -> dict[str, Any]:
    rev_id = UUID(str(spec["dataset_revision_id"]))
    revision = repo.get_dataset_revision(conn, org_id, rev_id)
    if not revision or revision["project_id"] != project_id:
        raise NotFoundError("dataset revision not found")
    spec_digest = digest_json(spec)
    exp_id = repo.insert_experiment(
        conn,
        org_id=org_id,
        project_id=project_id,
        experiment_key=experiment_key,
        display_name=display_name,
        dataset_revision_id=rev_id,
        baseline_experiment_id=baseline_experiment_id,
        spec=spec,
        spec_digest=spec_digest,
        seed=seed,
        repetitions=repetitions,
        concurrency=concurrency,
        budget_usd=budget_usd,
        actor=actor,
    )
    row = repo.get_experiment(conn, org_id, project_id, exp_id)
    assert row is not None
    return row


def start_experiment(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    experiment_id: UUID,
) -> dict[str, Any]:
    exp = repo.get_experiment(conn, org_id, project_id, experiment_id)
    if not exp:
        raise NotFoundError("experiment not found")
    if exp["status"] not in ("draft", "failed", "partial"):
        raise ConflictError(f"cannot start experiment in status {exp['status']}")
    examples = repo.list_examples_for_revision(conn, org_id, exp["dataset_revision_id"])
    rows: list[tuple[UUID, UUID, UUID, UUID, int]] = []
    for ex in examples:
        for rep in range(int(exp["repetitions"])):
            rows.append((experiment_id, org_id, project_id, ex["id"], rep))
    repo.insert_experiment_result_rows(conn, rows)
    repo.update_experiment_status(
        conn,
        org_id,
        experiment_id,
        "pending",
        started_at=datetime.now(UTC),
        progress={"total": len(rows), "completed": 0},
    )
    job_id = repo.enqueue_job(
        conn,
        org_id=org_id,
        project_id=project_id,
        job_type="experiment_run",
        payload={"experiment_id": str(experiment_id)},
        idempotency_key=f"experiment-run:{experiment_id}",
        max_attempts=settings.worker_max_attempts,
    )
    if job_id:
        publish_wake(settings, reason="experiment")
    row = repo.get_experiment(conn, org_id, project_id, experiment_id)
    assert row is not None
    return row


def cancel_experiment(
    conn: PgConn, org_id: UUID, project_id: UUID, experiment_id: UUID
) -> dict[str, Any]:
    exp = repo.get_experiment(conn, org_id, project_id, experiment_id)
    if not exp:
        raise NotFoundError("experiment not found")
    repo.cancel_pending_experiment_results(conn, experiment_id)
    repo.update_experiment_status(
        conn,
        org_id,
        experiment_id,
        "cancelled",
        cancelled_at=datetime.now(UTC),
    )
    row = repo.get_experiment(conn, org_id, project_id, experiment_id)
    assert row is not None
    return row


def retry_experiment(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    experiment_id: UUID,
) -> dict[str, Any]:
    exp = repo.get_experiment(conn, org_id, project_id, experiment_id)
    if not exp:
        raise NotFoundError("experiment not found")
    if exp["status"] not in ("failed", "partial", "cancelled"):
        raise ValidationError("retry allowed only for failed, partial, or cancelled experiments")
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE evaluate.experiment_results
            SET status = 'pending', error_message = NULL, updated_at = now()
            WHERE experiment_id = %s AND status IN ('failed', 'cancelled')
            """,
            (experiment_id,),
        )
    repo.update_experiment_status(conn, org_id, experiment_id, "pending")
    repo.enqueue_job(
        conn,
        org_id=org_id,
        project_id=project_id,
        job_type="experiment_run",
        payload={"experiment_id": str(experiment_id)},
        idempotency_key=f"experiment-retry:{experiment_id}:{datetime.now(UTC).timestamp()}",
        max_attempts=settings.worker_max_attempts,
    )
    publish_wake(settings, reason="experiment-retry")
    row = repo.get_experiment(conn, org_id, project_id, experiment_id)
    assert row is not None
    return row


def refresh_aggregates(
    conn: PgConn, org_id: UUID, project_id: UUID, experiment_id: UUID
) -> dict[str, Any]:
    exp = repo.get_experiment(conn, org_id, project_id, experiment_id)
    if not exp:
        raise NotFoundError("experiment not found")
    results = repo.list_experiment_results(conn, org_id, experiment_id)
    aggs = stats.aggregate_experiment_scores(results)
    comparison = None
    baseline_id = exp.get("baseline_experiment_id")
    if baseline_id:
        baseline = repo.get_experiment(conn, org_id, project_id, baseline_id)
        if baseline:
            base_results = repo.list_experiment_results(conn, org_id, baseline_id)
            base_aggs = stats.aggregate_experiment_scores(base_results)
            comparison = {"baseline_aggregates": base_aggs, "candidate_aggregates": aggs}
    repo.update_experiment_status(conn, org_id, experiment_id, exp["status"], aggregates=aggs)
    return {"aggregates": aggs, "comparison": comparison}


def get_results_with_comparison(
    conn: PgConn, org_id: UUID, project_id: UUID, experiment_id: UUID
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    exp = repo.get_experiment(conn, org_id, project_id, experiment_id)
    if not exp:
        raise NotFoundError("experiment not found")
    results = repo.list_experiment_results(conn, org_id, experiment_id)
    comparison = None
    baseline_id = exp.get("baseline_experiment_id")
    if baseline_id:
        cand_vals: list[float] = []
        base_vals: list[float] = []
        for r in results:
            scores = r.get("scores") or {}
            if isinstance(scores, dict) and "primary" in scores:
                try:
                    cand_vals.append(float(scores["primary"].get("score", scores["primary"])))
                except (TypeError, ValueError, AttributeError):
                    pass
        base_results = repo.list_experiment_results(conn, org_id, baseline_id)
        for r in base_results:
            scores = r.get("scores") or {}
            if isinstance(scores, dict) and "primary" in scores:
                try:
                    base_vals.append(float(scores["primary"].get("score", scores["primary"])))
                except (TypeError, ValueError, AttributeError):
                    pass
        comparison = stats.compare_to_baseline(cand_vals, base_vals, regression_threshold=0.05)
    return results, comparison
