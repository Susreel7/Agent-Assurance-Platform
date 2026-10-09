"""Annotation queues, leases, consensus metrics."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from evaluate.config import Settings
from evaluate.db import repository as repo
from evaluate.db.postgres import PgConn
from evaluate.domains.datasets import service as dataset_service
from evaluate.errors import ConflictError, NotFoundError
from evaluate.stats.aggregates import stddev


def create_queue(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    queue_key: str,
    display_name: str,
    item_filter: dict[str, Any],
    rubric: dict[str, Any],
    reviewers_required: int,
    actor: str,
) -> UUID:
    return repo.insert_annotation_queue(
        conn,
        org_id=org_id,
        project_id=project_id,
        queue_key=queue_key,
        display_name=display_name,
        item_filter=item_filter,
        rubric=rubric,
        reviewers_required=reviewers_required,
        actor=actor,
    )


def add_item(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    queue_id: UUID,
    item_type: str,
    reference_id: str,
    pairwise_reference_id: str | None,
    metadata: dict[str, Any],
) -> UUID:
    if not repo.get_annotation_queue(conn, org_id, project_id, queue_id):
        raise NotFoundError("annotation queue not found")
    return repo.insert_annotation_item(
        conn,
        queue_id=queue_id,
        org_id=org_id,
        project_id=project_id,
        item_type=item_type,
        reference_id=reference_id,
        pairwise_reference_id=pairwise_reference_id,
        metadata=metadata,
    )


def claim_item(
    conn: PgConn,
    *,
    org_id: UUID,
    item_id: UUID,
    assignee: str,
    expected_version: int,
    lease_seconds: int,
) -> bool:
    ok = repo.claim_annotation_item(
        conn,
        item_id=item_id,
        org_id=org_id,
        assignee=assignee,
        lease_seconds=lease_seconds,
        expected_version=expected_version,
    )
    if not ok:
        raise ConflictError("annotation lease conflict")
    return True


def submit(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    item_id: UUID,
    assignee: str,
    action: str,
    scores: dict[str, Any],
    comments: str,
    rubric_version: int,
) -> UUID:
    return repo.insert_annotation_submission(
        conn,
        item_id=item_id,
        org_id=org_id,
        project_id=project_id,
        assignee=assignee,
        action=action,
        scores=scores,
        comments=comments,
        rubric_version=rubric_version,
    )


def consensus_metrics(conn: PgConn, item_id: UUID) -> dict[str, Any]:
    subs = repo.list_annotation_submissions(conn, item_id)
    if len(subs) < 2:
        return {"submissions": len(subs), "disagreement": False}
    numeric: list[float] = []
    for s in subs:
        sc = s.get("scores") or {}
        if isinstance(sc, dict) and "rating" in sc:
            try:
                numeric.append(float(sc["rating"]))
            except (TypeError, ValueError):
                continue
    if len(numeric) < 2:
        return {"submissions": len(subs), "disagreement": False}
    spread = max(numeric) - min(numeric)
    return {
        "submissions": len(subs),
        "disagreement": spread > 0.25,
        "spread": spread,
        "stddev": stddev(numeric),
    }


def export_item_to_dataset(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    item_id: UUID,
    dataset_key: str,
    actor: str,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM evaluate.annotation_items
            WHERE id = %s AND organization_id = %s
            """,
            (item_id, org_id),
        )
        item = cur.fetchone()
    if not item:
        raise NotFoundError("annotation item not found")
    subs = repo.list_annotation_submissions(conn, item_id)
    reference = subs[-1]["scores"] if subs else {}
    example = {
        "example_key": f"annotation-{item_id}",
        "input": {"reference_id": item["reference_id"], "type": item["item_type"]},
        "reference_output": reference,
        "metadata": item["metadata"] if isinstance(item["metadata"], dict) else {},
    }
    ds = repo.get_dataset_by_key(conn, org_id, project_id, dataset_key)
    if not ds:
        dataset_service.create_dataset(
            conn,
            settings,
            org_id=org_id,
            project_id=project_id,
            dataset_key=dataset_key,
            display_name=dataset_key,
            description="from annotation export",
            tags=[],
            actor=actor,
        )
    return dataset_service.create_revision(
        conn,
        settings,
        org_id=org_id,
        project_id=project_id,
        dataset_key=dataset_key,
        payload_examples=[example],
        copy_from_revision_id=None,
        actor=actor,
    )
