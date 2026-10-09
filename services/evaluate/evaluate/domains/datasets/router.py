"""HTTP handlers for datasets."""

from __future__ import annotations

import base64
from typing import Any, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from evaluate.api.deps import db_conn, scoped_internal, settings_dep
from evaluate.auth.schemas import InternalPrincipal
from evaluate.config import Settings
from evaluate.db import repository as repo
from evaluate.db.postgres import PgConn
from evaluate.domains.common_schemas import PagedResponse
from evaluate.domains.datasets import attachments as attachment_service
from evaluate.domains.datasets import read_service as dataset_reads
from evaluate.domains.datasets import service
from evaluate.domains.datasets.schemas import (
    AttachmentDownloadOut,
    AttachmentUploadIn,
    AttachmentUploadOut,
    DatasetCreate,
    DatasetOut,
    DatasetRevisionCreate,
    DatasetRevisionOut,
    ExampleSummaryOut,
    ExportResponse,
    ImportRequest,
)
from evaluate.errors import EvaluateError

router = APIRouter(prefix="/v1/orgs/{org_id}/projects/{project_id}/datasets", tags=["datasets"])


@router.get("", response_model=PagedResponse[DatasetOut])
def list_datasets(
    q: str | None = Query(default=None, max_length=256),
    limit: int | None = Query(default=None, ge=1, le=500),
    cursor: str | None = Query(default=None),
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> PagedResponse[DatasetOut]:
    try:
        return dataset_reads.list_datasets(
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


@router.get("/{dataset_key}", response_model=DatasetOut)
def get_dataset(
    dataset_key: str,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> DatasetOut:
    try:
        return dataset_reads.get_dataset_by_key(
            conn, principal.organization_id, principal.project_id, dataset_key
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.get("/{dataset_key}/revisions", response_model=PagedResponse[DatasetRevisionOut])
def list_dataset_revisions(
    dataset_key: str,
    limit: int | None = Query(default=None, ge=1, le=500),
    cursor: str | None = Query(default=None),
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> PagedResponse[DatasetRevisionOut]:
    try:
        return dataset_reads.list_revisions(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            dataset_key=dataset_key,
            limit=limit,
            cursor=cursor,
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.get("/{dataset_key}/revisions/{revision_id}", response_model=DatasetRevisionOut)
def get_dataset_revision(
    dataset_key: str,
    revision_id: UUID,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> DatasetRevisionOut:
    try:
        return dataset_reads.get_revision(
            conn,
            principal.organization_id,
            principal.project_id,
            dataset_key,
            revision_id,
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.get(
    "/{dataset_key}/revisions/{revision_id}/examples",
    response_model=PagedResponse[ExampleSummaryOut],
)
def list_revision_examples(
    dataset_key: str,
    revision_id: UUID,
    split: str | None = Query(default=None),
    q: str | None = Query(default=None, max_length=128),
    limit: int | None = Query(default=None, ge=1, le=500),
    cursor: str | None = Query(default=None),
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> PagedResponse[ExampleSummaryOut]:
    try:
        return dataset_reads.list_examples(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            dataset_key=dataset_key,
            revision_id=revision_id,
            split=split,
            q=q,
            limit=limit,
            cursor=cursor,
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.get(
    "/{dataset_key}/revisions/{revision_id}/examples/{example_id}",
    response_model=ExampleSummaryOut,
)
def get_revision_example(
    dataset_key: str,
    revision_id: UUID,
    example_id: UUID,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> ExampleSummaryOut:
    try:
        return dataset_reads.get_example(
            conn,
            principal.organization_id,
            principal.project_id,
            dataset_key,
            revision_id,
            example_id,
        )
    except EvaluateError as exc:
        _map_error(exc)


def _map_error(exc: EvaluateError) -> NoReturn:
    from fastapi import HTTPException

    status = 400
    if exc.code == "not_found":
        status = 404
    elif exc.code == "conflict":
        status = 409
    elif exc.code == "payload_too_large":
        status = 413
    raise HTTPException(
        status_code=status, detail={"code": exc.code, "message": exc.message}
    ) from exc


def _dataset_out(row: dict[str, Any]) -> DatasetOut:
    return DatasetOut(
        id=row["id"],
        dataset_key=row["dataset_key"],
        display_name=row["display_name"],
        description=row["description"],
        tags=row["tags"],
        created_at=row["created_at"],
        created_by=row["created_by"],
    )


@router.post("", response_model=DatasetOut, status_code=201)
def create_dataset(
    payload: DatasetCreate,
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> DatasetOut:
    try:
        row = service.create_dataset(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            dataset_key=payload.dataset_key,
            display_name=payload.display_name,
            description=payload.description,
            tags=payload.tags,
            actor=principal.actor,
        )
        return _dataset_out(row)
    except EvaluateError as exc:
        _map_error(exc)


@router.post("/{dataset_key}/revisions", response_model=DatasetRevisionOut, status_code=201)
def create_revision(
    dataset_key: str,
    payload: DatasetRevisionCreate,
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> DatasetRevisionOut:
    try:
        examples = [e.model_dump() for e in payload.examples]
        row = service.create_revision(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            dataset_key=dataset_key,
            payload_examples=examples,
            copy_from_revision_id=payload.copy_from_revision_id,
            actor=principal.actor,
        )
        return DatasetRevisionOut(
            id=row["id"],
            dataset_id=row["dataset_id"],
            revision_number=row["revision_number"],
            manifest_digest=row["manifest_digest"],
            example_count=row["example_count"],
            created_at=row["created_at"],
            created_by=row["created_by"],
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.post("/{dataset_key}/import", response_model=DatasetRevisionOut, status_code=201)
def import_dataset(
    dataset_key: str,
    payload: ImportRequest,
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> DatasetRevisionOut:
    try:
        if payload.format == "jsonl":
            row = service.import_jsonl(
                conn,
                settings,
                org_id=principal.organization_id,
                project_id=principal.project_id,
                dataset_key=dataset_key,
                content=payload.content,
                actor=principal.actor,
            )
        elif payload.format == "csv":
            row = service.import_csv(
                conn,
                settings,
                org_id=principal.organization_id,
                project_id=principal.project_id,
                dataset_key=dataset_key,
                content=payload.content,
                actor=principal.actor,
            )
        else:
            raise EvaluateError("unsupported import format")
        return DatasetRevisionOut(
            id=row["id"],
            dataset_id=row["dataset_id"],
            revision_number=row["revision_number"],
            manifest_digest=row["manifest_digest"],
            example_count=row["example_count"],
            created_at=row["created_at"],
            created_by=row["created_by"],
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.get("/{dataset_key}/revisions/{revision_id}/export", response_model=ExportResponse)
def export_revision(
    dataset_key: str,
    revision_id: UUID,
    format: str = "jsonl",
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> ExportResponse:
    try:
        _ = dataset_key
        if format == "csv":
            content = service.export_revision_csv(conn, principal.organization_id, revision_id)
        else:
            content = service.export_revision_jsonl(conn, principal.organization_id, revision_id)
        return ExportResponse(format=format, content=content)
    except EvaluateError as exc:
        _map_error(exc)


@router.post("/attachments/upload", response_model=AttachmentUploadOut, status_code=201)
def upload_attachment(
    payload: AttachmentUploadIn,
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> AttachmentUploadOut:
    try:
        raw = base64.b64decode(payload.content_base64.encode("ascii"))
        ref_id = attachment_service.store_attachment(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            purpose=payload.purpose,
            plaintext=raw,
            mime_type=payload.mime_type,
        )
        signed = attachment_service.signed_download_metadata(
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            ref_id=ref_id,
        )
        row = repo.get_object_ref(conn, principal.organization_id, principal.project_id, ref_id)
        assert row is not None
        return AttachmentUploadOut(
            object_ref_id=ref_id,
            storage_ref=str(row["storage_ref"]),
            content_digest=str(row["content_digest"]),
            download=signed,
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.get("/attachments/{object_ref_id}/download", response_model=AttachmentDownloadOut)
def download_attachment(
    object_ref_id: UUID,
    expires_at: int = Query(...),
    signature: str = Query(...),
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> AttachmentDownloadOut:
    from evaluate.providers.download_sign import verify_download_signature

    try:
        ok = verify_download_signature(
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            object_ref_id=object_ref_id,
            expires_at=expires_at,
            signature=signature,
        )
        if not ok:
            raise EvaluateError("invalid or expired download signature")
        data = attachment_service.load_attachment_bytes(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            ref_id=object_ref_id,
        )
        row = repo.get_object_ref(
            conn, principal.organization_id, principal.project_id, object_ref_id
        )
        assert row is not None
        return AttachmentDownloadOut(
            object_ref_id=object_ref_id,
            mime_type=str(row["mime_type"]),
            size_bytes=int(row["size_bytes"]),
            content_digest=str(row["content_digest"]),
            content_base64=base64.b64encode(data).decode("ascii"),
        )
    except EvaluateError as exc:
        _map_error(exc)
