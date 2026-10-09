"""HTTP handlers for experiments."""

from __future__ import annotations

from typing import Any, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from evaluate.api.deps import db_conn, scoped_internal, settings_dep
from evaluate.auth.schemas import InternalPrincipal
from evaluate.config import Settings
from evaluate.db.postgres import PgConn
from evaluate.domains.common_schemas import PagedResponse
from evaluate.domains.experiments import read_service as experiment_reads
from evaluate.domains.experiments import service
from evaluate.domains.experiments.schemas import (
    ExperimentCreate,
    ExperimentOut,
    ExperimentResultOut,
    ExperimentResultsResponse,
)
from evaluate.errors import EvaluateError

router = APIRouter(
    prefix="/v1/orgs/{org_id}/projects/{project_id}/experiments", tags=["experiments"]
)


def _map_error(exc: EvaluateError) -> NoReturn:
    from fastapi import HTTPException

    status = 400
    if exc.code == "not_found":
        status = 404
    elif exc.code == "conflict":
        status = 409
    raise HTTPException(
        status_code=status, detail={"code": exc.code, "message": exc.message}
    ) from exc


@router.get("", response_model=PagedResponse[ExperimentOut])
def list_experiments(
    q: str | None = Query(default=None, max_length=256),
    limit: int | None = Query(default=None, ge=1, le=500),
    cursor: str | None = Query(default=None),
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> PagedResponse[ExperimentOut]:
    try:
        return experiment_reads.list_experiments(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            q=q,
            limit=limit,
            cursor=cursor,
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.get("/by-key/{experiment_key}", response_model=ExperimentOut)
def get_experiment_by_key(
    experiment_key: str,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> ExperimentOut:
    try:
        return experiment_reads.get_experiment_by_key(
            conn,
            principal.organization_id,
            principal.project_id,
            experiment_key,
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.get("/{experiment_id}", response_model=ExperimentOut)
def get_experiment(
    experiment_id: UUID,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> ExperimentOut:
    try:
        return experiment_reads.get_experiment(
            conn, principal.organization_id, principal.project_id, experiment_id
        )
    except EvaluateError as exc:
        _map_error(exc)


def _exp_out(row: dict[str, Any]) -> ExperimentOut:
    return ExperimentOut(
        id=row["id"],
        experiment_key=row["experiment_key"],
        display_name=row["display_name"],
        status=row["status"],
        dataset_revision_id=row["dataset_revision_id"],
        spec_digest=row["spec_digest"],
        seed=row["seed"],
        repetitions=row["repetitions"],
        concurrency=row["concurrency"],
        progress=row["progress"] if isinstance(row["progress"], dict) else {},
        aggregates=row["aggregates"] if isinstance(row["aggregates"], dict) else {},
        created_at=row["created_at"],
    )


@router.post("", response_model=ExperimentOut, status_code=201)
def create_experiment(
    payload: ExperimentCreate,
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> ExperimentOut:
    try:
        row = service.create_experiment(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            experiment_key=payload.experiment_key,
            display_name=payload.display_name,
            spec=payload.spec.model_dump(mode="json"),
            baseline_experiment_id=payload.baseline_experiment_id,
            seed=payload.seed,
            repetitions=payload.repetitions,
            concurrency=payload.concurrency,
            budget_usd=payload.budget_usd,
            actor=principal.actor,
        )
        return _exp_out(row)
    except EvaluateError as exc:
        _map_error(exc)


@router.post("/{experiment_id}/start", response_model=ExperimentOut)
def start_experiment(
    experiment_id: UUID,
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> ExperimentOut:
    try:
        row = service.start_experiment(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            experiment_id=experiment_id,
        )
        return _exp_out(row)
    except EvaluateError as exc:
        _map_error(exc)


@router.post("/{experiment_id}/cancel", response_model=ExperimentOut)
def cancel_experiment(
    experiment_id: UUID,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> ExperimentOut:
    try:
        row = service.cancel_experiment(
            conn, principal.organization_id, principal.project_id, experiment_id
        )
        return _exp_out(row)
    except EvaluateError as exc:
        _map_error(exc)


@router.post("/{experiment_id}/retry", response_model=ExperimentOut)
def retry_experiment(
    experiment_id: UUID,
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> ExperimentOut:
    try:
        row = service.retry_experiment(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            experiment_id=experiment_id,
        )
        return _exp_out(row)
    except EvaluateError as exc:
        _map_error(exc)


@router.get("/{experiment_id}/results", response_model=ExperimentResultsResponse)
def list_results(
    experiment_id: UUID,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> ExperimentResultsResponse:
    try:
        rows, comparison = service.get_results_with_comparison(
            conn, principal.organization_id, principal.project_id, experiment_id
        )
        items = [
            ExperimentResultOut(
                id=r["id"],
                example_id=r["example_id"],
                repetition_index=r["repetition_index"],
                status=r["status"],
                trace_id=r.get("trace_id"),
                scores=r["scores"] if isinstance(r["scores"], dict) else {},
                latency_ms=r.get("latency_ms"),
                cost_usd=float(r["cost_usd"]) if r.get("cost_usd") is not None else None,
            )
            for r in rows
        ]
        return ExperimentResultsResponse(items=items, comparison=comparison)
    except EvaluateError as exc:
        _map_error(exc)


@router.post("/{experiment_id}/aggregates/refresh")
def refresh_aggregates(
    experiment_id: UUID,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> dict[str, Any]:
    try:
        return service.refresh_aggregates(
            conn, principal.organization_id, principal.project_id, experiment_id
        )
    except EvaluateError as exc:
        _map_error(exc)
