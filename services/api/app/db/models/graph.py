"""Models for migration 0004 — the Agent Graph and the discovery pipeline.

Mirrors ``0004_graph.py``. Thin by rule (AGENTS.md).

Traversal is recursive CTEs in ``domains/graph/repository.py``, so these models are used
for writes and single-node reads rather than for walking the graph. A walk expressed as
ORM navigation would emit one query per hop.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped

_graph_node_kind = ENUM(
    "agent",
    "model",
    "prompt",
    "tool",
    "mcp_server",
    "data_class",
    "data_source",
    "vector_store",
    "dataset",
    "guardrail",
    "team",
    "person",
    "region",
    "framework",
    "customer",
    "engagement",
    name="graph_node_kind",
    create_type=False,
)
_graph_edge_kind = ENUM(
    "uses_model",
    "uses_prompt",
    "invokes_tool",
    "connects_mcp",
    "reads_data",
    "writes_data",
    "delegates_to",
    "owned_by",
    "accountable_for",
    "deployed_in",
    "processes_in",
    "accredited_under",
    "in_scope_for",
    "guarded_by",
    "depends_on",
    name="graph_edge_kind",
    create_type=False,
)
_graph_source = ENUM("declared", "observed", "inferred", name="graph_source", create_type=False)
_discovery_kind = ENUM(
    "otel",
    "k8s",
    "egress",
    "mcp_scan",
    "provider_keys",
    "vcs",
    "manual",
    name="discovery_kind",
    create_type=False,
)
_discovery_state = ENUM(
    "new", "confirmed", "dismissed", "merged", name="discovery_state", create_type=False
)


class GraphNode(Base, TenantScoped):
    """A thing in the estate.

    ``node_key`` is a stable natural key within ``(org_id, kind)``, which is what makes
    a rebuild idempotent and lets a descriptor and a telemetry span converge on the same
    node rather than creating two.
    """

    __tablename__ = "graph_nodes"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    kind: Mapped[str] = mapped_column(_graph_node_kind, nullable=False)
    node_key: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)

    entity_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")

    is_declared: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    is_observed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GraphEdge(Base, TenantScoped):
    """A relationship, with its provenance.

    ``source`` participates in the unique constraint so a declared edge and an observed
    edge of the same shape coexist. The gap between them is the most valuable data in
    the product: declared-and-not-observed is documentation nobody honours, and
    observed-and-not-declared is an agent doing something its owner never wrote down.
    """

    __tablename__ = "graph_edges"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    src_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("graph_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )
    dst_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("graph_nodes.id", ondelete="CASCADE"),
        nullable=False,
    )

    kind: Mapped[str] = mapped_column(_graph_edge_kind, nullable=False)
    source: Mapped[str] = mapped_column(_graph_source, nullable=False)

    confidence: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, server_default="1.00"
    )

    agent_version_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    observation_count: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")

    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DiscoverySource(Base, TenantScoped):
    """Where we look for agents nobody registered.

    Credentials are never stored here. ``secret_ref`` resolves through
    ``app/providers/secrets.py``, because in BYOC the secrets backend differs per
    customer.
    """

    __tablename__ = "discovery_sources"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    kind: Mapped[str] = mapped_column(_discovery_kind, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)

    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    secret_ref: Mapped[str | None] = mapped_column(Text)

    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(Text)
    last_error: Mapped[str | None] = mapped_column(Text)
    findings_last_run: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class DiscoveryFinding(Base, TenantScoped):
    """A candidate agent, keyed in the same space as ``GraphNode`` so a confirmed
    finding can be promoted without re-keying it."""

    __tablename__ = "discovery_findings"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    source_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("discovery_sources.id", ondelete="CASCADE"),
        nullable=False,
    )

    candidate_kind: Mapped[str] = mapped_column(_graph_node_kind, nullable=False)
    candidate_key: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)

    signals: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    confidence: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, server_default="0.50"
    )

    state: Mapped[str] = mapped_column(_discovery_state, nullable=False)

    agent_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_by: Mapped[str | None] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)
