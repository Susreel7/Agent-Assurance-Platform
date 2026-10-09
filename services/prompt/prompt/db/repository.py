"""SQL for prompt schema — only module with raw SQL."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from prompt.db.postgres import PgConn


@dataclass(frozen=True, slots=True)
class ArtifactRow:
    id: UUID
    organization_id: UUID
    project_id: UUID
    artifact_key: str
    kind: str
    display_name: str
    description: str
    tags: list[Any]
    created_at: datetime
    created_by: str
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class RevisionRow:
    id: UUID
    artifact_id: UUID
    organization_id: UUID
    project_id: UUID
    revision_number: int
    parent_revision_id: UUID | None
    is_draft: bool
    content_digest: str
    schema_digest: str | None
    config_digest: str | None
    semantic_version: str | None
    metadata: dict[str, Any]
    encryption_key_ref: str
    secret_scan_warnings: list[Any]
    created_at: datetime
    created_by: str


@dataclass(frozen=True, slots=True)
class LabelRow:
    id: UUID
    artifact_id: UUID
    organization_id: UUID
    project_id: UUID
    label_name: str
    revision_id: UUID
    version: int
    updated_at: datetime
    updated_by: str


def _artifact_from_row(row: dict[str, Any]) -> ArtifactRow:
    tags = row["tags"]
    if isinstance(tags, str):
        tags = json.loads(tags)
    return ArtifactRow(
        id=row["id"],
        organization_id=row["organization_id"],
        project_id=row["project_id"],
        artifact_key=row["artifact_key"],
        kind=row["kind"],
        display_name=row["display_name"],
        description=row["description"],
        tags=list(tags or []),
        created_at=row["created_at"],
        created_by=row["created_by"],
        updated_at=row["updated_at"],
    )


def _revision_from_row(row: dict[str, Any]) -> RevisionRow:
    meta = row["metadata"]
    if isinstance(meta, str):
        meta = json.loads(meta)
    warnings = row["secret_scan_warnings"]
    if isinstance(warnings, str):
        warnings = json.loads(warnings)
    return RevisionRow(
        id=row["id"],
        artifact_id=row["artifact_id"],
        organization_id=row["organization_id"],
        project_id=row["project_id"],
        revision_number=row["revision_number"],
        parent_revision_id=row["parent_revision_id"],
        is_draft=row["is_draft"],
        content_digest=row["content_digest"],
        schema_digest=row["schema_digest"],
        config_digest=row["config_digest"],
        semantic_version=row["semantic_version"],
        metadata=dict(meta or {}),
        encryption_key_ref=row["encryption_key_ref"],
        secret_scan_warnings=list(warnings or []),
        created_at=row["created_at"],
        created_by=row["created_by"],
    )


def insert_artifact(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    artifact_key: str,
    kind: str,
    display_name: str,
    description: str,
    tags: list[str],
    created_by: str,
) -> ArtifactRow:
    artifact_id = uuid.uuid4()
    now = datetime.now(tz=UTC)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO prompt.artifacts (
                id, organization_id, project_id, artifact_key, kind,
                display_name, description, tags, created_by, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            RETURNING *
            """,
            (
                artifact_id,
                org_id,
                project_id,
                artifact_key,
                kind,
                display_name,
                description,
                json.dumps(tags),
                created_by,
                now,
            ),
        )
        row = cur.fetchone()
    assert row is not None
    return _artifact_from_row(row)


def get_artifact_by_key(
    conn: PgConn, org_id: UUID, project_id: UUID, artifact_key: str
) -> ArtifactRow | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM prompt.artifacts
            WHERE organization_id = %s AND project_id = %s AND artifact_key = %s
            """,
            (org_id, project_id, artifact_key),
        )
        row = cur.fetchone()
    return _artifact_from_row(row) if row else None


def get_artifact_by_id(
    conn: PgConn, org_id: UUID, project_id: UUID, artifact_id: UUID
) -> ArtifactRow | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM prompt.artifacts
            WHERE organization_id = %s AND project_id = %s AND id = %s
            """,
            (org_id, project_id, artifact_id),
        )
        row = cur.fetchone()
    return _artifact_from_row(row) if row else None


