"""Dataset boundary models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class DatasetCreate(BaseModel):
    dataset_key: str = Field(min_length=1, max_length=128)
    display_name: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class DatasetOut(BaseModel):
    id: UUID
    dataset_key: str
    display_name: str
    description: str
    tags: list[Any]
    created_at: datetime
    created_by: str


class DatasetListResponse(BaseModel):
    items: list[DatasetOut]
    next_cursor: str | None = None


class ExampleCreate(BaseModel):
    example_key: str = Field(min_length=1, max_length=128)
    split_name: str = "default"
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    input: dict[str, Any]
    reference_output: dict[str, Any] | None = None
    source_trace_id: str | None = None


class DatasetRevisionCreate(BaseModel):
    examples: list[ExampleCreate] = Field(default_factory=list)
    copy_from_revision_id: UUID | None = None


class DatasetRevisionOut(BaseModel):
    id: UUID
    dataset_id: UUID
    revision_number: int
    manifest_digest: str
    example_count: int
    created_at: datetime
    created_by: str


class ExampleOut(BaseModel):
    id: UUID
    example_key: str
    split_name: str
    tags: list[Any]
    metadata: dict[str, Any]
    content_digest: str
    source_trace_id: str | None
    has_encrypted_payload: bool


class ExampleSummaryOut(BaseModel):
    id: UUID
    example_key: str
    ordinal: int
    split_name: str
    tags: list[Any]
    metadata: dict[str, Any]
    content_digest: str
    source_trace_id: str | None
    has_encrypted_payload: bool
    has_input_object: bool
    has_reference_object: bool
    created_at: datetime


class ImportRequest(BaseModel):
    format: str = Field(pattern="^(jsonl|csv)$")
    content: str


class ExportResponse(BaseModel):
    format: str
    content: str


class AttachmentUploadIn(BaseModel):
    purpose: str = Field(min_length=1, max_length=64)
    mime_type: str = "application/octet-stream"
    content_base64: str


class AttachmentUploadOut(BaseModel):
    object_ref_id: UUID
    storage_ref: str
    content_digest: str
    download: dict[str, Any]


class AttachmentDownloadOut(BaseModel):
    object_ref_id: UUID
    mime_type: str
    size_bytes: int
    content_digest: str
    content_base64: str
