"""Artifact dependency validation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from prompt.db import repository as repo
from prompt.db.postgres import PgConn
from prompt.errors import NotFoundError, ValidationError


@dataclass(frozen=True, slots=True)
class DependencyRef:
    artifact_key: str
    label: str | None = None
    revision_id: UUID | None = None


def parse_dependencies(raw: list[Any] | None) -> list[DependencyRef]:
    if not raw:
        return []
    out: list[DependencyRef] = []
    for item in raw:
        if not isinstance(item, dict):
            raise ValidationError("dependency entry must be an object")
        key = item.get("artifact_key")
        if not isinstance(key, str) or not key.strip():
            raise ValidationError("dependency.artifact_key is required")
        label = item.get("label")
        rev = item.get("revision_id")
        revision_id = UUID(str(rev)) if rev is not None else None
        out.append(
            DependencyRef(
                artifact_key=key.strip(),
                label=str(label).strip().lower() if label else None,
                revision_id=revision_id,
            )
        )
    return out


def validate_dependencies_exist(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    owner_artifact_key: str,
    dependencies: list[DependencyRef],
) -> None:
    for dep in dependencies:
        if dep.artifact_key == owner_artifact_key:
            raise ValidationError("artifact cannot depend on itself")
        row = repo.get_artifact_by_key(conn, org_id, project_id, dep.artifact_key)
        if row is None:
            raise NotFoundError(f"dependency artifact {dep.artifact_key} not found")
        if dep.revision_id is not None:
            rev = repo.get_revision(conn, org_id, project_id, dep.revision_id)
            if rev is None or rev.artifact_id != row.id:
                raise ValidationError(
                    f"dependency revision invalid for artifact {dep.artifact_key}"
                )
        elif dep.label:
            label_row = repo.get_label(conn, org_id, project_id, row.id, dep.label)
            if label_row is None:
                raise ValidationError(f"dependency label {dep.label} not set on {dep.artifact_key}")


def assert_no_dependency_cycles(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    root_artifact_key: str,
    dependencies: list[DependencyRef],
    max_depth: int,
) -> None:
    def deps_for_key(artifact_key: str) -> list[str]:
        artifact = repo.get_artifact_by_key(conn, org_id, project_id, artifact_key)
        if artifact is None:
            return []
        revs = repo.list_revisions(conn, org_id, project_id, artifact.id, limit=1)
        if not revs:
            return []
        stored = repo.list_revision_dependencies(conn, org_id, revs[0].id)
        return [str(d["dependency_artifact_key"]) for d in stored]

    def children(key: str) -> list[str]:
        if key == root_artifact_key:
            return [d.artifact_key for d in dependencies]
        return deps_for_key(key)

    visiting: set[str] = set()

    def visit(key: str, depth: int) -> None:
        if depth > max_depth:
            raise ValidationError(f"dependency depth exceeds max_depth={max_depth}")
        if key in visiting:
            raise ValidationError(f"dependency cycle detected at {key}")
        visiting.add(key)
        for nxt in children(key):
            visit(nxt, depth + 1)
        visiting.remove(key)

    visit(root_artifact_key, 0)


def assert_production_dependencies_resolvable(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    dependencies: list[DependencyRef],
) -> None:
    for dep in dependencies:
        artifact = repo.get_artifact_by_key(conn, org_id, project_id, dep.artifact_key)
        if artifact is None:
            raise NotFoundError(f"dependency artifact {dep.artifact_key} not found")
        if dep.revision_id is not None:
            rev = repo.get_revision(conn, org_id, project_id, dep.revision_id)
            if rev is None or rev.is_draft:
                raise ValidationError(f"dependency {dep.artifact_key} revision is draft or missing")
            continue
        label_name = dep.label or "production"
        label_row = repo.get_label(conn, org_id, project_id, artifact.id, label_name)
        if label_row is None:
            raise ValidationError(
                f"dependency {dep.artifact_key} label {label_name} not set for production promote"
            )
        rev = repo.get_revision(conn, org_id, project_id, label_row.revision_id)
        if rev is None or rev.is_draft:
            raise ValidationError(
                f"dependency {dep.artifact_key} via {label_name} resolves to draft or missing"
            )
