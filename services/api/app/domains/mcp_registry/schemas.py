"""MCP registry boundary models.

Nothing here carries a tool argument or a tool result. A capability is described by its
name, the digest of its input schema, the annotations the server declared, and the risk a
reviewer verified — which is everything a decision needs and none of the payload
(AGENTS.md rule 5).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.domains.registry.schemas import LifecycleState


class Transport(StrEnum):
    STDIO = "stdio"
    HTTP = "http"
    SSE = "sse"
    STREAMABLE_HTTP = "streamable_http"


class TrustTier(StrEnum):
    INTERNAL = "internal"
    ACCREDITED = "accredited"
    PARTNER = "partner"
    COMMUNITY = "community"
    UNVERIFIED = "unverified"


class ServerState(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    QUARANTINED = "quarantined"
    RETIRED = "retired"


class CapabilityKind(StrEnum):
    TOOL = "tool"
    RESOURCE = "resource"
    PROMPT = "prompt"


class RiskTier(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class HealthState(StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNREACHABLE = "unreachable"
    DRIFT = "drift"


class ServerRegister(BaseModel):
    slug: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=1024)
    transport: Transport
    endpoint_url: str | None = Field(default=None, max_length=2048)
    command: str | None = Field(default=None, max_length=2048)
    owner_team_id: UUID | None = None
    connection_id: UUID | None = None
    trust_tier: TrustTier = TrustTier.UNVERIFIED
    environments: list[LifecycleState] = Field(min_length=1, max_length=5)
    requires_approval_for_writes: bool = True

    @model_validator(mode="after")
    def _addressable(self) -> ServerRegister:
        if self.transport is Transport.STDIO:
            if not self.command:
                raise ValueError("stdio transport requires a command")
        elif not self.endpoint_url:
            raise ValueError(f"{self.transport.value} transport requires an endpoint_url")
        self.environments = list(dict.fromkeys(self.environments))
        return self


class ServerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=1024)
    owner_team_id: UUID | None = None
    connection_id: UUID | None = None
    trust_tier: TrustTier | None = None
    risk_tier: RiskTier | None = None
    environments: list[LifecycleState] | None = Field(default=None, min_length=1, max_length=5)
    requires_approval_for_writes: bool | None = None


class CapabilityDeclared(BaseModel):
    """One capability as the server advertised it.

    ``input_schema_digest`` is supplied by the discovery client, which hashes the schema
        canonically. Sending the schema itself would put arbitrary server-controlled JSON of
        unbounded size into a control-plane table for no decision-making benefit.
    """

    kind: CapabilityKind
    name: str = Field(min_length=1, max_length=256)
    title: str | None = Field(default=None, max_length=256)
    input_schema_digest: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    declared_read_only: bool | None = None
    declared_destructive: bool | None = None
    declared_idempotent: bool | None = None
    declared_open_world: bool | None = None


class SnapshotSubmit(BaseModel):
    """A discovery result. Recorded whether or not it matches the approved snapshot."""

    protocol_version: str | None = Field(default=None, max_length=32)
    source: str = Field(default="discovery", pattern=r"^(discovery|import|manual|observed)$")
    capabilities: list[CapabilityDeclared] = Field(min_length=0, max_length=4096)


class CapabilityReview(BaseModel):
    """A human's verdict on what a tool actually does.

    Separate from the declared annotations on purpose: an MCP server declares its own
    ``destructiveHint``, and a server that lies about it is precisely the case this
    registry exists to catch.
    """

    verified_risk: RiskTier
    verified_write: bool
    verified_irreversible: bool = False
    review_note: str | None = Field(default=None, max_length=512)

    @model_validator(mode="after")
    def _irreversible_implies_write(self) -> CapabilityReview:
        if self.verified_irreversible and not self.verified_write:
            raise ValueError("an irreversible capability is by definition a write")
        return self


class CapabilityOut(BaseModel):
    id: UUID
    snapshot_id: UUID
    server_id: UUID
    kind: CapabilityKind
    name: str
    title: str | None
    input_schema_digest_hex: str | None
    declared_read_only: bool | None
    declared_destructive: bool | None
    declared_idempotent: bool | None
    declared_open_world: bool | None
    verified_risk: RiskTier
    verified_write: bool
    verified_irreversible: bool
    review_note: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    annotation_mismatch: bool
    """True when the server declared read-only but review found a write."""


class SnapshotOut(BaseModel):
    id: UUID
    server_id: UUID
    capability_digest_hex: str
    protocol_version: str | None
    source: str
    tool_count: int
    resource_count: int
    prompt_count: int
    discovered_at: datetime
    discovered_by: str
    approved_at: datetime | None
    approved_by: str | None
    superseded_at: datetime | None


class ServerOut(BaseModel):
    id: UUID
    org_id: UUID
    slug: str
    name: str
    description: str | None
    transport: Transport
    endpoint_url: str | None
    command: str | None
    owner_team_id: UUID | None
    connection_id: UUID | None
    trust_tier: TrustTier
    state: ServerState
    risk_tier: RiskTier
    health: HealthState
    environments: list[LifecycleState]
    approved_snapshot_id: UUID | None
    observed_snapshot_id: UUID | None
    requires_approval_for_writes: bool
    quarantined_at: datetime | None
    quarantine_reason: str | None
    last_discovered_at: datetime | None
    created_at: datetime
    updated_at: datetime
    created_by: str

    model_config = {"from_attributes": True}


class ServerSummary(BaseModel):
    server: ServerOut
    owner_team_name: str | None
    tool_count: int
    grant_count: int
    dangerous_tool_count: int
    drifted: bool
    """Observed capabilities differ from the approved snapshot."""
    calls_7d: int
    denials_7d: int


class ServerPage(BaseModel):
    items: list[ServerSummary]
    total: int
    limit: int
    offset: int


class ServerDetail(BaseModel):
    """Everything the server page renders, in one response.

    The console's MCP page shows the server, its approved capability list, its grants and
    its recent usage together. Four endpoints would mean four sequential requests for one
    view, and the drift banner needs the approved and observed snapshots side by side to
    say anything true.
    """

    summary: ServerSummary
    approved_snapshot: SnapshotOut | None
    observed_snapshot: SnapshotOut | None
    capabilities: list[CapabilityOut]
    added_capability_names: list[str]
    removed_capability_names: list[str]
    changed_capability_names: list[str]


class GrantCreate(BaseModel):
    capability_name: str | None = Field(default=None, max_length=256)
    """``None`` grants the whole server. A name narrows it to one capability."""
    subject_kind: str = Field(pattern=r"^(member|team|agent|agent_version|workload)$")
    subject_id: UUID
    environments: list[LifecycleState] = Field(min_length=1, max_length=5)
    permission: str = Field(default="invoke", pattern=r"^(invoke|read)$")
    requires_approval: bool = False
    pin_approved_snapshot: bool = True
    """Bind this grant to the snapshot approved now, so new tools are not auto-granted."""
    reason: str | None = Field(default=None, max_length=1024)
    expires_at: datetime | None = None


class GrantOut(BaseModel):
    id: UUID
    server_id: UUID
    capability_name: str | None
    subject_kind: str
    subject_id: UUID
    environments: list[LifecycleState]
    permission: str
    requires_approval: bool
    pinned_snapshot_id: UUID | None
    granted_by: str
    reason: str | None
    expires_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class Quarantine(BaseModel):
    reason: str = Field(min_length=1, max_length=512)


class ToolDecision(BaseModel):
    """The gateway's answer for one attempted tool call.

    ``allowed`` is the only field the gateway must honour. The rest exists so the denial
    is explainable: an operator looking at a blocked call should be able to see which
    grant was missing or which snapshot was stale without reading a policy bundle.
    """

    allowed: bool
    requires_approval: bool
    reason_code: str
    server_id: UUID | None = None
    capability_name: str | None = None
    verified_risk: RiskTier | None = None
    verified_write: bool | None = None
    grant_id: UUID | None = None
    snapshot_digest_hex: str | None = None
    # The runtime route fills these from the verified Platform Key after the policy
    # service answers. They let the adapter attribute aggregate usage without trusting
    # identity fields supplied by the MCP request body.
    workload_credential_id: UUID | None = None
    project_id: UUID | None = None
    agent_id: UUID | None = None
    member_id: UUID | None = None
    environment: LifecycleState | None = None


class ToolDecisionRequest(BaseModel):
    """Ask whether a tool call is permitted.

    The subject is not in this model. It comes from the verified workload credential, so
    a caller cannot ask "may *somebody else* call this" and act on the answer.
    """

    server_slug: str = Field(min_length=1, max_length=128)
    capability_name: str = Field(min_length=1, max_length=256)


class UsageRollup(BaseModel):
    usage_date: str
    server_id: UUID
    capability_name: str
    call_count: int
    denied_count: int
    approval_count: int
    error_count: int
    p95_latency_ms: int | None
    cost_micros: int


class UsageIngest(BaseModel):
    """One day's aggregate for one capability, from the worker.

        Aggregates, never individual calls. At the volumes this platform targets a per-call
    control-plane row is not an option; the per-call record lives in ClickHouse behind
        Observe and this is the rollup the console and the grant reviewer read.
    """

    usage_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    server_id: UUID
    capability_name: str = Field(min_length=1, max_length=256)
    agent_id: UUID | None = None
    member_id: UUID | None = None
    call_count: int = Field(ge=0)
    denied_count: int = Field(default=0, ge=0)
    approval_count: int = Field(default=0, ge=0)
    error_count: int = Field(default=0, ge=0)
    p95_latency_ms: int | None = Field(default=None, ge=0)
    cost_micros: int = Field(default=0, ge=0)
