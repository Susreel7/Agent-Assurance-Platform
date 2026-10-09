"""Label promotion and history models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class LabelOut(BaseModel):
    artifact_id: UUID
    label_name: str
    revision_id: UUID
    version: int
    updated_at: datetime
    updated_by: str


class PromoteLabelRequest(BaseModel):
    label_name: str = Field(min_length=1, max_length=64)
    revision_id: UUID
    expected_version: int | None = Field(
        default=None,
        description="Optimistic concurrency token; omit on first create, required on updates",
    )


class CompareLabelsRequest(BaseModel):
    left_label: str
    right_label: str


class LabelHistoryEntry(BaseModel):
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
    items: list[LabelHistoryEntry]
