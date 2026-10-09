"""Bounded annotation queue read APIs."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from evaluate.api.listing import keyset_page
from evaluate.config import Settings
from evaluate.db import repository as repo
from evaluate.db.postgres import PgConn
from evaluate.domains.annotation.schemas import AnnotationItemOut, AnnotationQueueOut
from evaluate.domains.common_schemas import PagedResponse, PageMeta
from evaluate.errors import NotFoundError


def list_queues(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[AnnotationQueueOut]:
    rows, total, lim, next_cursor = keyset_page(
        settings,
        limit=limit,
        cursor=cursor,
        count=lambda: repo.count_annotation_queues(conn, org_id, project_id),
        fetch=lambda **kw: repo.list_annotation_queues(conn, org_id, project_id, **kw),
    )
    return PagedResponse(
        items=[AnnotationQueueOut.model_validate(r) for r in rows],
        meta=PageMeta(total=total, limit=lim, next_cursor=next_cursor),
    )


def get_queue(conn: PgConn, org_id: UUID, project_id: UUID, queue_id: UUID) -> AnnotationQueueOut:
    row = repo.get_annotation_queue(conn, org_id, project_id, queue_id)
    if not row:
        raise NotFoundError("annotation queue not found")
    return AnnotationQueueOut.model_validate(row)


def list_items(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    queue_id: UUID | None,
    status: str | None,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[AnnotationItemOut]:
    def count() -> int:
        return repo.count_annotation_items(
            conn, org_id, project_id, queue_id=queue_id, status=status
        )

    def fetch(**kw: Any) -> list[dict[str, Any]]:
        return repo.list_annotation_items(
            conn, org_id, project_id, queue_id=queue_id, status=status, **kw
        )

    rows, total, lim, next_cursor = keyset_page(
        settings, limit=limit, cursor=cursor, count=count, fetch=fetch
    )
    return PagedResponse(
        items=[AnnotationItemOut.model_validate(r) for r in rows],
        meta=PageMeta(total=total, limit=lim, next_cursor=next_cursor),
    )


def get_item(conn: PgConn, org_id: UUID, project_id: UUID, item_id: UUID) -> AnnotationItemOut:
    row = repo.get_annotation_item(conn, org_id, project_id, item_id)
    if not row:
        raise NotFoundError("annotation item not found")
    return AnnotationItemOut.model_validate(row)
