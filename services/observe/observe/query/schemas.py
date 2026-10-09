"""Query API boundary models."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TenantFilter(BaseModel):
    organization_id: UUID
    project_id: UUID


class TraceSummary(BaseModel):
    trace_id: str
    session_id: str | None = None
    service_name: str | None = None
    agent_id: str | None = None
    span_count: int = 0
    start_time: datetime | None = None
    end_time: datetime | None = None
    total_cost_micros: int | None = None
    outcome: str | None = None


class TraceListResponse(BaseModel):
    items: list[TraceSummary]
    limit: int
    offset: int
    total: int | None = None


class SessionSummary(BaseModel):
    session_id: str
    user_session_id: str | None = None
    display_name: str | None = None
    initiating_user_id: str | None = None
    status: str = "unknown"
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_ms: float | None = None
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None
    trace_count: int = 0
    execution_count: int = 0
    span_count: int = 0
    node_count: int = 0
    generation_count: int = 0
    tool_count: int = 0
    sdk_count: int = 0
    total_cost_micros: int = 0
    error_count: int = 0
    retry_count: int = 0
    replay_count: int = 0
    agent_ids: list[str] = Field(default_factory=list)
    environment_ids: list[str] = Field(default_factory=list)


class SessionListResponse(BaseModel):
    items: list[SessionSummary]
    limit: int
    offset: int
    total: int | None = None


class SessionDetailResponse(BaseModel):
    session: SessionSummary
    traces: list[TraceSummary]


class SpanOut(BaseModel):
    trace_id: str
    span_id: str
    parent_span_id: str | None = None
    kind: str
    operation_name: str
    outcome: str | None = None
    model: str | None = None
    tool_name: str | None = None
    duration_ms: float | None = None
    source_convention: str | None = None


class TraceDetailResponse(BaseModel):
    trace_id: str
    spans: list[SpanOut]
    limit: int
    offset: int
    truncated: bool = False
    malformed: bool = False
    has_cycle: bool = False


class GraphNode(BaseModel):
    span_id: str
    parent_span_id: str | None = None
    kind: str
    operation_name: str


class TraceGraphResponse(BaseModel):
    trace_id: str
    nodes: list[GraphNode]
    malformed: bool
    has_cycle: bool


class SearchFacets(BaseModel):
    time_range: dict[str, str | None] = Field(default_factory=dict)
    agents: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    kinds: list[str] = Field(default_factory=list)
    outcomes: list[str] = Field(default_factory=list)


class MetricsResponse(BaseModel):
    span_count: int
    trace_count: int = 0
    error_rate: float
    avg_latency_ms: float
    p50_latency_ms: float = 0
    p95_latency_ms: float = 0
    p99_latency_ms: float = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_micros: int


class AnalyticsBreakdownItem(BaseModel):
    label: str
    count: int
    failed_count: int = 0
    avg_duration_ms: float | None = None
    total_cost_micros: int = 0


class PipelineMetrics(BaseModel):
    pending_manifests: int = 0
    processing_manifests: int = 0
    quarantined_manifests: int = 0
    processed_24h: int = 0
    pending_projections: int = 0
    partial_executions: int = 0
    malformed_executions: int = 0
    late_executions: int = 0
    last_manifest_at: datetime | None = None


class ExecutionAnalyticsResponse(BaseModel):
    execution_count: int = 0
    session_count: int = 0
    user_count: int = 0
    actor_count: int = 0
    agent_count: int = 0
    success_count: int = 0
    failed_count: int = 0
    success_rate: float | None = None
    error_rate: float | None = None
    avg_duration_ms: float | None = None
    p50_duration_ms: float | None = None
    p90_duration_ms: float | None = None
    p95_duration_ms: float | None = None
    p99_duration_ms: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_micros: int = 0
    error_count: int = 0
    retry_count: int = 0
    population_start: datetime | None = None
    population_end: datetime | None = None
    population_label: str = "Recorded executions"
    by_agent: list[AnalyticsBreakdownItem] = Field(default_factory=list)
    by_environment: list[AnalyticsBreakdownItem] = Field(default_factory=list)
    by_user: list[AnalyticsBreakdownItem] = Field(default_factory=list)
    by_source: list[AnalyticsBreakdownItem] = Field(default_factory=list)
    by_framework: list[AnalyticsBreakdownItem] = Field(default_factory=list)
    by_status: list[AnalyticsBreakdownItem] = Field(default_factory=list)
    by_model: list[AnalyticsBreakdownItem] = Field(default_factory=list)
    by_tool: list[AnalyticsBreakdownItem] = Field(default_factory=list)
    by_sdk: list[AnalyticsBreakdownItem] = Field(default_factory=list)
    by_mcp: list[AnalyticsBreakdownItem] = Field(default_factory=list)
    pipeline: PipelineMetrics = Field(default_factory=PipelineMetrics)


class SamplingPolicyUpdate(BaseModel):
    head_sample_rate: float = Field(ge=0, le=1)
    tail_keep_errors: bool = True
    tail_keep_retries: bool = True
    tail_keep_high_latency: bool = True
    high_latency_ms: float = Field(default=10000, gt=0)
    max_traces_per_minute: int | None = Field(default=None, gt=0)


class SamplingPolicyOut(SamplingPolicyUpdate):
    organization_id: UUID
    project_id: UUID
    revision: int
    updated_by: str | None = None
    updated_at: datetime | None = None


class PayloadRefOut(BaseModel):
    trace_id: str
    span_id: str
    field_name: str
    digest: str
    media_type: str
    byte_size: int
    payload_id: UUID
    content_path: str
    redaction_state: str | None = None
    retention_deadline: datetime | None = None
    legal_hold: bool = False
    legal_hold_reason: str | None = None
    legal_hold_actor: str | None = None
    legal_hold_at: datetime | None = None
    retention_deleted_at: datetime | None = None
    signed_url: str | None = None
    expires_at: datetime | None = None


class PayloadLegalHoldRequest(BaseModel):
    enabled: bool
    reason: str | None = Field(default=None, max_length=512)
    actor_subject: str = Field(min_length=1, max_length=256)


class PayloadLegalHoldOut(BaseModel):
    payload_id: UUID
    legal_hold: bool
    legal_hold_reason: str | None = None
    legal_hold_actor: str | None = None
    legal_hold_at: datetime | None = None
    retention_deadline: datetime | None = None
    retention_deleted_at: datetime | None = None


class ExecutionSummary(BaseModel):
    execution_id: str
    execution_type: str | None = None
    trace_id: str
    root_span_id: str | None = None
    parent_execution_id: str | None = None
    parent_trace_id: str | None = None
    session_id: str | None = None
    user_session_id: str | None = None
    environment_id: str | None = None
    status: str | None = None
    agent_id: str | None = None
    agent_version_id: str | None = None
    agent_name: str | None = None
    initiating_user_id: str | None = None
    effective_actor_id: str | None = None
    effective_actor_type: str | None = None
    invocation_source: str | None = None
    application_name: str | None = None
    client_name: str | None = None
    request_id: str | None = None
    replay_of_execution_id: str | None = None
    replay_reason: str | None = None
    repository_ref: str | None = None
    branch_ref: str | None = None
    commit_sha: str | None = None
    deployment_name: str | None = None
    region_name: str | None = None
    runtime_name: str | None = None
    framework: str | None = None
    framework_version: str | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_ms: float | None = None
    span_count: int = 0
    node_count: int = 0
    generation_count: int = 0
    tool_count: int = 0
    sdk_count: int = 0
    mcp_tool_count: int = 0
    error_count: int = 0
    retry_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_cost_micros: int = 0
    is_live: bool = False
    is_partial: bool = False
    is_malformed: bool = False
    has_cycle: bool = False
    has_late_data: bool = False
    capture_level: str | None = None
    provider: str | None = None
    sdk_name: str | None = None
    mcp_server: str | None = None
    tags: list[str] = Field(default_factory=list)


class ExecutionListResponse(BaseModel):
    items: list[ExecutionSummary]
    limit: int
    offset: int
    total: int | None = None


class ExecutionDetailResponse(BaseModel):
    execution: ExecutionSummary
    trace_id: str
    malformed: bool = False
    has_cycle: bool = False


class ExecutionObservationOut(BaseModel):
    span_id: str
    parent_span_id: str | None = None
    execution_id: str | None = None
    parent_execution_id: str | None = None
    kind: str
    observation_type: str | None = None
    operation_name: str
    outcome: str | None = None
    model: str | None = None
    tool_name: str | None = None
    provider: str | None = None
    sdk_name: str | None = None
    sdk_version: str | None = None
    sdk_operation: str | None = None
    mcp_server: str | None = None
    mcp_method: str | None = None
    mcp_role: str | None = None
    mcp_request_id: str | None = None
    a2a_target_agent_id: str | None = None
    a2a_target_execution_id: str | None = None
    a2a_target_trace_id: str | None = None
    retry_attempt: int = 0
    graph_node_id: str | None = None
    graph_node_path: str | None = None
    initiating_user_id: str | None = None
    effective_actor_id: str | None = None
    effective_actor_type: str | None = None
    user_session_id: str | None = None
    environment_id: str | None = None
    agent_version_id: str | None = None
    session_id: str | None = None
    service_name: str | None = None
    agent_id: str | None = None
    agent_name: str | None = None
    duration_ms: float | None = None
    start_time: datetime | None = None
    end_time: datetime | None = None
    is_terminal: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    cost_micros: int = 0
    tags: list[str] = Field(default_factory=list)


class ExecutionObservationsResponse(BaseModel):
    execution_id: str
    items: list[ExecutionObservationOut]
    limit: int
    offset: int
    truncated: bool = False


class ExecutionEventOut(BaseModel):
    event_uid: str | None = None
    execution_id: str | None = None
    trace_id: str | None = None
    event_type: str
    observation_type: str | None = None
    event_time: datetime | None = None
    status: str | None = None
    span_id: str | None = None
    initiating_user_id: str | None = None
    effective_actor_id: str | None = None
    agent_id: str | None = None
    model: str | None = None
    tool_name: str | None = None
    sdk_name: str | None = None
    sdk_operation: str | None = None
    mcp_server: str | None = None
    mcp_method: str | None = None
    sequence: int = 0
    attributes: dict[str, str] = Field(default_factory=dict)


class ExecutionEventsResponse(BaseModel):
    execution_id: str
    items: list[ExecutionEventOut]
    limit: int


class ExecutionTimelineItem(BaseModel):
    kind: str
    label: str
    start_time: datetime | None = None
    end_time: datetime | None = None
    observation_type: str | None = None
    span_id: str | None = None
    event_type: str | None = None


class ExecutionTimelineResponse(BaseModel):
    execution_id: str
    items: list[ExecutionTimelineItem]


class ExecutionLinkOut(BaseModel):
    id: UUID
    execution_id: str
    link_type: str
    target_execution_id: str | None = None
    target_trace_id: str | None = None
    target_span_id: str | None = None
    direction: str
    created_at: datetime


class ObservedUserSummary(BaseModel):
    user_id: str
    display_label: str | None = None
    team: str | None = None
    activity_source: str | None = None
    execution_count: int = 0
    generation_count: int = 0
    tool_count: int = 0
    sdk_count: int = 0
    mcp_tool_count: int = 0
    first_seen_at: datetime | None = None
    last_seen_at: datetime | None = None


class UserIdentityBindingRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=256)
    binding_type: str = Field(pattern="^(oidc_subject|app_user_id|external_id)$")
    binding_value: str = Field(min_length=1, max_length=512)


class UserIdentityBindingOut(BaseModel):
    id: UUID
    user_id: str
    binding_type: str
    binding_value: str
    created_at: datetime


class ObservedUserListResponse(BaseModel):
    items: list[ObservedUserSummary]
    limit: int
    offset: int
    total: int | None = None


class LabeledCount(BaseModel):
    count: int


class ModelUsageCount(LabeledCount):
    model: str


class ToolUsageCount(LabeledCount):
    tool: str


class McpToolUsageCount(LabeledCount):
    server: str
    tool: str


class SdkUsageCount(LabeledCount):
    sdk: str
    operation: str = ""


class UserActivityBreakdown(BaseModel):
    user_id: str
    models: list[ModelUsageCount] = Field(default_factory=list)
    tools: list[ToolUsageCount] = Field(default_factory=list)
    mcp_tools: list[McpToolUsageCount] = Field(default_factory=list)
    sdk_operations: list[SdkUsageCount] = Field(default_factory=list)


class PayloadContentResponse(BaseModel):
    payload_id: UUID
    media_type: str
    byte_size: int
    redaction_state: str | None = None
    content_base64: str | None = None
