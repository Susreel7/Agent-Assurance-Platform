"""Engagement persistence. SQL only — no business logic, no HTTP concerns.

``org_id`` is passed explicitly into every function even though row-level security
already scopes the connection. A misconfigured policy then returns nothing rather than
returning another tenant's deliveries.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Row, delete, func, insert, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.company import (
    Customer,
    Engagement,
    EngagementAgent,
    EngagementServiceLevel,
)
from app.db.models.registry import Agent, AgentVersion

# ----------------------------------------------------------------------
# Engagements
# ----------------------------------------------------------------------


async def insert_engagement(
    session: AsyncSession, org_id: UUID, values: dict[str, Any]
) -> Engagement:
    stmt = insert(Engagement).values(org_id=org_id, **values).returning(Engagement)
    return (await session.execute(stmt)).scalar_one()


async def get_engagement(
    session: AsyncSession, org_id: UUID, engagement_id: UUID
) -> Engagement | None:
    stmt = select(Engagement).where(Engagement.id == engagement_id, Engagement.org_id == org_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_engagement_by_slug(
    session: AsyncSession, org_id: UUID, customer_id: UUID, slug: str
) -> Engagement | None:
    stmt = select(Engagement).where(
        Engagement.org_id == org_id,
        Engagement.customer_id == customer_id,
        Engagement.slug == slug,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def update_engagement(
    session: AsyncSession, org_id: UUID, engagement_id: UUID, values: dict[str, Any]
) -> Engagement | None:
    if not values:
        return await get_engagement(session, org_id, engagement_id)
    stmt = (
        update(Engagement)
        .where(Engagement.id == engagement_id, Engagement.org_id == org_id)
        .values(**values)
        .returning(Engagement)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


def _engagement_filters(
    stmt: Any,
    *,
    customer_id: UUID | None,
    states: list[str] | None,
    search: str | None,
) -> Any:
    if customer_id is not None:
        stmt = stmt.where(Engagement.customer_id == customer_id)
    if states:
        stmt = stmt.where(Engagement.state.in_(states))
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(func.lower(Engagement.name).like(pattern), Engagement.slug.like(pattern))
        )
    return stmt


async def list_engagements(
    session: AsyncSession,
    org_id: UUID,
    *,
    customer_id: UUID | None = None,
    states: list[str] | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Row[Any]]:
    """Engagements joined to their customer, so a list row can name the client."""
    stmt = (
        select(
            Engagement,
            Customer.display_name.label("customer_display_name"),
            Customer.slug.label("customer_slug"),
        )
        .join(Customer, Customer.id == Engagement.customer_id)
        .where(Engagement.org_id == org_id)
    )
    stmt = _engagement_filters(stmt, customer_id=customer_id, states=states, search=search)
    stmt = stmt.order_by(Customer.display_name, Engagement.name).limit(limit).offset(offset)
    return list((await session.execute(stmt)).all())


async def count_engagements(
    session: AsyncSession,
    org_id: UUID,
    *,
    customer_id: UUID | None = None,
    states: list[str] | None = None,
    search: str | None = None,
) -> int:
    stmt = select(func.count()).select_from(Engagement).where(Engagement.org_id == org_id)
    stmt = _engagement_filters(stmt, customer_id=customer_id, states=states, search=search)
    return int((await session.execute(stmt)).scalar_one())


async def fetch_customer_names(
    session: AsyncSession, org_id: UUID, customer_ids: list[UUID]
) -> dict[UUID, tuple[str, str]]:
    """Display name and slug per customer. The slug is half of the portal link."""
    if not customer_ids:
        return {}
    stmt = select(Customer.id, Customer.display_name, Customer.slug).where(
        Customer.org_id == org_id, Customer.id.in_(customer_ids)
    )
    return {row.id: (row.display_name, row.slug) for row in (await session.execute(stmt)).all()}


async def fetch_engagement_rollups(
    session: AsyncSession, org_id: UUID, engagement_ids: list[UUID]
) -> dict[UUID, dict[str, int]]:
    """Scope and drift counts per engagement, in two queries rather than 2N.

    The list screen shows these for every row; resolving them per row is the difference
    between one round trip and a hundred.
    """
    if not engagement_ids:
        return {}

    drifting = func.count().filter(
        EngagementAgent.deployed_version_id.is_not(None),
        EngagementAgent.accredited_version_id.is_not(None),
        EngagementAgent.deployed_version_id != EngagementAgent.accredited_version_id,
    )
    scope_stmt = (
        select(
            EngagementAgent.engagement_id,
            func.count().label("agents_in_scope"),
            drifting.label("agents_drifting"),
        )
        .where(
            EngagementAgent.org_id == org_id,
            EngagementAgent.engagement_id.in_(engagement_ids),
            EngagementAgent.removed_at.is_(None),
        )
        .group_by(EngagementAgent.engagement_id)
    )

    slo_stmt = (
        select(
            EngagementServiceLevel.engagement_id,
            func.count().label("slo_count"),
        )
        .where(
            EngagementServiceLevel.org_id == org_id,
            EngagementServiceLevel.engagement_id.in_(engagement_ids),
        )
        .group_by(EngagementServiceLevel.engagement_id)
    )

    rollups: dict[UUID, dict[str, int]] = {
        eid: {"agents_in_scope": 0, "agents_drifting": 0, "slo_count": 0} for eid in engagement_ids
    }
    for scope_row in (await session.execute(scope_stmt)).all():
        rollups[scope_row.engagement_id]["agents_in_scope"] = scope_row.agents_in_scope
        rollups[scope_row.engagement_id]["agents_drifting"] = scope_row.agents_drifting
    for slo_row in (await session.execute(slo_stmt)).all():
        rollups[slo_row.engagement_id]["slo_count"] = slo_row.slo_count
    return rollups


# ----------------------------------------------------------------------
# Service levels
# ----------------------------------------------------------------------


async def list_service_levels(
    session: AsyncSession, org_id: UUID, engagement_id: UUID
) -> list[EngagementServiceLevel]:
    stmt = (
        select(EngagementServiceLevel)
        .where(
            EngagementServiceLevel.org_id == org_id,
            EngagementServiceLevel.engagement_id == engagement_id,
        )
        .order_by(EngagementServiceLevel.kind, EngagementServiceLevel.measurement_window)
    )
    return list((await session.execute(stmt)).scalars())


async def upsert_service_level(
    session: AsyncSession, org_id: UUID, engagement_id: UUID, values: dict[str, Any]
) -> EngagementServiceLevel:
    """Insert, or replace the target and penalty of an existing commitment.

    Keyed on ``(engagement_id, kind, measurement_window)`` to match the unique
    constraint: renewing a contract with a tighter availability target should revise the
    row, not create a second commitment that the SLA engine would then evaluate twice.
    """
    stmt = (
        pg_insert(EngagementServiceLevel)
        .values(org_id=org_id, engagement_id=engagement_id, **values)
        .on_conflict_do_update(
            index_elements=["engagement_id", "kind", "measurement_window"],
            set_={
                "target": values["target"],
                "unit": values.get("unit"),
                "penalty_basis": values["penalty_basis"],
                "penalty_detail": values.get("penalty_detail"),
            },
        )
        .returning(EngagementServiceLevel)
    )
    return (await session.execute(stmt)).scalar_one()


async def delete_service_level(
    session: AsyncSession, org_id: UUID, engagement_id: UUID, slo_id: UUID
) -> int:
    stmt = (
        delete(EngagementServiceLevel)
        .where(
            EngagementServiceLevel.org_id == org_id,
            EngagementServiceLevel.engagement_id == engagement_id,
            EngagementServiceLevel.id == slo_id,
        )
        .returning(EngagementServiceLevel.id)
    )
    return len((await session.execute(stmt)).all())


# ----------------------------------------------------------------------
# Agents in scope
# ----------------------------------------------------------------------

_Accredited = AgentVersion.__table__.alias("accredited_version")
_Deployed = AgentVersion.__table__.alias("deployed_version")


def _scope_select() -> Any:
    """Scoped agents with both version labels resolved in one pass.

    Two aliases of ``agent_versions`` because the approved version and the running
    version are different rows of the same table, and the entire point of the screen is
    to show them side by side.
    """
    return (
        select(
            EngagementAgent.id,
            EngagementAgent.engagement_id,
            EngagementAgent.agent_id,
            EngagementAgent.uptake,
            EngagementAgent.in_scope_since,
            EngagementAgent.accredited_version_id,
            EngagementAgent.deployed_version_id,
            Agent.urn.label("agent_urn"),
            Agent.display_name.label("agent_display_name"),
            _Accredited.c.semver.label("accredited_semver"),
            _Accredited.c.published_at.label("accredited_at"),
            _Deployed.c.semver.label("deployed_semver"),
            _Deployed.c.published_at.label("deployed_at"),
        )
        .join(Agent, Agent.id == EngagementAgent.agent_id)
        .outerjoin(_Accredited, _Accredited.c.id == EngagementAgent.accredited_version_id)
        .outerjoin(_Deployed, _Deployed.c.id == EngagementAgent.deployed_version_id)
    )


async def list_scoped_agents(
    session: AsyncSession, org_id: UUID, engagement_id: UUID
) -> list[Row[Any]]:
    stmt = (
        _scope_select()
        .where(
            EngagementAgent.org_id == org_id,
            EngagementAgent.engagement_id == engagement_id,
            EngagementAgent.removed_at.is_(None),
        )
        .order_by(Agent.display_name)
    )
    return list((await session.execute(stmt)).all())


async def get_scoped_agent(
    session: AsyncSession, org_id: UUID, engagement_id: UUID, agent_id: UUID
) -> EngagementAgent | None:
    stmt = select(EngagementAgent).where(
        EngagementAgent.org_id == org_id,
        EngagementAgent.engagement_id == engagement_id,
        EngagementAgent.agent_id == agent_id,
        EngagementAgent.removed_at.is_(None),
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def insert_scoped_agent(
    session: AsyncSession, org_id: UUID, engagement_id: UUID, values: dict[str, Any]
) -> EngagementAgent:
    stmt = (
        insert(EngagementAgent)
        .values(org_id=org_id, engagement_id=engagement_id, **values)
        .returning(EngagementAgent)
    )
    return (await session.execute(stmt)).scalar_one()


async def update_scoped_agent(
    session: AsyncSession,
    org_id: UUID,
    engagement_id: UUID,
    agent_id: UUID,
    values: dict[str, Any],
) -> EngagementAgent | None:
    if not values:
        return await get_scoped_agent(session, org_id, engagement_id, agent_id)
    stmt = (
        update(EngagementAgent)
        .where(
            EngagementAgent.org_id == org_id,
            EngagementAgent.engagement_id == engagement_id,
            EngagementAgent.agent_id == agent_id,
            EngagementAgent.removed_at.is_(None),
        )
        .values(**values)
        .returning(EngagementAgent)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def remove_scoped_agent(
    session: AsyncSession,
    org_id: UUID,
    engagement_id: UUID,
    agent_id: UUID,
    removed_at: datetime,
) -> int:
    """Close the scope window rather than deleting the row.

    An accreditation issued last quarter refers to this row. Deleting it would make a
    historical pack unexplainable, so removal is a timestamp and the partial unique
    index permits the agent to be scoped in again later.
    """
    stmt = (
        update(EngagementAgent)
        .where(
            EngagementAgent.org_id == org_id,
            EngagementAgent.engagement_id == engagement_id,
            EngagementAgent.agent_id == agent_id,
            EngagementAgent.removed_at.is_(None),
        )
        .values(removed_at=removed_at)
        .returning(EngagementAgent.id)
    )
    return len((await session.execute(stmt)).all())


async def fetch_drift_rows(
    session: AsyncSession,
    org_id: UUID,
    *,
    customer_id: UUID | None = None,
    engagement_id: UUID | None = None,
    include_clean: bool = False,
) -> list[Row[Any]]:
    """Every scoped agent whose running version differs from the approved one.

    Backed by ``engagement_agents_drift_idx``, a partial index over exactly this
    predicate, so the estate-wide sweep stays cheap as the number of deliveries grows.
    """
    stmt = (
        _scope_select()
        .add_columns(
            Engagement.name.label("engagement_name"),
            Customer.id.label("customer_id"),
            Customer.display_name.label("customer_display_name"),
            Customer.criticality.label("customer_criticality"),
        )
        .join(Engagement, Engagement.id == EngagementAgent.engagement_id)
        .join(Customer, Customer.id == Engagement.customer_id)
        .where(
            EngagementAgent.org_id == org_id,
            EngagementAgent.removed_at.is_(None),
            # A terminated delivery serving an old version is not a live risk.
            Engagement.state.in_(["draft", "active", "suspended"]),
        )
    )

    if not include_clean:
        stmt = stmt.where(
            EngagementAgent.deployed_version_id.is_distinct_from(
                EngagementAgent.accredited_version_id
            )
        )
    if customer_id is not None:
        stmt = stmt.where(Engagement.customer_id == customer_id)
    if engagement_id is not None:
        stmt = stmt.where(EngagementAgent.engagement_id == engagement_id)

    stmt = stmt.order_by(Customer.criticality, Customer.display_name, Agent.display_name)
    return list((await session.execute(stmt)).all())


async def count_scoped_agents(
    session: AsyncSession,
    org_id: UUID,
    *,
    customer_id: UUID | None = None,
    engagement_id: UUID | None = None,
) -> int:
    stmt = (
        select(func.count())
        .select_from(EngagementAgent)
        .join(Engagement, Engagement.id == EngagementAgent.engagement_id)
        .where(
            EngagementAgent.org_id == org_id,
            EngagementAgent.removed_at.is_(None),
            Engagement.state.in_(["draft", "active", "suspended"]),
        )
    )
    if customer_id is not None:
        stmt = stmt.where(Engagement.customer_id == customer_id)
    if engagement_id is not None:
        stmt = stmt.where(EngagementAgent.engagement_id == engagement_id)
    return (await session.execute(stmt)).scalar_one()


async def version_sequence(session: AsyncSession, org_id: UUID, agent_id: UUID) -> list[UUID]:
    """Published version ids for one agent, oldest first.

    Used to turn "approved 2.1, running 2.4" into "two versions behind", which is the
    difference between a fact and something an operator can prioritise.
    """
    stmt = (
        select(AgentVersion.id)
        .where(AgentVersion.org_id == org_id, AgentVersion.agent_id == agent_id)
        .order_by(AgentVersion.published_at)
    )
    return list((await session.execute(stmt)).scalars())
