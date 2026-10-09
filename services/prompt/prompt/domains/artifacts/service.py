"""Artifact and revision business logic."""

from __future__ import annotations

import difflib
import json
from typing import Any
from uuid import UUID

from prompt.config import Settings
from prompt.db import repository as repo
from prompt.db.postgres import PgConn
from prompt.domains.artifacts.schemas import (
    ArtifactCreate,
    ArtifactDependencyRef,
    ArtifactListResponse,
    ArtifactOut,
    DiffHunk,
    DiffResponse,
    RevisionCreate,
    RevisionDetailOut,
    RevisionListResponse,
    RevisionSummaryOut,
)
from prompt.errors import ConflictError, NotFoundError, PreconditionFailedError, ValidationError
from prompt.providers.encryption.factory import resolve_encryption_provider
from prompt.validation.canonicalize import digest_config, digest_content, digest_schema
from prompt.validation.dependencies import (
    assert_no_dependency_cycles,
    parse_dependencies,
    validate_dependencies_exist,
)
from prompt.validation.kinds import validate_kind_structure
from prompt.validation.secrets import scan_secrets_in_content


def _artifact_out(row: repo.ArtifactRow) -> ArtifactOut:
    return ArtifactOut(
        id=row.id,
        organization_id=row.organization_id,
        project_id=row.project_id,
        artifact_key=row.artifact_key,
        kind=row.kind,  # type: ignore[arg-type]
        display_name=row.display_name,
        description=row.description,
        tags=[str(t) for t in row.tags],
        created_at=row.created_at,
        created_by=row.created_by,
        updated_at=row.updated_at,
    )


def _revision_summary(row: repo.RevisionRow) -> RevisionSummaryOut:
    return RevisionSummaryOut(
        id=row.id,
        artifact_id=row.artifact_id,
        revision_number=row.revision_number,
        parent_revision_id=row.parent_revision_id,
        is_draft=row.is_draft,
        content_digest=row.content_digest,
        schema_digest=row.schema_digest,
        config_digest=row.config_digest,
        semantic_version=row.semantic_version,
        metadata=row.metadata,
        encryption_key_ref=row.encryption_key_ref,
        secret_scan_warnings=[dict(w) for w in row.secret_scan_warnings],
        created_at=row.created_at,
        created_by=row.created_by,
    )


