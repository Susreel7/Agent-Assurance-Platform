"""Score API models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ScoreCreate(BaseModel):
    target_type: str = Field(pattern="^(run|span|trace|session|experiment_result)$")
    target_id: str
    name: str
    value_type: str = Field(pattern="^(numeric|boolean|categorical)$")
    value_numeric: float | None = None
    value_boolean: bool | None = None
    value_categorical: str | None = None
    source: str = Field(pattern="^(human|automated)$")
    evaluator_revision_id: UUID | None = None
    explanation: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScoreCorrection(BaseModel):
    reason: str = Field(min_length=1, max_length=512)
    corrected: ScoreCreate


class ScoreOut(BaseModel):
    id: UUID
    target_type: str
    target_id: str
    name: str
    value_type: str
    source: str
    created_at: datetime
    created_by: str


class ScoreDetailOut(BaseModel):
    id: UUID
    target_type: str
    target_id: str
    name: str
    value_type: str
    value_numeric: float | None = None
    value_boolean: bool | None = None
    value_categorical: str | None = None
    source: str
    evaluator_revision_id: UUID | None = None
    explanation: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    supersedes_score_id: UUID | None = None
    created_at: datetime
    created_by: str
