"""Bounded evaluator read APIs."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from evaluate.api.listing import keyset_page
from evaluate.config import Settings
from evaluate.db import repository as repo
from evaluate.db.postgres import PgConn
from evaluate.domains.common_schemas import PagedResponse, PageMeta
from evaluate.domains.evaluators.schemas import EvaluatorOut, EvaluatorRevisionSummaryOut
from evaluate.errors import NotFoundError


def list_evaluators(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    q: str | None,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[EvaluatorOut]:
    rows, total, lim, next_cursor = keyset_page(
        settings,
        limit=limit,
        cursor=cursor,
        count=lambda: repo.count_evaluators(conn, org_id, project_id, q=q),
        fetch=lambda **kw: repo.list_evaluators(conn, org_id, project_id, q=q, **kw),
    )
    return PagedResponse(
        items=[
            EvaluatorOut(
                id=r["id"],
                evaluator_key=r["evaluator_key"],
                display_name=r["display_name"],
                kind=r["kind"],
                created_at=r["created_at"],
                created_by=r["created_by"],
            )
            for r in rows
        ],
        meta=PageMeta(total=total, limit=lim, next_cursor=next_cursor),
    )


def get_evaluator(conn: PgConn, org_id: UUID, project_id: UUID, evaluator_key: str) -> EvaluatorOut:
    row = repo.get_evaluator_by_key(conn, org_id, project_id, evaluator_key)
    if not row:
        raise NotFoundError("evaluator not found")
    return EvaluatorOut(
        id=row["id"],
        evaluator_key=row["evaluator_key"],
        display_name=row["display_name"],
        kind=row["kind"],
        created_at=row["created_at"],
        created_by=row["created_by"],
    )


def list_revisions(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    evaluator_key: str,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[EvaluatorRevisionSummaryOut]:
    ev = repo.get_evaluator_by_key(conn, org_id, project_id, evaluator_key)
    if not ev:
        raise NotFoundError("evaluator not found")
    ev_id = ev["id"]
    rows, total, lim, next_cursor = keyset_page(
        settings,
        limit=limit,
        cursor=cursor,
        count=lambda: repo.count_evaluator_revisions(conn, org_id, ev_id),
        fetch=lambda **kw: repo.list_evaluator_revisions(conn, org_id, ev_id, **kw),
    )

    def _rev(row: dict[str, Any]) -> EvaluatorRevisionSummaryOut:
        return EvaluatorRevisionSummaryOut(
            id=row["id"],
            evaluator_id=row["evaluator_id"],
            evaluator_key=str(row.get("evaluator_key") or evaluator_key),
            kind=str(row.get("kind") or ev["kind"]),
            revision_number=row["revision_number"],
            config_digest=row["config_digest"],
            created_at=row["created_at"],
            created_by=row["created_by"],
        )

    return PagedResponse(
        items=[_rev(r) for r in rows],
        meta=PageMeta(total=total, limit=lim, next_cursor=next_cursor),
    )


def get_revision(
    conn: PgConn,
    org_id: UUID,
    project_id: UUID,
    evaluator_key: str,
    revision_id: UUID,
) -> EvaluatorRevisionSummaryOut:
    ev = repo.get_evaluator_by_key(conn, org_id, project_id, evaluator_key)
    if not ev:
        raise NotFoundError("evaluator not found")
    row = repo.get_evaluator_revision(conn, org_id, revision_id)
    if not row or row["evaluator_id"] != ev["id"]:
        raise NotFoundError("revision not found")
    return EvaluatorRevisionSummaryOut(
        id=row["id"],
        evaluator_id=row["evaluator_id"],
        evaluator_key=str(row.get("evaluator_key") or evaluator_key),
        kind=str(row.get("kind") or ev["kind"]),
        revision_number=row["revision_number"],
        config_digest=row["config_digest"],
        created_at=row["created_at"],
        created_by=row["created_by"],
    )
