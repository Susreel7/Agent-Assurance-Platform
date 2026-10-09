"""HTTP handlers for evaluators."""

from __future__ import annotations

from typing import Any, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query

from evaluate.api.deps import db_conn, scoped_internal, settings_dep
from evaluate.auth.schemas import InternalPrincipal
from evaluate.config import Settings
from evaluate.db.postgres import PgConn
from evaluate.domains.common_schemas import PagedResponse
from evaluate.domains.evaluators import read_service as evaluator_reads
from evaluate.domains.evaluators import service
from evaluate.domains.evaluators.schemas import (
    EvaluatorCreate,
    EvaluatorDryRunRequest,
    EvaluatorOut,
    EvaluatorRevisionOut,
    EvaluatorRevisionSummaryOut,
)
from evaluate.errors import EvaluateError

router = APIRouter(prefix="/v1/orgs/{org_id}/projects/{project_id}/evaluators", tags=["evaluators"])


@router.get("", response_model=PagedResponse[EvaluatorOut])
def list_evaluators(
    q: str | None = Query(default=None, max_length=256),
    limit: int | None = Query(default=None, ge=1, le=500),
    cursor: str | None = Query(default=None),
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> PagedResponse[EvaluatorOut]:
    try:
        return evaluator_reads.list_evaluators(
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


@router.get("/{evaluator_key}", response_model=EvaluatorOut)
def get_evaluator(
    evaluator_key: str,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> EvaluatorOut:
    try:
        return evaluator_reads.get_evaluator(
            conn, principal.organization_id, principal.project_id, evaluator_key
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.get("/{evaluator_key}/revisions", response_model=PagedResponse[EvaluatorRevisionSummaryOut])
def list_evaluator_revisions(
    evaluator_key: str,
    limit: int | None = Query(default=None, ge=1, le=500),
    cursor: str | None = Query(default=None),
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> PagedResponse[EvaluatorRevisionSummaryOut]:
    try:
        return evaluator_reads.list_revisions(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            evaluator_key=evaluator_key,
            limit=limit,
            cursor=cursor,
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.get("/{evaluator_key}/revisions/{revision_id}", response_model=EvaluatorRevisionSummaryOut)
def get_evaluator_revision(
    evaluator_key: str,
    revision_id: UUID,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> EvaluatorRevisionSummaryOut:
    try:
        return evaluator_reads.get_revision(
            conn,
            principal.organization_id,
            principal.project_id,
            evaluator_key,
            revision_id,
        )
    except EvaluateError as exc:
        _map_error(exc)


def _map_error(exc: EvaluateError) -> NoReturn:
    from fastapi import HTTPException

    status = 400
    if exc.code == "not_found":
        status = 404
    raise HTTPException(
        status_code=status, detail={"code": exc.code, "message": exc.message}
    ) from exc


@router.post("", response_model=EvaluatorRevisionOut, status_code=201)
def create_evaluator(
    payload: EvaluatorCreate,
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> EvaluatorRevisionOut:
    try:
        ev, rev = service.create_evaluator(
            conn,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            evaluator_key=payload.evaluator_key,
            display_name=payload.display_name,
            kind=payload.kind,
            config=payload.config,
            actor=principal.actor,
        )
        _ = ev
        return EvaluatorRevisionOut(
            id=rev["id"],
            evaluator_id=rev["evaluator_id"],
            revision_number=rev["revision_number"],
            config_digest=rev["config_digest"],
            created_at=rev["created_at"],
            created_by=rev["created_by"],
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.post("/dry-run")
async def dry_run(
    payload: EvaluatorDryRunRequest,
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> dict[str, Any]:
    try:
        return await service.dry_run(
            settings,
            conn=conn,
            org_id=principal.organization_id,
            revision_id=payload.revision_id,
            kind=payload.kind,
            config=payload.config,
            context=payload.context,
            authorization=authorization or "",
        )
    except EvaluateError as exc:
        _map_error(exc)