def list_artifacts(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    kind: str | None,
    query: str | None,
    label: str | None,
    cursor_key: str | None,
    limit: int,
) -> tuple[list[ArtifactRow], str | None]:
    clauses = ["organization_id = %s", "project_id = %s"]
    params: list[Any] = [org_id, project_id]
    if kind:
        clauses.append("kind = %s")
        params.append(kind)
    if query:
        clauses.append("(artifact_key ILIKE %s OR display_name ILIKE %s)")
        pattern = f"%{query}%"
        params.extend([pattern, pattern])
    if label:
        clauses.append(
            """
            EXISTS (
                SELECT 1 FROM prompt.labels l
                WHERE l.artifact_id = prompt.artifacts.id
                  AND l.organization_id = prompt.artifacts.organization_id
                  AND l.project_id = prompt.artifacts.project_id
                  AND l.label_name = %s
            )
            """
        )
        params.append(label)
    if cursor_key:
        clauses.append("artifact_key > %s")
        params.append(cursor_key)
    where = " AND ".join(clauses)
    params.append(limit + 1)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT * FROM prompt.artifacts
            WHERE {where}
            ORDER BY artifact_key ASC
            LIMIT %s
            """,
            tuple(params),
        )
        rows = cur.fetchall()
    items = [_artifact_from_row(r) for r in rows[:limit]]
    next_cursor = rows[limit]["artifact_key"] if len(rows) > limit else None
    return items, next_cursor


def next_revision_number(conn: PgConn, artifact_id: UUID) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(MAX(revision_number), 0) + 1 AS n
            FROM prompt.revisions WHERE artifact_id = %s
            """,
            (artifact_id,),
        )
        row = cur.fetchone()
    assert row is not None
    return int(row["n"])


def insert_revision(
    conn: PgConn,
    *,
    artifact_id: UUID,
    org_id: UUID,
    project_id: UUID,
    revision_number: int,
    parent_revision_id: UUID | None,
    is_draft: bool,
    content_digest: str,
    schema_digest: str | None,
    config_digest: str | None,
    semantic_version: str | None,
    metadata: dict[str, Any],
    encryption_key_ref: str,
    secret_scan_warnings: list[dict[str, str]],
    ciphertext: bytes,
    created_by: str,
) -> RevisionRow:
    revision_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO prompt.revisions (
                id, artifact_id, organization_id, project_id, revision_number,
                parent_revision_id, is_draft, content_digest, schema_digest, config_digest,
                semantic_version, metadata, encryption_key_ref, secret_scan_warnings, created_by
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s::jsonb, %s
            )
            RETURNING *
            """,
            (
                revision_id,
                artifact_id,
                org_id,
                project_id,
                revision_number,
                parent_revision_id,
                is_draft,
                content_digest,
                schema_digest,
                config_digest,
                semantic_version,
                json.dumps(metadata),
                encryption_key_ref,
                json.dumps(secret_scan_warnings),
                created_by,
            ),
        )
        rev_row = cur.fetchone()
        assert rev_row is not None
        cur.execute(
            """
            INSERT INTO prompt.revision_bodies (revision_id, organization_id, ciphertext)
            VALUES (%s, %s, %s)
            """,
            (revision_id, org_id, ciphertext),
        )
        cur.execute(
            "UPDATE prompt.artifacts SET updated_at = now() WHERE id = %s",
            (artifact_id,),
        )
    return _revision_from_row(rev_row)


def get_revision(
    conn: PgConn, org_id: UUID, project_id: UUID, revision_id: UUID
) -> RevisionRow | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM prompt.revisions
            WHERE organization_id = %s AND project_id = %s AND id = %s
            """,
            (org_id, project_id, revision_id),
        )
        row = cur.fetchone()
    return _revision_from_row(row) if row else None


def get_revision_ciphertext(conn: PgConn, org_id: UUID, revision_id: UUID) -> bytes | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ciphertext FROM prompt.revision_bodies
            WHERE organization_id = %s AND revision_id = %s
            """,
            (org_id, revision_id),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return bytes(row["ciphertext"])


def list_revisions(
    conn: PgConn, org_id: UUID, project_id: UUID, artifact_id: UUID, limit: int
) -> list[RevisionRow]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM prompt.revisions
            WHERE organization_id = %s AND project_id = %s AND artifact_id = %s
            ORDER BY revision_number DESC
            LIMIT %s
            """,
            (org_id, project_id, artifact_id, limit),
        )
        rows = cur.fetchall()
    return [_revision_from_row(r) for r in rows]


