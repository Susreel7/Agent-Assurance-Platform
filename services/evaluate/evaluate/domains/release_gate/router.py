"""HTTP handlers for release gates."""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from evaluate.api.deps import db_conn, scoped_internal, settings_dep
from evaluate.auth.schemas import InternalPrincipal
from evaluate.config import Settings
from evaluate.db.postgres import PgConn
from evaluate.domains.common_schemas import PagedResponse
from evaluate.domains.release_gate import read_service as gate_reads
from evaluate.domains.release_gate import service
from evaluate.domains.release_gate.schemas import (
    ReleaseGateCreate,
    ReleaseGateEvaluateRequest,
    ReleaseGateEvaluationOut,
    ReleaseGateOut,
)
from evaluate.errors import EvaluateError

router = APIRouter(
    prefix="/v1/orgs/{org_id}/projects/{project_id}/release-gates", tags=["release-gates"]
)


def _map_error(exc: EvaluateError) -> NoReturn:
    from fastapi import HTTPException

    status = 400
    if exc.code == "not_found":
        status = 404
    raise HTTPException(
        status_code=status, detail={"code": exc.code, "message": exc.message}
    ) from exc


@router.get("", response_model=PagedResponse[ReleaseGateOut])
def list_gates(
    limit: int | None = Query(default=None, ge=1, le=500),
    cursor: str | None = Query(default=None),
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> PagedResponse[ReleaseGateOut]:
    try:
        return gate_reads.list_gates(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            limit=limit,
            cursor=cursor,
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.get("/{gate_id}", response_model=ReleaseGateOut)
def get_gate(
    gate_id: UUID,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> ReleaseGateOut:
    try:
        return gate_reads.get_gate(conn, principal.organization_id, principal.project_id, gate_id)
    except EvaluateError as exc:
        _map_error(exc)


@router.get("/{gate_id}/evaluations", response_model=PagedResponse[ReleaseGateEvaluationOut])
def list_gate_evaluations(
    gate_id: UUID,
    limit: int | None = Query(default=None, ge=1, le=500),
    cursor: str | None = Query(default=None),
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> PagedResponse[ReleaseGateEvaluationOut]:
    try:
        return gate_reads.list_evaluations(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            gate_id=gate_id,
            limit=limit,
            cursor=cursor,
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.post("", status_code=201)
def create_gate(
    payload: ReleaseGateCreate,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> dict[str, str]:
    try:
        gid = service.create_gate(
            conn,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            gate_key=payload.gate_key,
            baseline_experiment_id=payload.baseline_experiment_id,
            thresholds=payload.thresholds,
            actor=principal.actor,
        )
        return {"id": str(gid)}
    except EvaluateError as exc:
        _map_error(exc)


@router.post("/{gate_id}/evaluate")
def evaluate_gate(
    gate_id: UUID,
    payload: ReleaseGateEvaluateRequest,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> dict[str, object]:
    try:
        return service.evaluate_gate(
            conn,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            gate_id=gate_id,
            candidate_experiment_id=payload.candidate_experiment_id,
        )
    except EvaluateError as exc:
        _map_error(exc)
