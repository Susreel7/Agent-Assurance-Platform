"""Trust portal boundary models — customer-safe aggregates only."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.domains.assurance.schemas import SeverityCounts


class PortalAgentSummary(BaseModel):
    agent_id: UUID
    accreditation_state: str | None
    pack_download_refs: list[str] = Field(default_factory=list)


class PortalViewOut(BaseModel):
    engagement_id: UUID
    engagement_slug: str
    agents: list[PortalAgentSummary]
    slo_attainment: dict[str, Decimal | None]
    finding_counts: SeverityCounts
    residency_summary: str
    chain_valid: bool
    chain_checked_at: datetime | None = None
