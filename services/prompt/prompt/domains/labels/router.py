"""HTTP handlers for labels."""

from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, Depends, Query

from prompt.api.deps import db_conn, scoped_internal, settings_dep
from prompt.auth.schemas import InternalPrincipal
from prompt.config import Settings
from prompt.db.postgres import PgConn
from prompt.domains.labels import service
from prompt.domains.labels.schemas import (
    CompareLabelsRequest,
    LabelHistoryResponse,
    LabelOut,
    PromoteLabelRequest,
)
from prompt.errors import PromptError

router = APIRouter(prefix="/v1/orgs/{org_id}/projects/{project_id}/artifacts", tags=["labels"])


def _map_error(exc: PromptError) -> NoReturn:
    from fastapi import HTTPException

    status = 400
    if exc.code == "not_found":
        status = 404
    elif exc.code == "conflict":
        status = 409
    elif exc.code == "precondition_failed":
        status = 412
    elif exc.code == "authorization_error":
        status = 403
    raise HTTPException(
        status_code=status, detail={"code": exc.code, "message": exc.message}
    ) from exc


@router.post("/{artifact_key}/labels:promote", response_model=LabelOut)
def promote_label(
    artifact_key: str,
    payload: PromoteLabelRequest,
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> LabelOut:
    try:
        return service.promote_label(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            artifact_key=artifact_key,
            payload=payload,
            actor=principal.actor,
            scopes=principal.scopes,
        )
    except PromptError as exc:
        _map_error(exc)


@router.get("/{artifact_key}/labels/{label_name}", response_model=LabelOut)
def get_label(
    artifact_key: str,
    label_name: str,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> LabelOut:
    try:
        return service.get_label(
            conn, principal.organization_id, principal.project_id, artifact_key, label_name
        )
    except PromptError as exc:
        _map_error(exc)


@router.get("/{artifact_key}/labels/{label_name}/history", response_model=LabelHistoryResponse)
def label_history(
    artifact_key: str,
    label_name: str,
    limit: int = Query(default=100, ge=1, le=500),
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> LabelHistoryResponse:
    try:
        return service.label_history(
            conn,
            principal.organization_id,
            principal.project_id,
            artifact_key,
            limit,
            label_name=label_name,
        )
    except PromptError as exc:
        _map_error(exc)


@router.post("/{artifact_key}/labels:compare")
def compare_labels(
    artifact_key: str,
    payload: CompareLabelsRequest,
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> dict[str, object]:
    try:
        return service.compare_labels(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            artifact_key=artifact_key,
            payload=payload,
        )
    except PromptError as exc:
        _map_error(exc)
