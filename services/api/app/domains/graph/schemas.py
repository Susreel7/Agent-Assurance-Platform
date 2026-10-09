"""Graph schemas — nodes, edges, traversals and discovery."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class GraphNodeKind(StrEnum):
    AGENT = "agent"
    MODEL = "model"
    PROMPT = "prompt"
    TOOL = "tool"
    MCP_SERVER = "mcp_server"
    DATA_CLASS = "data_class"
    DATA_SOURCE = "data_source"
    VECTOR_STORE = "vector_store"
    DATASET = "dataset"
    GUARDRAIL = "guardrail"
    TEAM = "team"
    PERSON = "person"
    REGION = "region"
    FRAMEWORK = "framework"
    CUSTOMER = "customer"
    ENGAGEMENT = "engagement"


class GraphEdgeKind(StrEnum):
    USES_MODEL = "uses_model"
    USES_PROMPT = "uses_prompt"
    INVOKES_TOOL = "invokes_tool"
    CONNECTS_MCP = "connects_mcp"
    READS_DATA = "reads_data"
    WRITES_DATA = "writes_data"
    DELEGATES_TO = "delegates_to"
    OWNED_BY = "owned_by"
    ACCOUNTABLE_FOR = "accountable_for"
    DEPLOYED_IN = "deployed_in"
    PROCESSES_IN = "processes_in"
    ACCREDITED_UNDER = "accredited_under"
    IN_SCOPE_FOR = "in_scope_for"
    GUARDED_BY = "guarded_by"
    DEPENDS_ON = "depends_on"


class GraphSource(StrEnum):
    DECLARED = "declared"
    OBSERVED = "observed"
    INFERRED = "inferred"


class GraphNodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: GraphNodeKind
    node_key: str
    label: str
    entity_id: UUID | None
    attrs: dict[str, object] = Field(default_factory=dict)
    is_declared: bool
    is_observed: bool
    first_seen_at: datetime
    last_seen_at: datetime
    retired_at: datetime | None


class GraphEdgeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    src_id: UUID
    dst_id: UUID
    kind: GraphEdgeKind
    source: GraphSource
    confidence: Decimal
    agent_version_id: UUID | None
    observation_count: int
    attrs: dict[str, object] = Field(default_factory=dict)
    first_seen_at: datetime
    last_seen_at: datetime
    retired_at: datetime | None


class NeighbourhoodNode(BaseModel):
    node_id: UUID
    kind: GraphNodeKind
    node_key: str
    label: str
    depth: int
    via_edge_kind: GraphEdgeKind


class Neighbourhood(BaseModel):
    origin_id: UUID
    depth: int
    nodes: list[NeighbourhoodNode] = Field(default_factory=list)


class BlastRadiusNode(BaseModel):
    node_id: UUID
    kind: GraphNodeKind
    node_key: str
    label: str
    depth: int


class BlastRadius(BaseModel):
    origin_id: UUID
    max_depth: int
    nodes: list[BlastRadiusNode] = Field(default_factory=list)


class ReconciliationRow(BaseModel):
    src_id: UUID
    dst_id: UUID
    kind: GraphEdgeKind
    declared: bool
    observed: bool
    reconciliation: str
    last_seen_at: datetime
    observation_count: int


class ReconciliationSummary(BaseModel):
    confirmed: int
    declared_not_observed: int
    observed_not_declared: int
    rows: list[ReconciliationRow] = Field(default_factory=list)


class PathHop(BaseModel):
    node_id: UUID
    kind: GraphNodeKind
    node_key: str
    label: str


class PathResult(BaseModel):
    src_id: UUID
    dst_id: UUID
    found: bool
    hops: list[PathHop] = Field(default_factory=list)


class DiscoverySourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    kind: str
    name: str
    is_enabled: bool
    last_run_at: datetime | None
    last_status: str | None
    findings_last_run: int


class DiscoveryFindingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_id: UUID
    candidate_kind: GraphNodeKind
    candidate_key: str
    label: str
    confidence: Decimal
    state: str
    agent_id: UUID | None
    first_seen_at: datetime
    last_seen_at: datetime


class DiscoveryFindingResolve(BaseModel):
    action: str = Field(description="confirm | dismiss | merge")
    agent_id: UUID | None = None
    note: str | None = Field(default=None, max_length=2000)
    resolved_by: str = Field(min_length=1, max_length=320)
