"""Attestation boundary models."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AttestationTrigger(StrEnum):
    SCHEDULE = "schedule"
    CHANGE = "change"
    MANUAL = "manual"
    INCIDENT = "incident"


class AttestationResult(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    DEGRADED = "degraded"
    ERROR = "error"


class AttestationRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    accreditation_id: UUID
    trigger: AttestationTrigger
    result: AttestationResult | None
    checks_json: list[dict[str, Any]]
    checks_run: int
    checks_failed: int
    caused_transition_id: UUID | None
    started_at: datetime
    finished_at: datetime | None


class AttestationRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    accreditation_id: UUID
    trigger: AttestationTrigger = AttestationTrigger.MANUAL
    triggered_by: str = "person:api"
