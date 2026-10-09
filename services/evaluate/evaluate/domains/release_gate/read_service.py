"""Bounded release gate read APIs."""

from __future__ import annotations

from uuid import UUID

from evaluate.api.listing import keyset_page
from evaluate.config import Settings
from evaluate.db import repository as repo
from evaluate.db.postgres import PgConn
from evaluate.domains.common_schemas import PagedResponse, PageMeta
from evaluate.domains.release_gate.schemas import ReleaseGateEvaluationOut, ReleaseGateOut
from evaluate.errors import NotFoundError


def list_gates(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[ReleaseGateOut]:
    rows, total, lim, next_cursor = keyset_page(
        settings,
        limit=limit,
        cursor=cursor,
        count=lambda: repo.count_release_gates(conn, org_id, project_id),
        fetch=lambda **kw: repo.list_release_gates(conn, org_id, project_id, **kw),
    )
    return PagedResponse(
        items=[ReleaseGateOut.model_validate(r) for r in rows],
        meta=PageMeta(total=total, limit=lim, next_cursor=next_cursor),
    )


def get_gate(conn: PgConn, org_id: UUID, project_id: UUID, gate_id: UUID) -> ReleaseGateOut:
    row = repo.get_release_gate(conn, org_id, project_id, gate_id)
    if not row:
        raise NotFoundError("release gate not found")
    return ReleaseGateOut.model_validate(row)


def list_evaluations(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    gate_id: UUID,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[ReleaseGateEvaluationOut]:
    gate = repo.get_release_gate(conn, org_id, project_id, gate_id)
    if not gate:
        raise NotFoundError("release gate not found")
    rows, total, lim, next_cursor = keyset_page(
        settings,
        limit=limit,
        cursor=cursor,
        count=lambda: repo.count_release_gate_evaluations(conn, org_id, gate_id),
        fetch=lambda **kw: repo.list_release_gate_evaluations(conn, org_id, gate_id, **kw),
    )
    return PagedResponse(
        items=[ReleaseGateEvaluationOut.model_validate(r) for r in rows],
        meta=PageMeta(total=total, limit=lim, next_cursor=next_cursor),
    )
