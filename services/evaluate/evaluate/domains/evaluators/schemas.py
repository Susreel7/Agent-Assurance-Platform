"""Evaluator boundary models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class EvaluatorCreate(BaseModel):
    evaluator_key: str = Field(min_length=1, max_length=128)
    display_name: str = ""
    kind: str
    config: dict[str, Any] = Field(default_factory=dict)


class EvaluatorOut(BaseModel):
    id: UUID
    evaluator_key: str
    display_name: str
    kind: str
    created_at: datetime | None = None
    created_by: str | None = None


class EvaluatorRevisionSummaryOut(BaseModel):
    id: UUID
    evaluator_id: UUID
    evaluator_key: str
    kind: str
    revision_number: int
    config_digest: str
    created_at: datetime
    created_by: str


class EvaluatorRevisionOut(BaseModel):
    id: UUID
    evaluator_id: UUID
    revision_number: int
    config_digest: str
    created_at: datetime
    created_by: str


class EvaluatorDryRunRequest(BaseModel):
    revision_id: UUID | None = None
    config: dict[str, Any] | None = None
    kind: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
