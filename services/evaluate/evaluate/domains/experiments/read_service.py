"""Bounded experiment read APIs."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from evaluate.api.listing import keyset_page
from evaluate.config import Settings
from evaluate.db import repository as repo
from evaluate.db.postgres import PgConn
from evaluate.domains.common_schemas import PagedResponse, PageMeta
from evaluate.domains.experiments.schemas import ExperimentOut
from evaluate.errors import NotFoundError


def _exp_out(row: dict[str, Any]) -> ExperimentOut:
    return ExperimentOut(
        id=row["id"],
        experiment_key=row["experiment_key"],
        display_name=row["display_name"],
        status=row["status"],
        dataset_revision_id=row["dataset_revision_id"],
        spec_digest=row["spec_digest"],
        seed=row["seed"],
        repetitions=row["repetitions"],
        concurrency=row["concurrency"],
        progress=row["progress"] if isinstance(row["progress"], dict) else {},
        aggregates=row["aggregates"] if isinstance(row["aggregates"], dict) else {},
        created_at=row["created_at"],
    )


def list_experiments(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    q: str | None,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[ExperimentOut]:
    rows, total, lim, next_cursor = keyset_page(
        settings,
        limit=limit,
        cursor=cursor,
        count=lambda: repo.count_experiments(conn, org_id, project_id, q=q),
        fetch=lambda **kw: repo.list_experiments(conn, org_id, project_id, q=q, **kw),
    )
    return PagedResponse(
        items=[_exp_out(r) for r in rows],
        meta=PageMeta(total=total, limit=lim, next_cursor=next_cursor),
    )


def get_experiment(
    conn: PgConn, org_id: UUID, project_id: UUID, experiment_id: UUID
) -> ExperimentOut:
    row = repo.get_experiment(conn, org_id, project_id, experiment_id)
    if not row:
        raise NotFoundError("experiment not found")
    return _exp_out(row)


def get_experiment_by_key(
    conn: PgConn, org_id: UUID, project_id: UUID, experiment_key: str
) -> ExperimentOut:
    row = repo.get_experiment_by_key(conn, org_id, project_id, experiment_key)
    if not row:
        raise NotFoundError("experiment not found")
    return _exp_out(row)
