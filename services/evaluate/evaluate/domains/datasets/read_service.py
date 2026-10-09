"""Bounded read APIs for datasets (no raw example bodies)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from evaluate.api.listing import example_keyset_page, keyset_page
from evaluate.config import Settings
from evaluate.db import repository as repo
from evaluate.db.postgres import PgConn
from evaluate.domains.common_schemas import PagedResponse, PageMeta
from evaluate.domains.datasets.schemas import DatasetOut, DatasetRevisionOut, ExampleSummaryOut
from evaluate.errors import NotFoundError


def _dataset_out(row: dict[str, Any]) -> DatasetOut:
    return DatasetOut(
        id=row["id"],
        dataset_key=row["dataset_key"],
        display_name=row["display_name"],
        description=row["description"],
        tags=row["tags"],
        created_at=row["created_at"],
        created_by=row["created_by"],
    )


def _revision_out(row: dict[str, Any]) -> DatasetRevisionOut:
    return DatasetRevisionOut(
        id=row["id"],
        dataset_id=row["dataset_id"],
        revision_number=row["revision_number"],
        manifest_digest=row["manifest_digest"],
        example_count=row["example_count"],
        created_at=row["created_at"],
        created_by=row["created_by"],
    )


def _example_summary(row: dict[str, Any]) -> ExampleSummaryOut:
    return ExampleSummaryOut(
        id=row["id"],
        example_key=row["example_key"],
        ordinal=row["ordinal"],
        split_name=row["split_name"],
        tags=row["tags"],
        metadata=row["metadata"] if isinstance(row["metadata"], dict) else {},
        content_digest=row["content_digest"],
        source_trace_id=row.get("source_trace_id"),
        has_encrypted_payload=bool(row["has_encrypted_payload"]),
        has_input_object=bool(row.get("has_input_object")),
        has_reference_object=bool(row.get("has_reference_object")),
        created_at=row["created_at"],
    )


def list_datasets(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    q: str | None,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[DatasetOut]:
    rows, total, lim, next_cursor = keyset_page(
        settings,
        limit=limit,
        cursor=cursor,
        count=lambda: repo.count_datasets(conn, org_id, project_id, q=q),
        fetch=lambda **kw: repo.search_datasets(conn, org_id, project_id, q=q, **kw),
    )
    return PagedResponse(
        items=[_dataset_out(r) for r in rows],
        meta=PageMeta(total=total, limit=lim, next_cursor=next_cursor),
    )


def get_dataset_by_key(
    conn: PgConn, org_id: UUID, project_id: UUID, dataset_key: str
) -> DatasetOut:
    row = repo.get_dataset_by_key(conn, org_id, project_id, dataset_key)
    if not row:
        raise NotFoundError("dataset not found")
    return _dataset_out(row)


def list_revisions(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    dataset_key: str,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[DatasetRevisionOut]:
    ds = repo.get_dataset_by_key(conn, org_id, project_id, dataset_key)
    if not ds:
        raise NotFoundError("dataset not found")
    dataset_id = ds["id"]
    rows, total, lim, next_cursor = keyset_page(
        settings,
        limit=limit,
        cursor=cursor,
        count=lambda: repo.count_dataset_revisions(conn, org_id, dataset_id),
        fetch=lambda **kw: repo.list_dataset_revisions(conn, org_id, dataset_id, **kw),
    )
    return PagedResponse(
        items=[_revision_out(r) for r in rows],
        meta=PageMeta(total=total, limit=lim, next_cursor=next_cursor),
    )


def get_revision(
    conn: PgConn,
    org_id: UUID,
    project_id: UUID,
    dataset_key: str,
    revision_id: UUID,
) -> DatasetRevisionOut:
    ds = repo.get_dataset_by_key(conn, org_id, project_id, dataset_key)
    if not ds:
        raise NotFoundError("dataset not found")
    row = repo.get_dataset_revision(conn, org_id, revision_id)
    if not row or row["dataset_id"] != ds["id"]:
        raise NotFoundError("revision not found")
    return _revision_out(row)


def list_examples(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    dataset_key: str,
    revision_id: UUID,
    split: str | None,
    q: str | None,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[ExampleSummaryOut]:
    ds = repo.get_dataset_by_key(conn, org_id, project_id, dataset_key)
    if not ds:
        raise NotFoundError("dataset not found")
    rev = repo.get_dataset_revision(conn, org_id, revision_id)
    if not rev or rev["dataset_id"] != ds["id"]:
        raise NotFoundError("revision not found")
    rows, total, lim, next_cursor = example_keyset_page(
        settings,
        limit=limit,
        cursor=cursor,
        count=lambda: repo.count_examples(conn, org_id, revision_id, split=split, q=q),
        fetch=lambda **kw: repo.list_example_summaries(
            conn, org_id, revision_id, split=split, q=q, **kw
        ),
    )
    return PagedResponse(
        items=[_example_summary(r) for r in rows],
        meta=PageMeta(total=total, limit=lim, next_cursor=next_cursor),
    )


def get_example(
    conn: PgConn,
    org_id: UUID,
    project_id: UUID,
    dataset_key: str,
    revision_id: UUID,
    example_id: UUID,
) -> ExampleSummaryOut:
    ds = repo.get_dataset_by_key(conn, org_id, project_id, dataset_key)
    if not ds:
        raise NotFoundError("dataset not found")
    rev = repo.get_dataset_revision(conn, org_id, revision_id)
    if not rev or rev["dataset_id"] != ds["id"]:
        raise NotFoundError("revision not found")
    row = repo.get_example_summary(conn, org_id, revision_id, example_id)
    if not row:
        raise NotFoundError("example not found")
    return _example_summary(row)