def get_label(
    conn: PgConn, org_id: UUID, project_id: UUID, artifact_id: UUID, label_name: str
) -> LabelRow | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM prompt.labels
            WHERE organization_id = %s AND project_id = %s
              AND artifact_id = %s AND label_name = %s
            """,
            (org_id, project_id, artifact_id, label_name),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return LabelRow(
        id=row["id"],
        artifact_id=row["artifact_id"],
        organization_id=row["organization_id"],
        project_id=row["project_id"],
        label_name=row["label_name"],
        revision_id=row["revision_id"],
        version=row["version"],
        updated_at=row["updated_at"],
        updated_by=row["updated_by"],
    )


def upsert_label_cas(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    artifact_id: UUID,
    label_name: str,
    to_revision_id: UUID,
    expected_version: int | None,
    actor: str,
    action: str,
    from_revision_id: UUID | None,
    detail: dict[str, Any],
) -> LabelRow:
    existing = get_label(conn, org_id, project_id, artifact_id, label_name)
    if existing is None:
        if expected_version is not None and expected_version != 0:
            raise ValueError("label_version_conflict")
        label_id = uuid.uuid4()
        version = 1
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO prompt.labels (
                    id, artifact_id, organization_id, project_id, label_name,
                    revision_id, version, updated_by
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                """,
                (
                    label_id,
                    artifact_id,
                    org_id,
                    project_id,
                    label_name,
                    to_revision_id,
                    version,
                    actor,
                ),
            )
            row = cur.fetchone()
        assert row is not None
    else:
        if expected_version is not None and existing.version != expected_version:
            raise ValueError("label_version_conflict")
        version = existing.version + 1
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE prompt.labels
                SET revision_id = %s, version = %s, updated_at = now(), updated_by = %s
                WHERE id = %s AND organization_id = %s AND project_id = %s AND version = %s
                RETURNING *
                """,
                (
                    to_revision_id,
                    version,
                    actor,
                    existing.id,
                    org_id,
                    project_id,
                    existing.version,
                ),
            )
            row = cur.fetchone()
        if row is None:
            raise ValueError("label_version_conflict")

    insert_label_history(
        conn,
        artifact_id=artifact_id,
        org_id=org_id,
        project_id=project_id,
        label_name=label_name,
        from_revision_id=from_revision_id,
        to_revision_id=to_revision_id,
        label_version=version,
        action=action,
        actor=actor,
        detail=detail,
    )
    assert row is not None
    return LabelRow(
        id=row["id"],
        artifact_id=row["artifact_id"],
        organization_id=row["organization_id"],
        project_id=row["project_id"],
        label_name=row["label_name"],
        revision_id=row["revision_id"],
        version=row["version"],
        updated_at=row["updated_at"],
        updated_by=row["updated_by"],
    )


def insert_label_history(
    conn: PgConn,
    *,
    artifact_id: UUID,
    org_id: UUID,
    project_id: UUID,
    label_name: str,
    from_revision_id: UUID | None,
    to_revision_id: UUID,
    label_version: int,
    action: str,
    actor: str,
    detail: dict[str, Any],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO prompt.label_history (
                id, artifact_id, organization_id, project_id, label_name,
                from_revision_id, to_revision_id, label_version, action, actor, detail
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                uuid.uuid4(),
                artifact_id,
                org_id,
                project_id,
                label_name,
                from_revision_id,
                to_revision_id,
                label_version,
                action,
                actor,
                json.dumps(detail),
            ),
        )


def list_label_history(
    conn: PgConn,
    org_id: UUID,
    project_id: UUID,
    artifact_id: UUID,
    limit: int,
    label_name: str | None = None,
) -> list[dict[str, Any]]:
    clauses = [
        "organization_id = %s",
        "project_id = %s",
        "artifact_id = %s",
    ]
    params: list[Any] = [org_id, project_id, artifact_id]
    if label_name:
        clauses.append("label_name = %s")
        params.append(label_name.strip().lower())
    params.append(limit)
    where = " AND ".join(clauses)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT * FROM prompt.label_history
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            tuple(params),
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def insert_revision_dependencies(
    conn: PgConn,
    *,
    revision_id: UUID,
    org_id: UUID,
    project_id: UUID,
    dependencies: list[dict[str, Any]],
) -> None:
    with conn.cursor() as cur:
        for dep in dependencies:
            cur.execute(
                """
                INSERT INTO prompt.revision_dependencies (
                    revision_id, organization_id, project_id,
                    dependency_artifact_key, dependency_label, dependency_revision_id
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    revision_id,
                    org_id,
                    project_id,
                    dep["artifact_key"],
                    dep.get("label"),
                    dep.get("revision_id"),
                ),
            )


