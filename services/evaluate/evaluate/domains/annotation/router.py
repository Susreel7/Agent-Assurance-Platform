"""HTTP handlers for annotation queues."""

from __future__ import annotations

from typing import Any, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from evaluate.api.deps import db_conn, scoped_internal, settings_dep
from evaluate.auth.schemas import InternalPrincipal
from evaluate.config import Settings
from evaluate.db.postgres import PgConn
from evaluate.domains.annotation import read_service as annotation_reads
from evaluate.domains.annotation import service
from evaluate.domains.annotation.schemas import (
    AnnotationItemCreate,
    AnnotationItemOut,
    AnnotationQueueCreate,
    AnnotationQueueOut,
    ClaimRequest,
    ExportToDatasetRequest,
    SubmissionRequest,
)
from evaluate.domains.common_schemas import PagedResponse
from evaluate.errors import EvaluateError

router = APIRouter(
    prefix="/v1/orgs/{org_id}/projects/{project_id}/annotation-queues", tags=["annotation"]
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


@router.get("/items", response_model=PagedResponse[AnnotationItemOut])
def list_items_project(
    queue_id: UUID | None = Query(default=None),
    status: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=500),
    cursor: str | None = Query(default=None),
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> PagedResponse[AnnotationItemOut]:
    try:
        return annotation_reads.list_items(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            queue_id=queue_id,
            status=status,
            limit=limit,
            cursor=cursor,
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.get("", response_model=PagedResponse[AnnotationQueueOut])
def list_queues(
    limit: int | None = Query(default=None, ge=1, le=500),
    cursor: str | None = Query(default=None),
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> PagedResponse[AnnotationQueueOut]:
    try:
        return annotation_reads.list_queues(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            limit=limit,
            cursor=cursor,
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.get("/{queue_id}", response_model=AnnotationQueueOut)
def get_queue(
    queue_id: UUID,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> AnnotationQueueOut:
    try:
        return annotation_reads.get_queue(
            conn, principal.organization_id, principal.project_id, queue_id
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.get("/{queue_id}/items", response_model=PagedResponse[AnnotationItemOut])
def list_queue_items(
    queue_id: UUID,
    status: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=500),
    cursor: str | None = Query(default=None),
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> PagedResponse[AnnotationItemOut]:
    try:
        return annotation_reads.list_items(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            queue_id=queue_id,
            status=status,
            limit=limit,
            cursor=cursor,
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.get("/items/{item_id}", response_model=AnnotationItemOut)
def get_item(
    item_id: UUID,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> AnnotationItemOut:
    try:
        return annotation_reads.get_item(
            conn, principal.organization_id, principal.project_id, item_id
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.post("", status_code=201)
def create_queue(
    payload: AnnotationQueueCreate,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> dict[str, str]:
    try:
        qid = service.create_queue(
            conn,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            queue_key=payload.queue_key,
            display_name=payload.display_name,
            item_filter=payload.item_filter,
            rubric=payload.rubric,
            reviewers_required=payload.reviewers_required,
            actor=principal.actor,
        )
        return {"id": str(qid)}
    except EvaluateError as exc:
        _map_error(exc)


@router.post("/{queue_id}/items", status_code=201)
def add_item(
    queue_id: UUID,
    payload: AnnotationItemCreate,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> dict[str, str]:
    try:
        iid = service.add_item(
            conn,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            queue_id=queue_id,
            item_type=payload.item_type,
            reference_id=payload.reference_id,
            pairwise_reference_id=payload.pairwise_reference_id,
            metadata=payload.metadata,
        )
        return {"id": str(iid)}
    except EvaluateError as exc:
        _map_error(exc)


@router.post("/items/{item_id}/claim")
def claim_item(
    item_id: UUID,
    payload: ClaimRequest,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> dict[str, bool]:
    try:
        service.claim_item(
            conn,
            org_id=principal.organization_id,
            item_id=item_id,
            assignee=payload.assignee,
            expected_version=payload.expected_version,
            lease_seconds=payload.lease_seconds,
        )
        return {"claimed": True}
    except EvaluateError as exc:
        _map_error(exc)


@router.post("/items/{item_id}/submissions", status_code=201)
def submit(
    item_id: UUID,
    payload: SubmissionRequest,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> dict[str, str]:
    try:
        sid = service.submit(
            conn,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            item_id=item_id,
            assignee=payload.assignee,
            action=payload.action,
            scores=payload.scores,
            comments=payload.comments,
            rubric_version=payload.rubric_version,
        )
        return {"id": str(sid)}
    except EvaluateError as exc:
        _map_error(exc)


@router.get("/items/{item_id}/consensus")
def consensus(
    item_id: UUID,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> dict[str, Any]:
    _ = principal
    return service.consensus_metrics(conn, item_id)


@router.post("/items/{item_id}/export-to-dataset")
def export_to_dataset(
    item_id: UUID,
    payload: ExportToDatasetRequest,
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> dict[str, str]:
    try:
        rev = service.export_item_to_dataset(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            item_id=item_id,
            dataset_key=payload.dataset_key,
            actor=principal.actor,
        )
        return {"revision_id": str(rev["id"])}
    except EvaluateError as exc:
        _map_error(exc)
