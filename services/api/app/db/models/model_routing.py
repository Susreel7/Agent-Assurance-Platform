"""ORM for migrations 0012 and 0015 — catalogue, gateway logs, router runtime."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, ENUM
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped

_hosting_mode = ENUM(
    "vendor_api",
    "cloud_managed",
    "self_hosted",
    name="model_hosting_mode",
    create_type=False,
)
_data_handling = ENUM(
    "zero_retention",
    "30_day",
    "provider_default",
    "unknown",
    name="model_data_handling_terms",
    create_type=False,
)
_classification = ENUM(
    "classified",
    "unclassified",
    "deprecated",
    name="model_classification_state",
    create_type=False,
)
_router_provider = ENUM(
    "openai",
    "openai_compatible",
    "azure_openai",
    "anthropic",
    "bedrock",
    "gemini",
    "vertex",
    name="router_provider",
    create_type=False,
)
_router_strategy = ENUM(
    "priority",
    "weighted",
    "least_busy",
    "latency",
    "lowest_cost",
    name="router_route_strategy",
    create_type=False,
)
_router_snapshot_status = ENUM(
    "active",
    "superseded",
    "expired",
    name="router_snapshot_status",
    create_type=False,
)
_enforcement = ENUM(
    "advisory",
    "overrideable",
    "blocking",
    name="model_routing_enforcement_level",
    create_type=False,
)
_lifecycle = ENUM(
    "dev",
    "test",
    "staging",
    "production",
    "retired",
    name="lifecycle_state",
    create_type=False,
)


class ModelCatalogEntry(Base):
    __tablename__ = "model_catalog_entries"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    org_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True, index=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)
    hosting_mode: Mapped[str] = mapped_column(_hosting_mode, nullable=False)
    primary_region: Mapped[str] = mapped_column(Text, nullable=False)
    jurisdiction: Mapped[str] = mapped_column(Text, nullable=False)
    cross_border_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    data_handling_terms: Mapped[str] = mapped_column(_data_handling, nullable=False)
    classification_state: Mapped[str] = mapped_column(_classification, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    valid_from: Mapped[date] = mapped_column(Date, nullable=False)
    valid_to: Mapped[date | None] = mapped_column(Date)
    digest: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ModelCatalogAlias(Base):
    __tablename__ = "model_catalog_aliases"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    org_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    catalog_entry_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ModelDeployment(TenantScoped, Base):
    __tablename__ = "model_deployments"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        UniqueConstraint("org_id", "project_id", "id"),
        ForeignKeyConstraint(
            ["org_id", "project_id"],
            ["projects.org_id", "projects.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    provider: Mapped[str] = mapped_column(_router_provider, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    endpoint: Mapped[str] = mapped_column(Text, nullable=False)
    credential_ref: Mapped[str] = mapped_column(Text, nullable=False)
    region: Mapped[str] = mapped_column(Text, nullable=False)
    jurisdiction: Mapped[str] = mapped_column(Text, nullable=False)
    capabilities: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    rpm: Mapped[int | None] = mapped_column(Integer)
    tpm: Mapped[int | None] = mapped_column(Integer)
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=60000)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    input_price_micros_per_m: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    output_price_micros_per_m: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    max_concurrency: Mapped[int | None] = mapped_column(Integer)
    daily_budget_micros: Mapped[int | None] = mapped_column(BigInteger)
    cooldown_failure_threshold: Mapped[int | None] = mapped_column(Integer)
    cooldown_initial_ms: Mapped[int | None] = mapped_column(Integer)
    cooldown_max_ms: Mapped[int | None] = mapped_column(Integer)
    data_classes: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ModelRoute(TenantScoped, Base):
    __tablename__ = "model_routes"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        UniqueConstraint("org_id", "project_id", "id"),
        ForeignKeyConstraint(
            ["org_id", "project_id"],
            ["projects.org_id", "projects.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "agent_id"],
            ["agents.org_id", "agents.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "agent_id", "agent_version_id"],
            ["agent_versions.org_id", "agent_versions.agent_id", "agent_versions.id"],
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    agent_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    agent_version_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    environment: Mapped[str] = mapped_column(_lifecycle, nullable=False)
    alias: Mapped[str] = mapped_column(Text, nullable=False)
    strategy: Mapped[str] = mapped_column(_router_strategy, nullable=False)
    enforcement: Mapped[str] = mapped_column(_enforcement, nullable=False)
    permitted_regions: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    data_classes: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    fallback_before_first_byte: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    response_cache_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    response_cache_ttl_seconds: Mapped[int | None] = mapped_column(Integer)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ModelRouteTarget(TenantScoped, Base):
    __tablename__ = "model_route_targets"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        UniqueConstraint("org_id", "route_id", "deployment_id"),
        UniqueConstraint("org_id", "route_id", "position"),
        ForeignKeyConstraint(
            ["org_id", "route_id"],
            ["model_routes.org_id", "model_routes.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "deployment_id"],
            ["model_deployments.org_id", "model_deployments.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id", "route_id"],
            ["model_routes.org_id", "model_routes.project_id", "model_routes.id"],
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["org_id", "project_id", "deployment_id"],
            ["model_deployments.org_id", "model_deployments.project_id", "model_deployments.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    route_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    deployment_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RouterConfigSnapshot(TenantScoped, Base):
    __tablename__ = "router_config_snapshots"
    __table_args__ = (
        UniqueConstraint("org_id", "id"),
        ForeignKeyConstraint(
            ["org_id", "project_id"],
            ["projects.org_id", "projects.id"],
            ondelete="CASCADE",
        ),
    )

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    project_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    config_bytes: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    config_digest: Mapped[str] = mapped_column(Text, nullable=False)
    rules_digest: Mapped[str] = mapped_column(Text, nullable=False)
    signature: Mapped[str] = mapped_column(Text, nullable=False)
    key_id: Mapped[str] = mapped_column(Text, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(_router_snapshot_status, nullable=False)
    compiled_by: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class RouterSigningKey(TenantScoped, Base):
    __tablename__ = "router_signing_keys"

    org_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    key_id: Mapped[str] = mapped_column(Text, primary_key=True)
    algorithm: Mapped[str] = mapped_column(Text, nullable=False, default="ES256")
    public_key_pem: Mapped[str] = mapped_column(Text, nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GatewayRequestLog(TenantScoped, Base):
    __tablename__ = "gateway_request_logs"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    agent_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    agent_version_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    engagement_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    model_provider: Mapped[str] = mapped_column(Text, nullable=False)
    model_id: Mapped[str] = mapped_column(Text, nullable=False)
    region_used: Mapped[str | None] = mapped_column(Text)
    virtual_key_ref: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    policy_decision_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    log_digest: Mapped[str] = mapped_column(Text, nullable=False)
    logged_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