def list_revision_dependencies(
    conn: PgConn, org_id: UUID, revision_id: UUID
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT dependency_artifact_key, dependency_label, dependency_revision_id
            FROM prompt.revision_dependencies
            WHERE organization_id = %s AND revision_id = %s
            ORDER BY dependency_artifact_key ASC
            """,
            (org_id, revision_id),
        )
        rows = cur.fetchall()
    return [dict(r) for r in rows]


def insert_audit(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    action: str,
    resource_type: str,
    resource_id: UUID,
    actor: str,
    detail: dict[str, Any],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO prompt.audit_events (
                id, organization_id, project_id, action, resource_type, resource_id, actor, detail
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                uuid.uuid4(),
                org_id,
                project_id,
                action,
                resource_type,
                resource_id,
                actor,
                json.dumps(detail),
            ),
        )


def list_audit(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    resource_type: str | None,
    action: str | None,
    actor: str | None,
    since: datetime | None,
    until: datetime | None,
    cursor_time: datetime | None,
    limit: int,
) -> tuple[list[dict[str, Any]], datetime | None]:
    clauses = ["organization_id = %s", "project_id = %s"]
    params: list[Any] = [org_id, project_id]
    if resource_type:
        clauses.append("resource_type = %s")
        params.append(resource_type)
    if action:
        clauses.append("action = %s")
        params.append(action)
    if actor:
        clauses.append("actor = %s")
        params.append(actor)
    if since:
        clauses.append("created_at >= %s")
        params.append(since)
    if until:
        clauses.append("created_at <= %s")
        params.append(until)
    if cursor_time:
        clauses.append("created_at < %s")
        params.append(cursor_time)
    params.append(limit + 1)
    where = " AND ".join(clauses)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT * FROM prompt.audit_events
            WHERE {where}
            ORDER BY created_at DESC
            LIMIT %s
            """,
            tuple(params),
        )
        rows = cur.fetchall()
    items = [dict(r) for r in rows[:limit]]
    next_cursor = rows[limit]["created_at"] if len(rows) > limit else None
    return items, next_cursor


def insert_playground_run(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    mode: str,
    status: str,
    resolved_revision_ids: list[UUID],
    model_alias: str | None,
    variables: dict[str, Any],
    created_by: str,
) -> UUID:
    run_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO prompt.playground_runs (
                id, organization_id, project_id, mode, status,
                resolved_revision_ids, model_alias, variables, created_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            """,
            (
                run_id,
                org_id,
                project_id,
                mode,
                status,
                resolved_revision_ids,
                model_alias,
                json.dumps(variables),
                created_by,
            ),
        )
    return run_id


def finalize_playground_run(
    conn: PgConn,
    *,
    org_id: UUID,
    run_id: UUID,
    status: str,
    router_request_id: str | None,
    router_trace: dict[str, Any],
    input_digest: str | None,
    output_digest: str | None,
    error_message: str | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE prompt.playground_runs
            SET status = %s,
                router_request_id = %s,
                router_trace = %s::jsonb,
                input_digest = %s,
                output_digest = %s,
                error_message = %s,
                completed_at = now()
            WHERE id = %s AND organization_id = %s
            """,
            (
                status,
                router_request_id,
                json.dumps(router_trace),
                input_digest,
                output_digest,
                error_message,
                run_id,
                org_id,
            ),
        )


def update_playground_run_status(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    run_id: UUID,
    status: str,
    error_message: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE prompt.playground_runs
            SET status = %s,
                error_message = COALESCE(%s, error_message),
                completed_at = CASE
                    WHEN %s IN ('completed', 'failed', 'cancelled') THEN now()
                    ELSE completed_at
                END
            WHERE organization_id = %s AND project_id = %s AND id = %s
            """,
            (status, error_message, status, org_id, project_id, run_id),
        )


def get_playground_run(
    conn: PgConn, org_id: UUID, project_id: UUID, run_id: UUID
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM prompt.playground_runs
            WHERE organization_id = %s AND project_id = %s AND id = %s
            """,
            (org_id, project_id, run_id),
        )
        row = cur.fetchone()
    return dict(row) if row else None
