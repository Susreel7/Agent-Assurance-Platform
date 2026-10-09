"""Release gate models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ReleaseGateCreate(BaseModel):
    gate_key: str = Field(min_length=1, max_length=128)
    baseline_experiment_id: UUID | None = None
    thresholds: dict[str, Any] = Field(default_factory=dict)


class ReleaseGateEvaluateRequest(BaseModel):
    candidate_experiment_id: UUID


class ReleaseGateOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    project_id: UUID
    gate_key: str
    baseline_experiment_id: UUID | None = None
    thresholds: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    created_by: str


class ReleaseGateEvaluationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    gate_id: UUID
    organization_id: UUID
    project_id: UUID
    candidate_experiment_id: UUID
    passed: bool
    detail: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
