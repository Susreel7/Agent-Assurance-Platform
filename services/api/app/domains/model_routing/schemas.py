"""Model routing boundary models — catalogue, compiled policy, gateway emission."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domains.engagements.schemas import CrossBorderTransfer


class HostingMode(StrEnum):
    VENDOR_API = "vendor_api"
    CLOUD_MANAGED = "cloud_managed"
    SELF_HOSTED = "self_hosted"


class DataHandlingTerms(StrEnum):
    ZERO_RETENTION = "zero_retention"
    THIRTY_DAY = "30_day"
    PROVIDER_DEFAULT = "provider_default"
    UNKNOWN = "unknown"


class ClassificationState(StrEnum):
    CLASSIFIED = "classified"
    UNCLASSIFIED = "unclassified"
    DEPRECATED = "deprecated"


class EnforcementLevel(StrEnum):
    """Gradual rollout: advisory records, blocking refuses dispatch at the gateway."""

    ADVISORY = "advisory"
    OVERRIDEABLE = "overrideable"
    BLOCKING = "blocking"


class ModelSelectionMode(StrEnum):
    PINNED = "pinned"
    ALLOWLIST = "allowlist"
    AUTO = "auto"


class CatalogEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID | None
    provider: str
    model_id: str
    display_name: str | None
    hosting_mode: HostingMode
    primary_region: str
    jurisdiction: str
    cross_border_ok: bool
    data_handling_terms: DataHandlingTerms
    classification_state: ClassificationState
    source: str
    source_url: str | None
    valid_from: date
    valid_to: date | None
    digest: str


class CatalogEntryCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=64)
    model_id: str = Field(min_length=1, max_length=128)
    display_name: str | None = Field(default=None, max_length=200)
    hosting_mode: HostingMode = HostingMode.VENDOR_API
    primary_region: str = Field(min_length=1, max_length=64)
    jurisdiction: str = Field(min_length=1, max_length=16)
    cross_border_ok: bool = False
    data_handling_terms: DataHandlingTerms = DataHandlingTerms.UNKNOWN
    classification_state: ClassificationState = ClassificationState.CLASSIFIED
    source: str = Field(default="operator_assertion", max_length=64)
    source_url: str | None = Field(default=None, max_length=512)
    valid_from: date | None = None


class CatalogPage(BaseModel):
    items: list[CatalogEntryOut]
    total: int
    unclassified_count: int


class AllowedDeployment(BaseModel):
    """One row the gateway may route to — region_name is what LiteLLM filters on."""

    catalog_entry_id: UUID
    provider: str
    model_id: str
    region_name: str
    jurisdiction: str


class CompiledModelPolicy(BaseModel):
    """Compiled allow-set shared by the decision endpoint and emitted gateway config."""

    agent_id: UUID
    agent_version_id: UUID
    engagement_id: UUID | None
    selection_mode: ModelSelectionMode
    allowed_deployments: tuple[AllowedDeployment, ...]
    allowed_patterns: tuple[str, ...]
    permitted_regions: frozenset[str]
    cross_border_rung: CrossBorderTransfer
    enforcement_level: EnforcementLevel
    virtual_key_ref: str | None
    compiled_at: datetime
    rules_digest: str


class GatewayTargetKind(StrEnum):
    """Pluggable enforcement point — LiteLLM is the first supported emitter."""

    LITELLM = "litellm"


class GatewayConfigOut(BaseModel):
    """OpenAI-compatible gateway configuration derived from ``CompiledModelPolicy``."""

    target: GatewayTargetKind = GatewayTargetKind.LITELLM
    agent_id: UUID
    agent_version_id: UUID
    rules_digest: str
    config: dict[str, object]
    enforcement_level: EnforcementLevel
    fallback_access_enforced: bool


class ModelRoutingEvaluateRequest(BaseModel):
    agent_id: UUID
    agent_version_id: UUID | None = None
    engagement_id: UUID | None = None
    environment: str | None = Field(
        default=None,
        description="Agent version environment; production triggers fail-closed rules.",
    )
    model_provider: str = Field(min_length=1, max_length=64)
    model_id: str = Field(min_length=1, max_length=128)
    data_classes: list[str] = Field(default_factory=list)
    lawful_basis: dict[str, str] = Field(default_factory=dict)
    subject_ref: str | None = Field(default=None, max_length=256)
    enforcement_level: EnforcementLevel | None = None
    region_hint: str | None = Field(default=None, max_length=64)


class ModelRoutingEvaluateResult(BaseModel):
    outcome: str
    would_block: bool
    http_status: int
    reason_code: str
    rule_id: str
    effective_region: str | None = None
    catalog_entry_id: UUID | None = None
    policy_decision_id: UUID | None = None
    compiled_rules_digest: str


class GatewayLogIngest(BaseModel):
    agent_id: UUID | None = None
    agent_version_id: UUID | None = None
    engagement_id: UUID | None = None
    model_provider: str = Field(min_length=1, max_length=64)
    model_id: str = Field(min_length=1, max_length=128)
    region_used: str | None = Field(default=None, max_length=64)
    virtual_key_ref: str | None = Field(default=None, max_length=128)
    outcome: str = Field(min_length=1, max_length=32)
    logged_at: datetime
    log_digest: str = Field(min_length=8, max_length=128)


class RouterProvider(StrEnum):
    OPENAI = "openai"
    OPENAI_COMPATIBLE = "openai_compatible"
    AZURE_OPENAI = "azure_openai"
    ANTHROPIC = "anthropic"
    BEDROCK = "bedrock"
    GEMINI = "gemini"
    VERTEX = "vertex"


class RouterCapability(StrEnum):
    CHAT = "chat"
    RESPONSES = "responses"
    EMBEDDINGS = "embeddings"
    STREAMING = "streaming"
    RESPONSES_STREAM = "responses_stream"
    TOOLS = "tools"
    JSON_SCHEMA = "json_schema"
    VISION = "vision"
    REASONING = "reasoning"


class RouteStrategy(StrEnum):
    PRIORITY = "priority"
    WEIGHTED = "weighted"
    LEAST_BUSY = "least_busy"
    LATENCY = "latency"
    LOWEST_COST = "lowest_cost"


class RouteEnvironment(StrEnum):
    DEV = "dev"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class SnapshotStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    EXPIRED = "expired"


class CooldownPolicyIn(BaseModel):
    failure_threshold: int = Field(ge=1, le=100)
    initial_cooldown_ms: int = Field(ge=1, le=3600000)
    max_cooldown_ms: int = Field(ge=1, le=86400000)

    @model_validator(mode="after")
    def _ordered(self) -> CooldownPolicyIn:
        if self.max_cooldown_ms < self.initial_cooldown_ms:
            raise ValueError("max_cooldown_ms must be at least initial_cooldown_ms")
        return self


class DeploymentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    provider: RouterProvider
    model: str = Field(min_length=1, max_length=256)
    endpoint: str = Field(min_length=1, max_length=2048)
    credential_ref: str = Field(min_length=1, max_length=512)
    region: str = Field(min_length=1, max_length=64)
    jurisdiction: str = Field(min_length=1, max_length=16)
    capabilities: list[RouterCapability] = Field(min_length=1)
    priority: int = Field(default=100, ge=0, le=10000)
    weight: int = Field(default=100, ge=1, le=10000)
    rpm: int | None = Field(default=None, ge=1)
    tpm: int | None = Field(default=None, ge=1)
    timeout_ms: int = Field(default=60000, ge=100, le=3600000)
    max_retries: int = Field(default=2, ge=0, le=10)
    input_price_micros_per_m: int = Field(default=0, ge=0)
    output_price_micros_per_m: int = Field(default=0, ge=0)
    max_concurrency: int | None = Field(default=None, ge=1)
    daily_budget_micros: int | None = Field(default=None, ge=1)
    cooldown: CooldownPolicyIn | None = None
    data_classes: list[str] = Field(default_factory=list, max_length=64)

    @model_validator(mode="after")
    def _validate_runtime_values(self) -> DeploymentCreate:
        endpoint = urlsplit(self.endpoint)
        if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
            raise ValueError("endpoint must be an absolute http(s) URL")
        if len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("capabilities must be unique")
        if len(set(self.data_classes)) != len(self.data_classes):
            raise ValueError("data_classes must be unique")
        return self


class DeploymentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    endpoint: str | None = Field(default=None, min_length=1, max_length=2048)
    credential_ref: str | None = Field(default=None, min_length=1, max_length=512)
    capabilities: list[RouterCapability] | None = Field(default=None, min_length=1)
    priority: int | None = Field(default=None, ge=0, le=10000)
    weight: int | None = Field(default=None, ge=1, le=10000)
    rpm: int | None = Field(default=None, ge=1)
    tpm: int | None = Field(default=None, ge=1)
    timeout_ms: int | None = Field(default=None, ge=100, le=3600000)
    max_retries: int | None = Field(default=None, ge=0, le=10)
    input_price_micros_per_m: int | None = Field(default=None, ge=0)
    output_price_micros_per_m: int | None = Field(default=None, ge=0)
    max_concurrency: int | None = Field(default=None, ge=1)
    daily_budget_micros: int | None = Field(default=None, ge=1)
    cooldown: CooldownPolicyIn | None = None
    data_classes: list[str] | None = None

    @model_validator(mode="after")
    def _validate_runtime_values(self) -> DeploymentUpdate:
        required = {
            "name",
            "endpoint",
            "credential_ref",
            "capabilities",
            "priority",
            "weight",
            "timeout_ms",
            "max_retries",
            "input_price_micros_per_m",
            "output_price_micros_per_m",
        }
        null_required = [
            key for key in required if key in self.model_fields_set and getattr(self, key) is None
        ]
        if null_required:
            raise ValueError(f"{', '.join(sorted(null_required))} cannot be null")
        if self.endpoint is not None:
            endpoint = urlsplit(self.endpoint)
            if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
                raise ValueError("endpoint must be an absolute http(s) URL")
        if self.capabilities is not None and len(set(self.capabilities)) != len(self.capabilities):
            raise ValueError("capabilities must be unique")
        if self.data_classes is not None and len(set(self.data_classes)) != len(self.data_classes):
            raise ValueError("data_classes must be unique")
        return self


class DeploymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    project_id: UUID
    name: str
    provider: RouterProvider
    model: str
    endpoint: str
    credential_ref: str
    region: str
    jurisdiction: str
    capabilities: list[RouterCapability]
    priority: int
    weight: int
    rpm: int | None
    tpm: int | None
    timeout_ms: int
    max_retries: int
    input_price_micros_per_m: int
    output_price_micros_per_m: int
    max_concurrency: int | None
    daily_budget_micros: int | None
    cooldown: CooldownPolicyIn | None = None
    data_classes: list[str]
    disabled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DeploymentPage(BaseModel):
    items: list[DeploymentOut]
    total: int


class RouteTargetIn(BaseModel):
    deployment_id: UUID
    position: int = Field(ge=0)


class RouteCreate(BaseModel):
    agent_id: UUID
    agent_version_id: UUID | None = None
    environment: RouteEnvironment
    alias: str = Field(min_length=1, max_length=256)
    strategy: RouteStrategy = RouteStrategy.PRIORITY
    enforcement: EnforcementLevel = EnforcementLevel.ADVISORY
    targets: list[RouteTargetIn] = Field(min_length=1)
    permitted_regions: list[str] = Field(default_factory=list)
    data_classes: list[str] = Field(default_factory=list)
    fallback_before_first_byte: bool = True
    max_attempts: int = Field(default=3, ge=1, le=10)
    response_cache_enabled: bool = False
    response_cache_ttl_seconds: int | None = Field(default=None, ge=1, le=86400)

    @model_validator(mode="after")
    def _validate_route(self) -> RouteCreate:
        deployment_ids = [target.deployment_id for target in self.targets]
        positions = [target.position for target in self.targets]
        if len(set(deployment_ids)) != len(deployment_ids):
            raise ValueError("route deployment targets must be unique")
        if len(set(positions)) != len(positions):
            raise ValueError("route target positions must be unique")
        if self.response_cache_enabled and self.response_cache_ttl_seconds is None:
            raise ValueError("response_cache_ttl_seconds is required when cache is enabled")
        return self


class RouteUpdate(BaseModel):
    agent_version_id: UUID | None = None
    strategy: RouteStrategy | None = None
    enforcement: EnforcementLevel | None = None
    targets: list[RouteTargetIn] | None = Field(default=None, min_length=1)
    permitted_regions: list[str] | None = None
    data_classes: list[str] | None = None
    fallback_before_first_byte: bool | None = None
    max_attempts: int | None = Field(default=None, ge=1, le=10)
    response_cache_enabled: bool | None = None
    response_cache_ttl_seconds: int | None = Field(default=None, ge=1, le=86400)

    @model_validator(mode="after")
    def _validate_targets(self) -> RouteUpdate:
        required = {
            "strategy",
            "enforcement",
            "targets",
            "fallback_before_first_byte",
            "max_attempts",
            "response_cache_enabled",
        }
        null_required = [
            key for key in required if key in self.model_fields_set and getattr(self, key) is None
        ]
        if null_required:
            raise ValueError(f"{', '.join(sorted(null_required))} cannot be null")
        if self.targets is None:
            return self
        deployment_ids = [target.deployment_id for target in self.targets]
        positions = [target.position for target in self.targets]
        if len(set(deployment_ids)) != len(deployment_ids):
            raise ValueError("route deployment targets must be unique")
        if len(set(positions)) != len(positions):
            raise ValueError("route target positions must be unique")
        return self


class RouteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    project_id: UUID
    agent_id: UUID
    agent_version_id: UUID | None
    environment: RouteEnvironment
    alias: str
    strategy: RouteStrategy
    enforcement: EnforcementLevel
    targets: list[RouteTargetIn]
    permitted_regions: list[str]
    data_classes: list[str]
    fallback_before_first_byte: bool
    max_attempts: int
    response_cache_enabled: bool
    response_cache_ttl_seconds: int | None
    disabled_at: datetime | None
    created_at: datetime
    updated_at: datetime


class RoutePage(BaseModel):
    items: list[RouteOut]
    total: int


class RouteSimulateRequest(BaseModel):
    operation: str = Field(default="chat", min_length=1, max_length=64)
    data_class: str | None = Field(default=None, max_length=64)
    region_hint: str | None = Field(default=None, max_length=64)


class RouteTargetSimulation(BaseModel):
    deployment_id: UUID
    position: int
    eligible: bool
    reason: str


class RouteSimulateResult(BaseModel):
    route_id: UUID
    targets: list[RouteTargetSimulation]


class SnapshotCompileRequest(BaseModel):
    """Optional override; default TTL comes from settings."""

    expires_at: datetime | None = None


class SnapshotOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    org_id: UUID
    project_id: UUID
    config_digest: str
    rules_digest: str
    key_id: str
    issued_at: datetime
    expires_at: datetime
    status: SnapshotStatus
    compiled_by: str
    created_at: datetime


class SnapshotConfigMeta(BaseModel):
    snapshot_id: UUID
    config_digest: str
    rules_digest: str
    key_id: str
    signature: str
    issued_at: datetime
    expires_at: datetime
    public_key_pem: str


class RoutingOverview(BaseModel):
    """Console summary — catalogue health, recent denials, drift signals."""

    unclassified_models: list[CatalogEntryOut]
    recent_denials: list[dict[str, object]]
    drift_findings: list[dict[str, object]]
    observation_note: str = (
        "Observed models from run steps detect drift only; they do not block requests."
    )
