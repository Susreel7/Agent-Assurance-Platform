"""HTTP handlers for scores."""

from __future__ import annotations

from typing import NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Path, Query

from evaluate.api.deps import db_conn, scoped_internal, settings_dep
from evaluate.auth.schemas import InternalPrincipal
from evaluate.auth.workload import introspect_bearer
from evaluate.config import Settings, get_settings
from evaluate.db.postgres import PgConn
from evaluate.domains.common_schemas import PagedResponse
from evaluate.domains.scores import read_service as score_reads
from evaluate.domains.scores import service
from evaluate.domains.scores.schemas import ScoreCorrection, ScoreCreate, ScoreDetailOut, ScoreOut
from evaluate.errors import AuthenticationError, AuthorizationError, EvaluateError

router = APIRouter(prefix="/v1/orgs/{org_id}/projects/{project_id}/scores", tags=["scores"])


def _map_error(exc: EvaluateError) -> NoReturn:
    from fastapi import HTTPException

    status = 400
    if exc.code == "not_found":
        status = 404
    elif exc.code in ("authentication_error",):
        status = 401
    elif exc.code in ("authorization_error",):
        status = 403
    raise HTTPException(
        status_code=status, detail={"code": exc.code, "message": exc.message}
    ) from exc


@router.get("", response_model=PagedResponse[ScoreDetailOut])
def list_scores(
    target_type: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    name: str | None = Query(default=None),
    source: str | None = Query(default=None),
    limit: int | None = Query(default=None, ge=1, le=500),
    cursor: str | None = Query(default=None),
    conn: PgConn = Depends(db_conn),
    settings: Settings = Depends(settings_dep),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> PagedResponse[ScoreDetailOut]:
    try:
        return score_reads.list_scores(
            conn,
            settings,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            target_type=target_type,
            target_id=target_id,
            name=name,
            source=source,
            limit=limit,
            cursor=cursor,
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.get("/{score_id}", response_model=ScoreDetailOut)
def get_score(
    score_id: UUID,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> ScoreDetailOut:
    try:
        return score_reads.get_score(
            conn, principal.organization_id, principal.project_id, score_id
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.post("", response_model=ScoreOut, status_code=201)
async def create_score(
    payload: ScoreCreate,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> ScoreOut:
    try:
        sid = service.create_score(
            conn,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            payload=payload,
            actor=principal.actor,
        )
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM evaluate.scores WHERE id = %s", (sid,))
            row = cur.fetchone()
        assert row
        return ScoreOut(
            id=row["id"],
            target_type=row["target_type"],
            target_id=row["target_id"],
            name=row["name"],
            value_type=row["value_type"],
            source=row["source"],
            created_at=row["created_at"],
            created_by=row["created_by"],
        )
    except EvaluateError as exc:
        _map_error(exc)


@router.post("/workload", response_model=ScoreOut, status_code=201)
async def create_score_workload(
    payload: ScoreCreate,
    conn: PgConn = Depends(db_conn),
    org_id: UUID = Path(...),
    project_id: UUID = Path(...),
    authorization: str | None = Header(default=None, alias="Authorization"),
) -> ScoreOut:
    settings = get_settings()
    try:
        principal = await introspect_bearer(
            settings, authorization, required_scope="evaluate:score"
        )
        if principal.organization_id != org_id or principal.project_id != project_id:
            raise AuthorizationError("token org/project must match path")
        sid = service.create_score(
            conn,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            payload=payload,
            actor=principal.subject,
        )
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM evaluate.scores WHERE id = %s", (sid,))
            row = cur.fetchone()
        assert row
        return ScoreOut(
            id=row["id"],
            target_type=row["target_type"],
            target_id=row["target_id"],
            name=row["name"],
            value_type=row["value_type"],
            source=row["source"],
            created_at=row["created_at"],
            created_by=row["created_by"],
        )
    except (AuthenticationError, AuthorizationError) as exc:
        _map_error(exc)


@router.post("/{score_id}/corrections", response_model=ScoreOut, status_code=201)
def correct_score(
    score_id: UUID,
    payload: ScoreCorrection,
    conn: PgConn = Depends(db_conn),
    principal: InternalPrincipal = Depends(scoped_internal),
) -> ScoreOut:
    try:
        cid = service.correct_score(
            conn,
            org_id=principal.organization_id,
            project_id=principal.project_id,
            original_score_id=score_id,
            payload=payload.corrected,
            reason=payload.reason,
            actor=principal.actor,
        )
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM evaluate.scores WHERE id = %s", (cid,))
            row = cur.fetchone()
        assert row
        return ScoreOut(
            id=row["id"],
            target_type=row["target_type"],
            target_id=row["target_id"],
            name=row["name"],
            value_type=row["value_type"],
            source=row["source"],
            created_at=row["created_at"],
            created_by=row["created_by"],
        )
    except EvaluateError as exc:
        _map_error(exc)
