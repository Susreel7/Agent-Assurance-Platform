"""Annotation queue models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AnnotationQueueCreate(BaseModel):
    queue_key: str = Field(min_length=1, max_length=128)
    display_name: str = ""
    item_filter: dict[str, Any] = Field(default_factory=dict)
    rubric: dict[str, Any] = Field(default_factory=dict)
    reviewers_required: int = Field(default=1, ge=1, le=10)


class AnnotationItemCreate(BaseModel):
    item_type: str = Field(pattern="^(trace|span|session|pairwise)$")
    reference_id: str
    pairwise_reference_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClaimRequest(BaseModel):
    assignee: str
    expected_version: int = 0
    lease_seconds: int = Field(default=300, ge=30, le=3600)


class SubmissionRequest(BaseModel):
    assignee: str
    action: str = Field(pattern="^(submit|skip)$")
    scores: dict[str, Any] = Field(default_factory=dict)
    comments: str = ""
    rubric_version: int = 1


class ExportToDatasetRequest(BaseModel):
    dataset_key: str
    actor: str | None = None


class AnnotationQueueOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    project_id: UUID
    queue_key: str
    display_name: str
    item_filter: dict[str, Any] = Field(default_factory=dict)
    rubric: dict[str, Any] = Field(default_factory=dict)
    reviewers_required: int
    created_at: datetime
    created_by: str


class AnnotationItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    queue_id: UUID
    organization_id: UUID
    project_id: UUID
    item_type: str
    reference_id: str
    pairwise_reference_id: str | None = None
    status: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime | None = None
