"""Audit HTTP handlers."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from prompt.api.deps import db_conn, scoped_internal, settings_dep
from prompt.auth.schemas import InternalPrincipal
from prompt.config import Settings
from prompt.db.postgres import PgConn
from prompt.domains.audit import service
from prompt.domains.audit.schemas import AuditListResponse

router = APIRouter(prefix="/v1/orgs/{org_id}/projects/{project_id}/audit", tags=["audit"])


@router.get("", response_model=AuditListResponse)
def list_audit(
    resource_type: str | None = Query(default=None),
    action: str | None = Query(default=None),
    actor: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    cursor: datetime | None = Query(default=None),
    limit: int | None = Query(default=None),
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> AuditListResponse:
    lim = limit or settings.list_default_limit
    lim = min(lim, settings.list_max_limit)
    return service.list_audit_events(
        conn,
        org_id=principal.organization_id,
        project_id=principal.project_id,
        resource_type=resource_type,
        action=action,
        actor=actor,
        since=since,
        until=until,
        cursor=cursor,
        limit=lim,
    )


@router.get("/export")
def export_audit(
    resource_type: str | None = Query(default=None),
    action: str | None = Query(default=None),
    actor: str | None = Query(default=None),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int | None = Query(default=None),
    format: str = Query(default="ndjson", alias="format"),
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> PlainTextResponse:
    lim = limit or settings.list_max_limit
    lim = min(lim, settings.list_max_limit)
    if format != "ndjson":
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail="only ndjson export is supported")
    body = service.export_audit_ndjson(
        conn,
        org_id=principal.organization_id,
        project_id=principal.project_id,
        resource_type=resource_type,
        action=action,
        actor=actor,
        since=since,
        until=until,
        limit=lim,
    )
    return PlainTextResponse(body, media_type="application/x-ndjson")
