"""Experiment boundary models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ExperimentSpec(BaseModel):
    dataset_revision_id: UUID
    prompt_revision_pins: dict[str, UUID] = Field(default_factory=dict)
    rule_revision_pins: dict[str, UUID] = Field(default_factory=dict)
    skill_revision_pins: dict[str, UUID] = Field(default_factory=dict)
    context_revision_pins: dict[str, UUID] = Field(default_factory=dict)
    evaluator_revision_ids: list[UUID] = Field(default_factory=list)
    model_route_alias: str | None = None
    model_settings: dict[str, Any] = Field(default_factory=dict)


class ExperimentCreate(BaseModel):
    experiment_key: str = Field(min_length=1, max_length=128)
    display_name: str = ""
    spec: ExperimentSpec
    baseline_experiment_id: UUID | None = None
    seed: int = 0
    repetitions: int = Field(default=1, ge=1, le=100)
    concurrency: int = Field(default=2, ge=1, le=32)
    budget_usd: float | None = Field(default=None, ge=0)


class ExperimentOut(BaseModel):
    id: UUID
    experiment_key: str
    display_name: str
    status: str
    dataset_revision_id: UUID
    spec_digest: str
    seed: int
    repetitions: int
    concurrency: int
    progress: dict[str, Any]
    aggregates: dict[str, Any]
    created_at: datetime


class ExperimentResultOut(BaseModel):
    id: UUID
    example_id: UUID
    repetition_index: int
    status: str
    trace_id: str | None
    scores: dict[str, Any]
    latency_ms: int | None
    cost_usd: float | None


class ExperimentResultsResponse(BaseModel):
    items: list[ExperimentResultOut]
    comparison: dict[str, Any] | None = None
