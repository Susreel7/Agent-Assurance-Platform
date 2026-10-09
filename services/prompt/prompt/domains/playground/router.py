"""Playground HTTP handlers."""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import StreamingResponse

from prompt.api.deps import db_conn, scoped_internal, settings_dep
from prompt.auth.schemas import InternalPrincipal
from prompt.config import Settings
from prompt.db.postgres import PgConn
from prompt.domains.playground import service
from prompt.domains.playground.schemas import (
    PlaygroundCancelResponse,
    PlaygroundRunRequest,
    PlaygroundRunResponse,
    PlaygroundRunStatusOut,
)
from prompt.domains.playground.streaming import stream_router_sse
from prompt.errors import PromptError

router = APIRouter(prefix="/v1/orgs/{org_id}/projects/{project_id}/playground", tags=["playground"])


def _map_error(exc: PromptError) -> NoReturn:
    from fastapi import HTTPException

    status = 400
    if exc.code == "not_found":
        status = 404
    elif exc.code == "router_upstream_error":
        status = 502
    raise HTTPException(
        status_code=status, detail={"code": exc.code, "message": exc.message}
    ) from exc


def _workload_bearer(workload_authorization: str | None) -> str | None:
    if workload_authorization and workload_authorization.lower().startswith("bearer "):
        return workload_authorization.split(" ", 1)[1].strip()
    return None


@router.post("/runs", status_code=201, response_model=None)
async def create_run(
    payload: PlaygroundRunRequest,
    request: Request,
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
    workload_authorization: str | None = Header(default=None, alias="X-Workload-Authorization"),
) -> PlaygroundRunResponse | StreamingResponse:
    bearer = _workload_bearer(workload_authorization)
    try:
        if payload.stream:
            run_id, _resolved, body = await service.prepare_playground_run(
                conn, settings, principal=principal, payload=payload
            )

            async def disconnect() -> bool:
                return await request.is_disconnected()

            stream = stream_router_sse(
                settings,
                org_id=principal.organization_id,
                project_id=principal.project_id,
                run_id=run_id,
                request_body=body,
                workload_bearer=bearer,
                disconnect=disconnect,
            )
            return StreamingResponse(
                stream,
                media_type="text/event-stream",
                headers={
                    "X-Playground-Run-Id": str(run_id),
                    "Cache-Control": "no-cache",
                },
            )
        return await service.run_playground(
            conn,
            settings,
            principal=principal,
            payload=payload,
            workload_bearer=bearer,
        )
    except PromptError as exc:
        _map_error(exc)


@router.get("/runs/{run_id}", response_model=PlaygroundRunStatusOut)
def get_run(
    run_id: UUID,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> PlaygroundRunStatusOut:
    try:
        row = service.get_playground_run_status(
            conn, principal.organization_id, principal.project_id, run_id
        )
        return PlaygroundRunStatusOut(
            run_id=row["id"],
            status=row["status"],
            mode=row["mode"],
            resolved_revision_ids=list(row["resolved_revision_ids"]),
            model_alias=row.get("model_alias"),
            router_request_id=row.get("router_request_id"),
            router_trace=dict(row.get("router_trace") or {}),
            input_digest=row.get("input_digest"),
            output_digest=row.get("output_digest"),
            error_message=row.get("error_message"),
        )
    except PromptError as exc:
        _map_error(exc)


@router.post("/runs/{run_id}:cancel", response_model=PlaygroundCancelResponse)
async def cancel_run(
    run_id: UUID,
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> PlaygroundCancelResponse:
    try:
        cancelled = await service.cancel_playground_run(
            conn,
            settings,
            principal.organization_id,
            principal.project_id,
            run_id,
        )
        row = service.get_playground_run_status(
            conn, principal.organization_id, principal.project_id, run_id
        )
        return PlaygroundCancelResponse(
            run_id=run_id,
            status=str(row["status"]),
            cancelled=cancelled,
        )
    except PromptError as exc:
        _map_error(exc)


@router.post("/runs/{run_id}:replay", response_model=PlaygroundRunResponse, status_code=201)
async def replay_run(
    run_id: UUID,
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
    workload_authorization: str | None = Header(default=None, alias="X-Workload-Authorization"),
) -> PlaygroundRunResponse:
    bearer = _workload_bearer(workload_authorization)
    try:
        return await service.replay_playground(
            conn,
            settings,
            principal=principal,
            run_id=run_id,
            workload_bearer=bearer,
        )
    except PromptError as exc:
        _map_error(exc)
