"""Online evaluator rule models."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OnlineRuleCreate(BaseModel):
    rule_key: str = Field(min_length=1, max_length=128)
    filter: dict[str, Any] = Field(default_factory=dict)
    sample_rate: float = Field(default=0.01, ge=0, le=1)
    sample_hash_salt: str | None = None
    evaluator_revision_ids: list[UUID] = Field(default_factory=list)
    budget_usd: float | None = Field(default=None, ge=0)
    max_concurrency: int = Field(default=2, ge=1, le=32)
    actions: list[dict[str, Any]] = Field(default_factory=list)


class ObserveWebhookEvent(BaseModel):
    trace_id: str
    organization_id: UUID
    project_id: UUID
    metadata: dict[str, Any] = Field(default_factory=dict)


class OnlineRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    project_id: UUID
    rule_key: str
    enabled: bool = True
    filter: dict[str, Any] = Field(default_factory=dict)
    sample_rate: float
    evaluator_revision_ids: list[Any] = Field(default_factory=list)
    budget_usd: float | None = None
    max_concurrency: int
    spent_usd: float = 0
    circuit_open_until: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None


class AlertOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="ignore")

    id: UUID
    organization_id: UUID
    project_id: UUID
    rule_id: UUID | None = None
    action_type: str
    target: str
    payload_digest: str
    status: str
    attempts: int
    max_attempts: int
    last_error: str | None = None
    delivered_at: datetime | None = None
    acknowledged_at: datetime | None = None
    created_at: datetime
    updated_at: datetime | None = None
    payload_trace_id: str | None = None
