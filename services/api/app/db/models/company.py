"""Models for migration 0002 — the company model.

Mirrors ``0002_company_model.py``. Enum columns are declared as ``String`` with
``native_enum=False`` suppressed in favour of the real Postgres type name, so that
SQLAlchemy emits the enum label and the database performs the validation. The Python
enums used at the boundary live in each domain's ``schemas.py``.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import ARRAY, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import ENUM
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped
from app.db.models.evidence import _evidence_kind

# Enum types are created by the migration, so every reference must declare
# create_type=False. Forgetting this makes Alembic try to create an existing type and
# fail on the second table that uses it.
_customer_status = ENUM(
    "prospect",
    "active",
    "suspended",
    "offboarding",
    "churned",
    name="customer_status",
    create_type=False,
)
_criticality_tier = ENUM("tier_1", "tier_2", "tier_3", name="criticality_tier", create_type=False)
_engagement_state = ENUM(
    "draft", "active", "suspended", "terminated", name="engagement_state", create_type=False
)
_contact_role = ENUM(
    "security_reviewer",
    "data_protection",
    "business_owner",
    "procurement",
    "technical",
    "executive_sponsor",
    name="contact_role",
    create_type=False,
)
_framework_kind = ENUM(
    "standard",
    "regulation",
    "certification",
    "questionnaire",
    "internal_policy",
    name="framework_kind",
    create_type=False,
)
_requirement_level = ENUM(
    "mandatory", "expected", "informational", name="requirement_level", create_type=False
)
_mapping_strength = ENUM(
    "satisfies", "partially_satisfies", "supports", name="mapping_strength", create_type=False
)
_version_uptake = ENUM(
    "pinned", "auto_patch", "auto_minor", "auto_all", name="version_uptake", create_type=False
)


class Customer(Base, TenantScoped):
    __tablename__ = "customers"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    slug: Mapped[str] = mapped_column(Text, nullable=False)
    legal_name: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[str] = mapped_column(_customer_status, nullable=False)
    sector: Mapped[str | None] = mapped_column(Text)

    home_jurisdiction: Mapped[str | None] = mapped_column(Text)
    operating_jurisdictions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )

    criticality: Mapped[str] = mapped_column(_criticality_tier, nullable=False)

    external_ref: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CustomerContact(Base, TenantScoped):
    """The only table holding personal data, kept separable so it can be purged alone."""

    __tablename__ = "customer_contacts"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    customer_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )

    role: Mapped[str] = mapped_column(_contact_role, nullable=False)
    principal_id: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(Text)

    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    valid_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Framework(Base):
    """Reference data. ``org_id`` NULL means we ship it; set means a tenant authored it,
    which in practice is a specific client's own questionnaire.

    Not ``TenantScoped``: the mixin implies a non-null org and a plain isolation policy,
    and this table has neither.
    """

    __tablename__ = "frameworks"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    org_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(_framework_kind, nullable=False)
    publisher: Mapped[str | None] = mapped_column(Text)
    version: Mapped[str | None] = mapped_column(Text)

    typical_sectors: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    jurisdictions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )

    source_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class FrameworkControl(Base):
    __tablename__ = "framework_controls"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    framework_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    org_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    control_ref: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    requirement: Mapped[str | None] = mapped_column(Text)

    section: Mapped[str | None] = mapped_column(Text)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    answer_mode: Mapped[str] = mapped_column(String, nullable=False, server_default="evidence")
    text_status: Mapped[str] = mapped_column(String, nullable=False, server_default="paraphrased")


class ControlMapping(Base):
    """Which of our evidence kinds answers which control, and how completely."""

    __tablename__ = "control_mappings"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    control_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("framework_controls.id", ondelete="CASCADE"),
        nullable=False,
    )
    org_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    evidence_kind: Mapped[str] = mapped_column(_evidence_kind, nullable=False)
    strength: Mapped[str] = mapped_column(_mapping_strength, nullable=False)
    producer: Mapped[str] = mapped_column(Text, nullable=False)
    narrative_template: Mapped[str | None] = mapped_column(Text)
    obligation_template_id: Mapped[str | None] = mapped_column(Text)
    required_polarity: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ObligationTemplate(Base):
    """Shipped mapping targets for gap analysis — paraphrased statements only."""

    __tablename__ = "obligation_templates"

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    org_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    category: Mapped[str] = mapped_column(Text, nullable=False)
    polarity: Mapped[str] = mapped_column(Text, nullable=False)
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    framework_hint: Mapped[str | None] = mapped_column(Text)


class CustomerFramework(Base, TenantScoped):
    __tablename__ = "customer_frameworks"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    customer_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )
    framework_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("frameworks.id", ondelete="RESTRICT"), nullable=False
    )

    level: Mapped[str] = mapped_column(_requirement_level, nullable=False)
    scoped_controls: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )

    required_since: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Engagement(Base, TenantScoped):
    __tablename__ = "engagements"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    customer_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False
    )

    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    state: Mapped[str] = mapped_column(_engagement_state, nullable=False)

    permitted_regions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    prohibited_regions: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )
    cross_border_transfer: Mapped[str] = mapped_column(
        String, nullable=False, server_default="prohibited"
    )
    permitted_data_classes: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default="{}"
    )

    contract_ref: Mapped[str | None] = mapped_column(Text)
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)

    delivery_lead: Mapped[str | None] = mapped_column(Text)
    customer_approver: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EngagementServiceLevel(Base, TenantScoped):
    __tablename__ = "engagement_service_levels"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    engagement_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )

    kind: Mapped[str] = mapped_column(Text, nullable=False)
    target: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    unit: Mapped[str | None] = mapped_column(Text)
    measurement_window: Mapped[str] = mapped_column(Text, nullable=False, server_default="monthly")

    penalty_basis: Mapped[str] = mapped_column(Text, nullable=False, server_default="none")
    penalty_detail: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EngagementAgent(Base, TenantScoped):
    """Which agents a client has in scope, and at which version *they* approved.

    ``deployed_version_id`` differing from ``accredited_version_id`` is accreditation
    drift: the client is being served something they have not signed off. That
    comparison is the most consequential query in the product.
    """

    __tablename__ = "engagement_agents"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    engagement_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("engagements.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"), nullable=False
    )

    accredited_version_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    deployed_version_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    uptake: Mapped[str] = mapped_column(_version_uptake, nullable=False)

    in_scope_since: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
