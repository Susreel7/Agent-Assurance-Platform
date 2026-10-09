"""Label pointer and promotion logic."""

from __future__ import annotations

from uuid import UUID

from prompt.auth.rbac import assert_may_promote_label
from prompt.config import PROTECTED_LABELS, Settings
from prompt.db import repository as repo
from prompt.db.postgres import PgConn
from prompt.domains.artifacts import service as artifact_service
from prompt.domains.labels.schemas import (
    CompareLabelsRequest,
    LabelHistoryEntry,
    LabelHistoryResponse,
    LabelOut,
    PromoteLabelRequest,
)
from prompt.errors import AuthorizationError, ConflictError, NotFoundError
from prompt.validation.dependencies import (
    assert_production_dependencies_resolvable,
    parse_dependencies,
)


def promote_label(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    artifact_key: str,
    payload: PromoteLabelRequest,
    actor: str,
    scopes: list[str],
) -> LabelOut:
    artifact = repo.get_artifact_by_key(conn, org_id, project_id, artifact_key)
    if artifact is None:
        raise NotFoundError(f"artifact {artifact_key} not found")

    revision = repo.get_revision(conn, org_id, project_id, payload.revision_id)
    if revision is None or revision.artifact_id != artifact.id:
        raise NotFoundError("revision not found for artifact")

    label_name = payload.label_name.strip().lower()
    try:
        assert_may_promote_label(scopes, label_name)
    except AuthorizationError:
        repo.insert_audit(
            conn,
            org_id=org_id,
            project_id=project_id,
            action="label.promote.denied",
            resource_type="label",
            resource_id=artifact.id,
            actor=actor,
            detail={"label_name": label_name, "reason": "missing_scope"},
        )
        raise
    if label_name in PROTECTED_LABELS or label_name == "production":
        artifact_service.ensure_not_draft_for_production(revision, label_name)
    if label_name == "production":
        stored = repo.list_revision_dependencies(conn, org_id, revision.id)
        dep_refs = parse_dependencies(
            [
                {
                    "artifact_key": d["dependency_artifact_key"],
                    "label": d.get("dependency_label"),
                    "revision_id": d.get("dependency_revision_id"),
                }
                for d in stored
            ]
        )
        assert_production_dependencies_resolvable(
            conn, org_id=org_id, project_id=project_id, dependencies=dep_refs
        )

    existing = repo.get_label(conn, org_id, project_id, artifact.id, label_name)
    if existing is not None and payload.expected_version is None:
        raise ConflictError("expected_version required when updating an existing label")

    from_revision_id = existing.revision_id if existing else None
    try:
        row = repo.upsert_label_cas(
            conn,
            org_id=org_id,
            project_id=project_id,
            artifact_id=artifact.id,
            label_name=label_name,
            to_revision_id=payload.revision_id,
            expected_version=payload.expected_version,
            actor=actor,
            action="promote",
            from_revision_id=from_revision_id,
            detail={"artifact_key": artifact_key},
        )
    except ValueError as exc:
        if str(exc) == "label_version_conflict":
            raise ConflictError("label version conflict; refresh and retry") from exc
        raise

    repo.insert_audit(
        conn,
        org_id=org_id,
        project_id=project_id,
        action="label.promote",
        resource_type="label",
        resource_id=artifact.id,
        actor=actor,
        detail={
            "label_name": label_name,
            "revision_id": str(payload.revision_id),
            "version": row.version,
        },
    )
    return LabelOut(
        artifact_id=row.artifact_id,
        label_name=row.label_name,
        revision_id=row.revision_id,
        version=row.version,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


def get_label(
    conn: PgConn, org_id: UUID, project_id: UUID, artifact_key: str, label_name: str
) -> LabelOut:
    artifact = repo.get_artifact_by_key(conn, org_id, project_id, artifact_key)
    if artifact is None:
        raise NotFoundError(f"artifact {artifact_key} not found")
    row = repo.get_label(conn, org_id, project_id, artifact.id, label_name.strip().lower())
    if row is None:
        raise NotFoundError(f"label {label_name} not set")
    return LabelOut(
        artifact_id=row.artifact_id,
        label_name=row.label_name,
        revision_id=row.revision_id,
        version=row.version,
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


def label_history(
    conn: PgConn,
    org_id: UUID,
    project_id: UUID,
    artifact_key: str,
    limit: int,
    label_name: str | None = None,
) -> LabelHistoryResponse:
    artifact = repo.get_artifact_by_key(conn, org_id, project_id, artifact_key)
    if artifact is None:
        raise NotFoundError(f"artifact {artifact_key} not found")
    rows = repo.list_label_history(
        conn, org_id, project_id, artifact.id, limit, label_name=label_name
    )
    items = [
        LabelHistoryEntry(
            id=r["id"],
            label_name=r["label_name"],
            from_revision_id=r["from_revision_id"],
            to_revision_id=r["to_revision_id"],
            label_version=r["label_version"],
            action=r["action"],
            actor=r["actor"],
            created_at=r["created_at"],
            detail=dict(r.get("detail") or {}),
        )
        for r in rows
    ]
    return LabelHistoryResponse(items=items)


def compare_labels(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    artifact_key: str,
    payload: CompareLabelsRequest,
) -> dict[str, object]:
    left = get_label(conn, org_id, project_id, artifact_key, payload.left_label)
    right = get_label(conn, org_id, project_id, artifact_key, payload.right_label)
    diff = artifact_service.diff_revisions(
        conn,
        settings,
        org_id=org_id,
        project_id=project_id,
        artifact_key=artifact_key,
        from_revision_id=left.revision_id,
        to_revision_id=right.revision_id,
        mode="structured",
    )
    return {
        "left_label": payload.left_label,
        "right_label": payload.right_label,
        "diff": diff.model_dump(),
    }
