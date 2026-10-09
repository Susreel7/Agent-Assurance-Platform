"""Typed control-plane boundary for the prompt workspace service."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ArtifactCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_key: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    kind: Literal["prompt", "rule", "skill", "context"]
    display_name: str = Field(default="", max_length=256)
    description: str = Field(default="", max_length=2048)
    tags: list[str] = Field(default_factory=list, max_length=32)


class ArtifactDependencyRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_key: str = Field(min_length=1, max_length=128)
    label: str | None = Field(default=None, max_length=64)
    revision_id: UUID | None = None


class RevisionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: dict[str, Any]
    input_schema: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    semantic_version: str | None = Field(default=None, max_length=64)
    metadata: dict[str, Any] = Field(default_factory=dict)
    is_draft: bool = False
    parent_revision_id: UUID | None = None
    encryption_key_ref: str | None = None
    dependencies: list[ArtifactDependencyRef] = Field(default_factory=list)


class ArtifactOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    organization_id: UUID
    project_id: UUID
    artifact_key: str
    kind: str
    display_name: str
    description: str
    tags: list[str]
    created_at: datetime
    created_by: str
    updated_at: datetime


class RevisionSummaryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    model_config = ConfigDict(extra="forbid")

    items: list[ArtifactOut]
    next_cursor: str | None = None


class RevisionListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[RevisionSummaryOut]


class DiffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_revision_id: UUID
    to_revision_id: UUID
    mode: Literal["structured", "text"] = "structured"


class DiffHunk(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    before: Any | None = None
    after: Any | None = None


class DiffResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_revision_id: UUID
    to_revision_id: UUID
    mode: str
    hunks: list[DiffHunk]
    text_diff: str | None = None


class RollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_revision_id: UUID
    is_draft: bool = False


class CompareRevisionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    revision_ids: list[UUID] = Field(min_length=2, max_length=8)


class CompareRevisionsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_revision_id: UUID
    comparisons: list[DiffResponse]


class LabelOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_id: UUID
    label_name: str
    revision_id: UUID
    version: int
    updated_at: datetime
    updated_by: str


class PromoteLabelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label_name: str = Field(min_length=1, max_length=64)
    revision_id: UUID
    expected_version: int | None = None


class CompareLabelsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    left_label: str
    right_label: str


class LabelHistoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    label_name: str
    from_revision_id: UUID | None
    to_revision_id: UUID
    label_version: int
    action: str
    actor: str
    created_at: datetime
    detail: dict[str, object]


class LabelHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[LabelHistoryEntry]


class ArtifactRef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_key: str | None = None
    revision_id: UUID | None = None
    label: str | None = None


class PlaygroundRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["sync", "stream", "compare", "replay"] = "sync"
    artifacts: list[ArtifactRef] = Field(min_length=1)
    variables: dict[str, Any] = Field(default_factory=dict)
    model_alias: str = Field(min_length=1)
    model_settings: dict[str, Any] = Field(default_factory=dict)
    messages_override: list[dict[str, Any]] | None = None
    replay_run_id: UUID | None = None
    stream: bool = False


class PlaygroundRunResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    status: str
    resolved_revision_ids: list[UUID]
    model_alias: str
    router_trace: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    error_message: str | None = None


class PlaygroundRunStatusOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    status: str
    mode: str
    resolved_revision_ids: list[UUID]
    model_alias: str | None = None
    router_request_id: str | None = None
    router_trace: dict[str, Any] = Field(default_factory=dict)
    input_digest: str | None = None
    output_digest: str | None = None
    error_message: str | None = None


class PlaygroundCancelResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: UUID
    status: str
    cancelled: bool


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID
    action: str
    resource_type: str
    resource_id: UUID
    actor: str
    detail: dict[str, Any]
    created_at: datetime


class AuditListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AuditEntryOut]
    next_cursor: datetime | None = None


class RuntimeArtifactResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    artifact_key: str
    kind: str
    revision_id: UUID
    revision_number: int
    label: str | None = None
    pinned_revision: bool = False
    content_digest: str
    schema_digest: str | None = None
    config_digest: str | None = None
    content: dict[str, Any]
    input_schema: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    resolved_at: datetime
