"""HTTP handlers for artifacts and revisions."""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from prompt.api.deps import db_conn, scoped_internal, settings_dep
from prompt.auth.schemas import InternalPrincipal
from prompt.config import Settings
from prompt.db.postgres import PgConn
from prompt.domains.artifacts import service
from prompt.domains.artifacts.schemas import (
    ArtifactCreate,
    ArtifactListResponse,
    ArtifactOut,
    CompareRevisionsRequest,
    DiffRequest,
    DiffResponse,
    RevisionCreate,
    RevisionDetailOut,
    RevisionListResponse,
    RollbackRequest,
)
from prompt.errors import PromptError

router = APIRouter(prefix="/v1/orgs/{org_id}/projects/{project_id}/artifacts", tags=["artifacts"])


def _map_error(exc: PromptError) -> NoReturn:
    from fastapi import HTTPException

    status = 400
    if exc.code == "not_found":
        status = 404
    elif exc.code == "conflict":
        status = 409
    elif exc.code == "precondition_failed":
        status = 412
    elif exc.code == "payload_too_large":
        status = 413
    raise HTTPException(
        status_code=status, detail={"code": exc.code, "message": exc.message}
    ) from exc


@router.post("", response_model=ArtifactOut, status_code=201)
def create_artifact(
    payload: ArtifactCreate,
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> ArtifactOut:
    try:
        return service.create_artifact(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            payload=payload,
            actor=principal.actor,
        )
    except PromptError as exc:
        _map_error(exc)


@router.get("", response_model=ArtifactListResponse)
def list_artifacts(
    kind: str | None = Query(default=None),
    q: str | None = Query(default=None),
    label: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int | None = Query(default=None),
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> ArtifactListResponse:
    lim = limit or settings.list_default_limit
    lim = min(lim, settings.list_max_limit)
    return service.list_artifacts(
        conn,
        org_id=principal.organization_id,
        project_id=principal.project_id,
        kind=kind,
        query=q,
        label=label,
        cursor=cursor,
        limit=lim,
    )


@router.get("/{artifact_key}", response_model=ArtifactOut)
def get_artifact(
    artifact_key: str,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> ArtifactOut:
    try:
        return service.get_artifact(
            conn, principal.organization_id, principal.project_id, artifact_key
        )
    except PromptError as exc:
        _map_error(exc)


@router.post("/{artifact_key}/revisions", response_model=RevisionDetailOut, status_code=201)
def create_revision(
    artifact_key: str,
    payload: RevisionCreate,
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> RevisionDetailOut:
    try:
        return service.create_revision(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            artifact_key=artifact_key,
            payload=payload,
            actor=principal.actor,
        )
    except PromptError as exc:
        _map_error(exc)


@router.get("/{artifact_key}/revisions", response_model=RevisionListResponse)
def list_revisions(
    artifact_key: str,
    limit: int = Query(default=50, ge=1, le=200),
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> RevisionListResponse:
    try:
        return service.list_revisions_for_artifact(
            conn, principal.organization_id, principal.project_id, artifact_key, limit
        )
    except PromptError as exc:
        _map_error(exc)


@router.get("/{artifact_key}/revisions/{revision_id}", response_model=RevisionDetailOut)
def get_revision(
    artifact_key: str,
    revision_id: UUID,
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> RevisionDetailOut:
    try:
        return service.get_revision_detail(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            artifact_key=artifact_key,
            revision_id=revision_id,
        )
    except PromptError as exc:
        _map_error(exc)


@router.post("/{artifact_key}/revisions:diff", response_model=DiffResponse)
def diff_revisions(
    artifact_key: str,
    payload: DiffRequest,
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> DiffResponse:
    try:
        return service.diff_revisions(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            artifact_key=artifact_key,
            from_revision_id=payload.from_revision_id,
            to_revision_id=payload.to_revision_id,
            mode=payload.mode,
        )
    except PromptError as exc:
        _map_error(exc)


@router.post(
    "/{artifact_key}/revisions:rollback", response_model=RevisionDetailOut, status_code=201
)
def rollback(
    artifact_key: str,
    payload: RollbackRequest,
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> RevisionDetailOut:
    try:
        return service.rollback_revision(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            artifact_key=artifact_key,
            target_revision_id=payload.target_revision_id,
            is_draft=payload.is_draft,
            actor=principal.actor,
        )
    except PromptError as exc:
        _map_error(exc)


@router.post("/{artifact_key}/revisions:compare")
def compare_revisions(
    artifact_key: str,
    payload: CompareRevisionsRequest,
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> dict[str, object]:
    diffs: list[dict[str, object]] = []
    try:
        base = payload.revision_ids[0]
        for other in payload.revision_ids[1:]:
            diff = service.diff_revisions(
                conn,
                settings,
                org_id=principal.organization_id,
                project_id=principal.project_id,
                artifact_key=artifact_key,
                from_revision_id=base,
                to_revision_id=other,
                mode="structured",
            )
            diffs.append(diff.model_dump())
        return {"base_revision_id": str(base), "comparisons": diffs}
    except PromptError as exc:
        _map_error(exc)
