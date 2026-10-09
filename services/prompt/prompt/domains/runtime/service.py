"""Machine runtime artifact resolution."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from prompt.auth.schemas import WorkloadPrincipal
from prompt.config import Settings
from prompt.db import repository as repo
from prompt.db.postgres import PgConn
from prompt.domains.artifacts import service as artifact_service
from prompt.domains.runtime.schemas import RuntimeArtifactResponse
from prompt.errors import AuthorizationError, NotFoundError, PreconditionFailedError


def _assert_runtime_scope(principal: WorkloadPrincipal, org_id: UUID, project_id: UUID) -> None:
    if principal.organization_id != org_id or principal.project_id != project_id:
        raise AuthorizationError("workload org/project mismatch")


def resolve_runtime_artifact_core(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    artifact_key: str,
    label: str | None,
    revision_id: UUID | None,
    pin_revision_id: UUID | None = None,
) -> RuntimeArtifactResponse:
    """Resolve artifact content with the same rules as workload runtime fetch."""
    artifact = repo.get_artifact_by_key(conn, org_id, project_id, artifact_key)
    if artifact is None:
        raise NotFoundError(f"artifact {artifact_key} not found")

    resolved_label = label.strip().lower() if label else None
    pinned_id = pin_revision_id or revision_id
    rev_row: repo.RevisionRow | None
    pinned = False
    if pinned_id is not None:
        rev_row = repo.get_revision(conn, org_id, project_id, pinned_id)
        if rev_row is None or rev_row.artifact_id != artifact.id:
            raise NotFoundError("revision not found")
        pinned = True
    elif resolved_label:
        label_row = repo.get_label(conn, org_id, project_id, artifact.id, resolved_label)
        if label_row is None:
            raise NotFoundError(f"label {resolved_label} not set")
        rev_row = repo.get_revision(conn, org_id, project_id, label_row.revision_id)
    else:
        raise NotFoundError("label, revision_id, or pin_revision_id required")

    assert rev_row is not None
    if resolved_label == "production" and rev_row.is_draft:
        raise PreconditionFailedError("production label resolves to a draft revision")

    detail = artifact_service.copy_revision_for_playground(
        conn, settings, org_id, project_id, rev_row.id
    )
    return RuntimeArtifactResponse(
        artifact_key=artifact.artifact_key,
        kind=artifact.kind,
        revision_id=rev_row.id,
        revision_number=rev_row.revision_number,
        label=resolved_label,
        pinned_revision=pinned,
        content_digest=rev_row.content_digest,
        schema_digest=rev_row.schema_digest,
        config_digest=rev_row.config_digest,
        content=detail.content,
        input_schema=detail.input_schema,
        config=detail.config,
        resolved_at=datetime.now(tz=UTC),
    )


def resolve_runtime_artifact(
    conn: PgConn,
    settings: Settings,
    *,
    principal: WorkloadPrincipal,
    org_id: UUID,
    project_id: UUID,
    artifact_key: str,
    label: str | None,
    revision_id: UUID | None,
    pin_revision_id: UUID | None = None,
) -> RuntimeArtifactResponse:
    _assert_runtime_scope(principal, org_id, project_id)
    return resolve_runtime_artifact_core(
        conn,
        settings,
        org_id=org_id,
        project_id=project_id,
        artifact_key=artifact_key,
        label=label,
        revision_id=revision_id,
        pin_revision_id=pin_revision_id,
    )


def runtime_etag(digest: str) -> str:
    return f'"{digest}"'


def apply_evaluate_digest_headers(response: Any, resolved: RuntimeArtifactResponse) -> None:
    response.headers["X-Revision-Id"] = str(resolved.revision_id)
    response.headers["X-Revision-Number"] = str(resolved.revision_number)
    response.headers["X-Content-Digest"] = resolved.content_digest
    if resolved.schema_digest:
        response.headers["X-Schema-Digest"] = resolved.schema_digest
    if resolved.config_digest:
        response.headers["X-Config-Digest"] = resolved.config_digest
    if resolved.pinned_revision:
        response.headers["X-Pinned-Revision"] = "true"


def runtime_cache_control(settings: Settings) -> str:
    max_age = settings.runtime_cache_max_age_seconds
    stale = settings.runtime_cache_stale_if_error_seconds
    if max_age <= 0:
        return "no-store"
    return f"max-age={max_age}, stale-if-error={stale}"
