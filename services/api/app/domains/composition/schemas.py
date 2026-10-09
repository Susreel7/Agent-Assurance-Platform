"""Composition boundary models — declared elements and reconciliation rows."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReconciliationStatus(StrEnum):
    ALIGNED = "aligned"
    DECLARED_ONLY = "declared_only"
    OBSERVED_ONLY = "observed_only"
    CONFLICT = "conflict"


class CompositionElementKind(StrEnum):
    TOOL = "tool"
    MCP_SERVER = "mcp_server"
    MODEL = "model"
    SKILL = "skill"
    SUB_AGENT = "sub_agent"
    CONFIG = "config"
    RULE_OBLIGATION = "rule_obligation"
    MEMORY_RETRIEVAL = "memory_retrieval"
    GUARDRAIL = "guardrail"


class RuleObligationIn(BaseModel):
    id: str = Field(min_length=1, max_length=128)
    source_ref: str = Field(min_length=1, max_length=128)
    category: str = Field(min_length=1, max_length=64)
    polarity: str = Field(min_length=1, max_length=32)
    statement: str = Field(min_length=1, max_length=512)
    strength: str = Field(min_length=1, max_length=32)
    digest: str = Field(min_length=8, max_length=128)
    template_ref: str | None = Field(default=None, max_length=128)

    @field_validator("statement")
    @classmethod
    def _statement_byte_bound(cls, v: str) -> str:
        if len(v.encode("utf-8")) > 512:
            raise ValueError("statement must be at most 512 bytes")
        return v


class CompositionBlock(BaseModel):
    """Parsed ``composition`` object. Every list item carries a stable ``name`` or ``id``."""

    model_config = ConfigDict(extra="allow")

    model_policy: dict[str, Any] | None = None
    rule_sources: list[dict[str, Any]] = Field(default_factory=list)
    rule_obligations: list[RuleObligationIn] = Field(default_factory=list)
    skills: list[dict[str, Any]] = Field(default_factory=list)
    sub_agents: list[dict[str, Any]] = Field(default_factory=list)
    configs: list[dict[str, Any]] = Field(default_factory=list)
    memory_retrieval: list[dict[str, Any]] = Field(default_factory=list)
    guardrails: list[dict[str, Any]] = Field(default_factory=list)


class CompositionElementOut(BaseModel):
    kind: CompositionElementKind
    key: str
    declared: bool
    observed: bool
    status: ReconciliationStatus
    observed_count: int = 0
    declared_meta: dict[str, Any] = Field(default_factory=dict)


class CompositionSummary(BaseModel):
    agent_id: UUID
    agent_version_id: UUID
    semver: str
    elements: list[CompositionElementOut]
    rule_sources: list[dict[str, Any]] = Field(default_factory=list)
    rule_obligations: list[RuleObligationIn] = Field(default_factory=list)
    model_policy: dict[str, Any] | None = None


class ReconciliationRowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_id: UUID
    agent_version_id: UUID
    element_kind: str
    element_key: str
    declared: bool
    observed: bool
    status: ReconciliationStatus
    observed_count: int
    window_start: date
    window_end: date
    computed_at: datetime


class ReconciliationPage(BaseModel):
    agent_id: UUID
    agent_version_id: UUID
    window_days: int
    window_start: date
    window_end: date
    items: list[ReconciliationRowOut]
    elements: list[CompositionElementOut]
