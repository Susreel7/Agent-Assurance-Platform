"""HTTP handlers for online evaluator rules."""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from evaluate.api.deps import db_conn, scoped_internal, settings_dep
from evaluate.auth.schemas import InternalPrincipal
from evaluate.config import Settings
from evaluate.db.postgres import PgConn
from evaluate.domains.common_schemas import PagedResponse
from evaluate.domains.online_rules import read_service as online_reads
from evaluate.domains.online_rules import service
from evaluate.domains.online_rules.schemas import (
    AlertOut,
    ObserveWebhookEvent,
    OnlineRuleCreate,
    OnlineRuleOut,
)
from evaluate.errors import EvaluateError, ValidationError

router = APIRouter(
    prefix="/v1/orgs/{org_id}/projects/{project_id}/online-rules", tags=["online-rules"]
)


def _map_error(exc: EvaluateError) -> NoReturn:
    from fastapi import HTTPException

    status = 400
    if exc.code == "not_found":
        status = 404
    raise HTTPException(
        status_code=status, detail={"code": exc.code, "message": exc.message}
    ) from exc


@router.get("/alerts", response_model=PagedResponse[AlertOut])
def list_alerts(
    status: str | None = Query(default=None),
    rule_id: UUID | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=500),
    cursor: str | None = Query(default=None),
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> PagedResponse[AlertOut]:
    try:
        return online_reads.list_alerts(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            status=status,
            rule_id=rule_id,
            limit=limit,
            cursor=cursor,
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.get("/alerts/{alert_id}", response_model=AlertOut)
def get_alert(
    alert_id: UUID,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> AlertOut:
    try:
        return online_reads.get_alert(
            conn, principal.organization_id, principal.project_id, alert_id
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.post("/alerts/{alert_id}/retry", response_model=AlertOut)
def retry_alert(
    alert_id: UUID,
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> AlertOut:
    try:
        return online_reads.retry_alert(
            conn,
            settings,
            principal.organization_id,
            principal.project_id,
            alert_id,
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.post("/alerts/{alert_id}/acknowledge", response_model=AlertOut)
def acknowledge_alert(
    alert_id: UUID,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> AlertOut:
    try:
        return online_reads.acknowledge_alert(
            conn, principal.organization_id, principal.project_id, alert_id
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.get("", response_model=PagedResponse[OnlineRuleOut])
def list_rules(
    limit: int | None = Query(default=None, ge=1, le=500),
    cursor: str | None = Query(default=None),
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> PagedResponse[OnlineRuleOut]:
    try:
        return online_reads.list_rules(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            limit=limit,
            cursor=cursor,
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.get("/{rule_id}", response_model=OnlineRuleOut)
def get_rule(
    rule_id: UUID,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> OnlineRuleOut:
    try:
        return online_reads.get_rule(conn, principal.organization_id, principal.project_id, rule_id)
    except EvaluateError as exc:
        _map_error(exc)


@router.post("", status_code=201)
def create_rule(
    payload: OnlineRuleCreate,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> dict[str, str]:
    try:
        rid = service.create_rule(
            conn,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            payload=payload.model_dump(mode="json"),
        )
        return {"id": str(rid)}
    except EvaluateError as exc:
        _map_error(exc)


@router.post("/{rule_id}/events", status_code=202)
def observe_webhook(
    rule_id: UUID,
    event: ObserveWebhookEvent,
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> dict[str, str | None]:
    try:
        if (
            event.organization_id != principal.organization_id
            or event.project_id != principal.project_id
        ):
            raise ValidationError("event org/project must match headers")
        job_id = service.ingest_trace_event(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            rule_id=rule_id,
            trace_id=event.trace_id,
            metadata=event.metadata,
        )
        return {"job_id": str(job_id) if job_id else None}
    except EvaluateError as exc:
        _map_error(exc)