def _load_revision_content(
    conn: PgConn, settings: Settings, row: repo.RevisionRow
) -> dict[str, Any]:
    ciphertext = repo.get_revision_ciphertext(conn, row.organization_id, row.id)
    if ciphertext is None:
        raise NotFoundError("revision body not found")
    provider = resolve_encryption_provider(settings, row.encryption_key_ref)
    plaintext = provider.decrypt(ciphertext)
    payload = json.loads(plaintext.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValidationError("stored revision body is not an object")
    return payload


def create_artifact(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    payload: ArtifactCreate,
    actor: str,
) -> ArtifactOut:
    existing = repo.get_artifact_by_key(conn, org_id, project_id, payload.artifact_key)
    if existing is not None:
        raise ConflictError(f"artifact key {payload.artifact_key} already exists")
    row = repo.insert_artifact(
        conn,
        org_id=org_id,
        project_id=project_id,
        artifact_key=payload.artifact_key,
        kind=payload.kind,
        display_name=payload.display_name,
        description=payload.description,
        tags=payload.tags,
        created_by=actor,
    )
    repo.insert_audit(
        conn,
        org_id=org_id,
        project_id=project_id,
        action="artifact.create",
        resource_type="artifact",
        resource_id=row.id,
        actor=actor,
        detail={"artifact_key": row.artifact_key, "kind": row.kind},
    )
    return _artifact_out(row)


def list_artifacts(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    kind: str | None,
    query: str | None,
    label: str | None,
    cursor: str | None,
    limit: int,
) -> ArtifactListResponse:
    rows, next_cursor = repo.list_artifacts(
        conn,
        org_id=org_id,
        project_id=project_id,
        kind=kind,
        query=query,
        label=label,
        cursor_key=cursor,
        limit=limit,
    )
    return ArtifactListResponse(items=[_artifact_out(r) for r in rows], next_cursor=next_cursor)


def get_artifact(conn: PgConn, org_id: UUID, project_id: UUID, artifact_key: str) -> ArtifactOut:
    row = repo.get_artifact_by_key(conn, org_id, project_id, artifact_key)
    if row is None:
        raise NotFoundError(f"artifact {artifact_key} not found")
    return _artifact_out(row)


def create_revision(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    artifact_key: str,
    payload: RevisionCreate,
    actor: str,
) -> RevisionDetailOut:
    artifact = repo.get_artifact_by_key(conn, org_id, project_id, artifact_key)
    if artifact is None:
        raise NotFoundError(f"artifact {artifact_key} not found")

    validate_kind_structure(
        artifact.kind,
        payload.content,
        input_schema=payload.input_schema,
        max_body_bytes=settings.max_body_bytes,
    )
    warnings = scan_secrets_in_content(payload.content)

    key_ref = payload.encryption_key_ref or settings.default_encryption_key_ref
    provider = resolve_encryption_provider(settings, key_ref)

    body_obj = {
        "content": payload.content,
        "input_schema": payload.input_schema,
        "config": payload.config,
    }
    plaintext = json.dumps(body_obj, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ciphertext = provider.encrypt(plaintext)

    if payload.parent_revision_id is not None:
        parent = repo.get_revision(conn, org_id, project_id, payload.parent_revision_id)
        if parent is None or parent.artifact_id != artifact.id:
            raise ValidationError("parent_revision_id invalid for artifact")

    dep_refs = parse_dependencies([d.model_dump() for d in payload.dependencies])
    validate_dependencies_exist(
        conn,
        org_id=org_id,
        project_id=project_id,
        owner_artifact_key=artifact.artifact_key,
        dependencies=dep_refs,
    )
    assert_no_dependency_cycles(
        conn,
        org_id=org_id,
        project_id=project_id,
        root_artifact_key=artifact.artifact_key,
        dependencies=dep_refs,
        max_depth=settings.max_dependency_depth,
    )

    rev_num = repo.next_revision_number(conn, artifact.id)
    row = repo.insert_revision(
        conn,
        artifact_id=artifact.id,
        org_id=org_id,
        project_id=project_id,
        revision_number=rev_num,
        parent_revision_id=payload.parent_revision_id,
        is_draft=payload.is_draft,
        content_digest=digest_content(payload.content),
        schema_digest=digest_schema(payload.input_schema),
        config_digest=digest_config(payload.config),
        semantic_version=payload.semantic_version,
        metadata=payload.metadata,
        encryption_key_ref=key_ref,
        secret_scan_warnings=warnings,
        ciphertext=ciphertext,
        created_by=actor,
    )
    if dep_refs:
        repo.insert_revision_dependencies(
            conn,
            revision_id=row.id,
            org_id=org_id,
            project_id=project_id,
            dependencies=[
                {
                    "artifact_key": d.artifact_key,
                    "label": d.label,
                    "revision_id": d.revision_id,
                }
                for d in dep_refs
            ],
        )
    repo.insert_audit(
        conn,
        org_id=org_id,
        project_id=project_id,
        action="revision.create",
        resource_type="revision",
        resource_id=row.id,
        actor=actor,
        detail={
            "artifact_key": artifact.artifact_key,
            "revision_number": rev_num,
            "is_draft": payload.is_draft,
        },
    )
    return _revision_detail_from_row(
        row,
        content=payload.content,
        input_schema=payload.input_schema,
        config=payload.config,
        dependencies=payload.dependencies,
    )


def _dependencies_for_revision(
    conn: PgConn, org_id: UUID, revision_id: UUID
) -> list[ArtifactDependencyRef]:
    rows = repo.list_revision_dependencies(conn, org_id, revision_id)
    return [
        ArtifactDependencyRef(
            artifact_key=str(r["dependency_artifact_key"]),
            label=r.get("dependency_label"),
            revision_id=r.get("dependency_revision_id"),
        )
        for r in rows
    ]


def _revision_detail_from_row(
    row: repo.RevisionRow,
    *,
    content: dict[str, Any],
    input_schema: dict[str, Any] | None,
    config: dict[str, Any] | None,
    dependencies: list[Any],
) -> RevisionDetailOut:
    return RevisionDetailOut(
        **_revision_summary(row).model_dump(),
        content=content,
        input_schema=input_schema,
        config=config,
        dependencies=dependencies,
    )


def get_revision_detail(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    artifact_key: str,
    revision_id: UUID,
) -> RevisionDetailOut:
    artifact = repo.get_artifact_by_key(conn, org_id, project_id, artifact_key)
    if artifact is None:
        raise NotFoundError(f"artifact {artifact_key} not found")
    row = repo.get_revision(conn, org_id, project_id, revision_id)
    if row is None or row.artifact_id != artifact.id:
        raise NotFoundError("revision not found")
    body = _load_revision_content(conn, settings, row)
    deps = _dependencies_for_revision(conn, org_id, row.id)
    return _revision_detail_from_row(
        row,
        content=body.get("content", {}),
        input_schema=body.get("input_schema"),
        config=body.get("config"),
        dependencies=deps,
    )


def list_revisions_for_artifact(
    conn: PgConn, org_id: UUID, project_id: UUID, artifact_key: str, limit: int
) -> RevisionListResponse:
    artifact = repo.get_artifact_by_key(conn, org_id, project_id, artifact_key)
    if artifact is None:
        raise NotFoundError(f"artifact {artifact_key} not found")
    rows = repo.list_revisions(conn, org_id, project_id, artifact.id, limit)
    return RevisionListResponse(items=[_revision_summary(r) for r in rows])


def rollback_revision(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    artifact_key: str,
    target_revision_id: UUID,
    is_draft: bool,
    actor: str,
) -> RevisionDetailOut:
    target = get_revision_detail(
        conn,
        settings,
        org_id=org_id,
        project_id=project_id,
        artifact_key=artifact_key,
        revision_id=target_revision_id,
    )
    create_payload = RevisionCreate(
        content=target.content,
        input_schema=target.input_schema,
        config=target.config,
        semantic_version=target.semantic_version,
        metadata={**target.metadata, "rollback_of": str(target_revision_id)},
        is_draft=is_draft,
        parent_revision_id=target_revision_id,
        encryption_key_ref=target.encryption_key_ref,
        dependencies=target.dependencies,
    )
    return create_revision(
        conn,
        settings,
        org_id=org_id,
        project_id=project_id,
        artifact_key=artifact_key,
        payload=create_payload,
        actor=actor,
    )


def diff_revisions(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    artifact_key: str,
    from_revision_id: UUID,
    to_revision_id: UUID,
    mode: str,
) -> DiffResponse:
    left = get_revision_detail(
        conn,
        settings,
        org_id=org_id,
        project_id=project_id,
        artifact_key=artifact_key,
        revision_id=from_revision_id,
    )
    right = get_revision_detail(
        conn,
        settings,
        org_id=org_id,
        project_id=project_id,
        artifact_key=artifact_key,
        revision_id=to_revision_id,
    )
    hunks: list[DiffHunk] = []
    if left.content_digest != right.content_digest:
        hunks.append(DiffHunk(field="content", before=left.content, after=right.content))
    if left.schema_digest != right.schema_digest:
        hunks.append(
            DiffHunk(field="input_schema", before=left.input_schema, after=right.input_schema)
        )
    if left.config_digest != right.config_digest:
        hunks.append(DiffHunk(field="config", before=left.config, after=right.config))

    text_diff: str | None = None
    if mode == "text":
        left_text = json.dumps(left.content, indent=2, sort_keys=True)
        right_text = json.dumps(right.content, indent=2, sort_keys=True)
        text_diff = "".join(
            difflib.unified_diff(
                left_text.splitlines(keepends=True),
                right_text.splitlines(keepends=True),
                fromfile="from",
                tofile="to",
            )
        )
    return DiffResponse(
        from_revision_id=from_revision_id,
        to_revision_id=to_revision_id,
        mode=mode,
        hunks=hunks,
        text_diff=text_diff,
    )


def copy_revision_for_playground(
    conn: PgConn,
    settings: Settings,
    org_id: UUID,
    project_id: UUID,
    revision_id: UUID,
) -> RevisionDetailOut:
    row = repo.get_revision(conn, org_id, project_id, revision_id)
    if row is None:
        raise NotFoundError("revision not found")
    artifact = repo.get_artifact_by_id(conn, org_id, project_id, row.artifact_id)
    if artifact is None:
        raise NotFoundError("artifact not found")
    body = _load_revision_content(conn, settings, row)
    return RevisionDetailOut(
        **_revision_summary(row).model_dump(),
        content=body.get("content", {}),
        input_schema=body.get("input_schema"),
        config=body.get("config"),
    )


def ensure_not_draft_for_production(row: repo.RevisionRow, label_name: str) -> None:
    if label_name == "production" and row.is_draft:
        raise PreconditionFailedError("draft revisions cannot be promoted to production")
