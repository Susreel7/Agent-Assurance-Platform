"""Service level boundary models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SloKind(StrEnum):
    AVAILABILITY = "availability"
    LATENCY_P50 = "latency_p50"
    LATENCY_P95 = "latency_p95"
    LATENCY_P99 = "latency_p99"
    SUCCESS_RATE = "success_rate"
    RESOLUTION_P1 = "resolution_p1"
    RESOLUTION_P2 = "resolution_p2"


class SloCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engagement_id: UUID | None = None
    agent_id: UUID | None = None
    service_level_id: UUID | None = None
    kind: SloKind
    target: Decimal
    unit: str | None = None
    measurement_window: str = "monthly"
    penalty_model: dict[str, Any] = Field(default_factory=dict)


class SloOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    engagement_id: UUID | None
    agent_id: UUID | None
    service_level_id: UUID | None
    kind: SloKind
    target: Decimal
    unit: str | None
    measurement_window: str
    penalty_model: dict[str, Any]
    is_enabled: bool
    created_at: datetime


class MeasurementCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bucket_start: datetime
    bucket_end: datetime
    value: Decimal
    sample_count: int = Field(ge=0)


class MeasurementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slo_id: UUID
    bucket_start: datetime
    bucket_end: datetime
    value: Decimal
    sample_count: int
    is_breaching: bool
    computed_at: datetime


class BreachOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slo_id: UUID
    started_at: datetime
    ended_at: datetime | None
    worst_value: Decimal
    target: Decimal
    credit_amount: Decimal | None
    credit_currency: str
    credit_basis: str | None


class EngagementSloSummary(BaseModel):
    slo_id: UUID
    kind: str
    target: Decimal
    attainment: Decimal | None
    open_breach_count: int
    total_credit_gbp: Decimal


class EngagementSummaryOut(BaseModel):
    engagement_id: UUID
    slos: list[EngagementSloSummary]
    total_credit_gbp: Decimal
