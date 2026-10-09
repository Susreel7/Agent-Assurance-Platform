"""Bounded score list/get APIs."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from evaluate.api.listing import keyset_page
from evaluate.config import Settings
from evaluate.db import repository as repo
from evaluate.db.postgres import PgConn
from evaluate.domains.common_schemas import PagedResponse, PageMeta
from evaluate.domains.scores.schemas import ScoreDetailOut
from evaluate.errors import NotFoundError


def _score_out(row: dict[str, Any]) -> ScoreDetailOut:
    return ScoreDetailOut(
        id=row["id"],
        target_type=row["target_type"],
        target_id=row["target_id"],
        name=row["name"],
        value_type=row["value_type"],
        value_numeric=row.get("value_numeric"),
        value_boolean=row.get("value_boolean"),
        value_categorical=row.get("value_categorical"),
        source=row["source"],
        evaluator_revision_id=row.get("evaluator_revision_id"),
        explanation=row.get("explanation"),
        metadata=row["metadata"] if isinstance(row["metadata"], dict) else {},
        supersedes_score_id=row.get("supersedes_score_id"),
        created_at=row["created_at"],
        created_by=row["created_by"],
    )


def list_scores(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    target_type: str | None,
    target_id: str | None,
    name: str | None,
    source: str | None,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[ScoreDetailOut]:
    def count() -> int:
        return repo.count_scores(
            conn,
            org_id,
            project_id,
            target_type=target_type,
            target_id=target_id,
            name=name,
            source=source,
        )

    def fetch(**kw: Any) -> list[dict[str, Any]]:
        return repo.list_scores(
            conn,
            org_id,
            project_id,
            target_type=target_type,
            target_id=target_id,
            name=name,
            source=source,
            **kw,
        )

    rows, total, lim, next_cursor = keyset_page(
        settings, limit=limit, cursor=cursor, count=count, fetch=fetch
    )
    return PagedResponse(
        items=[_score_out(r) for r in rows],
        meta=PageMeta(total=total, limit=lim, next_cursor=next_cursor),
    )


def get_score(conn: PgConn, org_id: UUID, project_id: UUID, score_id: UUID) -> ScoreDetailOut:
    row = repo.get_score(conn, org_id, project_id, score_id)
    if not row:
        raise NotFoundError("score not found")
    return _score_out(row)
