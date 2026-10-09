"""Pydantic models for artifact/revision APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from prompt.config import ARTIFACT_KINDS

ArtifactKind = Literal["prompt", "rule", "skill", "context"]


class ArtifactCreate(BaseModel):
    artifact_key: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    kind: ArtifactKind
    display_name: str = Field(default="", max_length=256)
    description: str = Field(default="", max_length=2048)
    tags: list[str] = Field(default_factory=list, max_length=32)


class ArtifactDependencyRef(BaseModel):
    artifact_key: str = Field(min_length=1, max_length=128)
    label: str | None = Field(default=None, max_length=64)
    revision_id: UUID | None = None


class RevisionCreate(BaseModel):
    content: dict[str, Any]
    input_schema: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    semantic_version: str | None = Field(default=None, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_draft: bool = False
    parent_revision_id: UUID | None = None
    encryption_key_ref: str | None = None
    dependencies: list[ArtifactDependencyRef] = Field(default_factory=list)

    @field_validator("content")
    @classmethod
    def _content_object(cls, v: dict[str, Any]) -> dict[str, Any]:
        if not v:
            raise ValueError("content must not be empty")
        return v


class ArtifactOut(BaseModel):
    id: UUID
    organization_id: UUID
    project_id: UUID
    artifact_key: str
    kind: ArtifactKind
    display_name: str
    description: str
    tags: list[str]
    created_at: datetime
    created_by: str
    updated_at: datetime


class RevisionSummaryOut(BaseModel):
    id: UUID
    artifact_id: UUID
    revision_number: int
    parent_revision_id: UUID | None
    is_draft: bool
    content_digest: str
    schema_digest: str | None
    config_digest: str | None
    semantic_version: str | None
    metadata: dict[str, Any]
    encryption_key_ref: str
    secret_scan_warnings: list[dict[str, str]]
    created_at: datetime
    created_by: str


class RevisionDetailOut(RevisionSummaryOut):
    content: dict[str, Any]
    input_schema: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    dependencies: list[ArtifactDependencyRef] = Field(default_factory=list)


class ArtifactListResponse(BaseModel):
    items: list[ArtifactOut]
    next_cursor: str | None = None


class RevisionListResponse(BaseModel):
    items: list[RevisionSummaryOut]


class DiffRequest(BaseModel):
    from_revision_id: UUID
    to_revision_id: UUID
    mode: Literal["structured", "text"] = "structured"


class DiffHunk(BaseModel):
    field: str
    before: Any | None = None
    after: Any | None = None


class DiffResponse(BaseModel):
    from_revision_id: UUID
    to_revision_id: UUID
    mode: str
    hunks: list[DiffHunk]
    text_diff: str | None = None


class RollbackRequest(BaseModel):
    target_revision_id: UUID
    is_draft: bool = False


class CompareRevisionsRequest(BaseModel):
    revision_ids: list[UUID] = Field(min_length=2, max_length=8)


def parse_kind(value: str) -> ArtifactKind:
    if value not in ARTIFACT_KINDS:
        msg = f"invalid kind: {value}"
        raise ValueError(msg)
    return value  # type: ignore[return-value]
