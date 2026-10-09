"""Regression thresholds and release gate evaluation."""

from __future__ import annotations

from uuid import UUID

from evaluate.db import repository as repo
from evaluate.db.postgres import PgConn
from evaluate.domains.experiments import service as experiment_service
from evaluate.errors import NotFoundError
from evaluate.stats import aggregates as stats


def create_gate(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    gate_key: str,
    baseline_experiment_id: UUID | None,
    thresholds: dict[str, object],
    actor: str,
) -> UUID:
    return repo.insert_release_gate(
        conn,
        org_id=org_id,
        project_id=project_id,
        gate_key=gate_key,
        baseline_experiment_id=baseline_experiment_id,
        thresholds=thresholds,
        actor=actor,
    )


def evaluate_gate(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    gate_id: UUID,
    candidate_experiment_id: UUID,
) -> dict[str, object]:
    gate = repo.get_release_gate(conn, org_id, project_id, gate_id)
    if not gate:
        raise NotFoundError("release gate not found")
    thresholds = gate.get("thresholds") or {}
    regression_threshold = float(thresholds.get("regression_threshold", 0.05))
    metric = str(thresholds.get("metric", "primary"))
    baseline_id = gate.get("baseline_experiment_id")
    if not baseline_id:
        raise NotFoundError("gate has no baseline experiment")
    cand_results = repo.list_experiment_results(conn, org_id, candidate_experiment_id)
    base_results = repo.list_experiment_results(conn, org_id, baseline_id)
    cand_vals: list[float] = []
    base_vals: list[float] = []
    for r in cand_results:
        scores = r.get("scores") or {}
        if isinstance(scores, dict) and metric in scores:
            try:
                cand_vals.append(float(scores[metric].get("score", scores[metric])))
            except (TypeError, ValueError, AttributeError):
                pass
    for r in base_results:
        scores = r.get("scores") or {}
        if isinstance(scores, dict) and metric in scores:
            try:
                base_vals.append(float(scores[metric].get("score", scores[metric])))
            except (TypeError, ValueError, AttributeError):
                pass
    comparison = stats.compare_to_baseline(
        cand_vals, base_vals, regression_threshold=regression_threshold
    )
    passed = not comparison["regressed"]
    detail = {"comparison": comparison, "metric": metric}
    repo.insert_release_gate_evaluation(
        conn,
        gate_id=gate_id,
        org_id=org_id,
        project_id=project_id,
        candidate_experiment_id=candidate_experiment_id,
        passed=passed,
        detail=detail,
    )
    experiment_service.refresh_aggregates(conn, org_id, project_id, candidate_experiment_id)
    return {"passed": passed, "detail": detail}
