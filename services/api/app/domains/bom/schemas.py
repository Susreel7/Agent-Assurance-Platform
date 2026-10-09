"""BOM schemas — what is inside one agent version."""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ComponentKind(StrEnum):
    MODEL = "model"
    PROMPT = "prompt"
    TOOL = "tool"
    MCP_SERVER = "mcp_server"
    DATA_SOURCE = "data_source"
    VECTOR_STORE = "vector_store"
    SUB_AGENT = "sub_agent"
    GUARDRAIL = "guardrail"
    SKILL = "skill"
    CONFIG = "config"
    RULE_SOURCE = "rule_source"
    RULE_OBLIGATION = "rule_obligation"
    MODEL_POLICY = "model_policy"


class BomComponentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    agent_version_id: UUID
    kind: ComponentKind
    name: str
    version: str | None
    provider: str | None
    digest: str | None
    effect: str | None
    reversible: bool | None


class BomSummary(BaseModel):
    agent_version_id: UUID
    total: int
    by_kind: dict[str, int] = Field(default_factory=dict)


class BomPage(BaseModel):
    items: list[BomComponentOut]
    summary: BomSummary
