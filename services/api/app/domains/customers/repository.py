"""Customer persistence. SQL only — no business logic, no HTTP concerns.

Every function takes ``org_id`` explicitly rather than reading it from the session.
Row-level security already scopes the connection, but an explicit predicate means a
misconfigured policy degrades to returning nothing instead of returning everything.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, insert, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.company import (
    Customer,
    CustomerContact,
    CustomerFramework,
    Framework,
    FrameworkControl,
)

# ----------------------------------------------------------------------
# Customers
# ----------------------------------------------------------------------


async def insert_customer(session: AsyncSession, org_id: UUID, values: dict[str, Any]) -> Customer:
    stmt = insert(Customer).values(org_id=org_id, **values).returning(Customer)
    return (await session.execute(stmt)).scalar_one()


async def get_customer(session: AsyncSession, org_id: UUID, customer_id: UUID) -> Customer | None:
    stmt = select(Customer).where(Customer.id == customer_id, Customer.org_id == org_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_customer_by_slug(session: AsyncSession, org_id: UUID, slug: str) -> Customer | None:
    stmt = select(Customer).where(Customer.slug == slug, Customer.org_id == org_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def update_customer(
    session: AsyncSession, org_id: UUID, customer_id: UUID, values: dict[str, Any]
) -> Customer | None:
    if not values:
        return await get_customer(session, org_id, customer_id)
    stmt = (
        update(Customer)
        .where(Customer.id == customer_id, Customer.org_id == org_id)
        .values(**values)
        .returning(Customer)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_customers(
    session: AsyncSession,
    org_id: UUID,
    *,
    statuses: list[str] | None = None,
    sectors: list[str] | None = None,
    criticalities: list[str] | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Customer]:
    stmt = select(Customer).where(Customer.org_id == org_id)

    if statuses:
        stmt = stmt.where(Customer.status.in_(statuses))
    if sectors:
        stmt = stmt.where(Customer.sector.in_(sectors))
    if criticalities:
        stmt = stmt.where(Customer.criticality.in_(criticalities))
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Customer.display_name).like(pattern),
                func.lower(Customer.legal_name).like(pattern),
                Customer.slug.like(pattern),
            )
        )

    stmt = stmt.order_by(Customer.display_name).limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars())


async def count_customers(
    session: AsyncSession,
    org_id: UUID,
    *,
    statuses: list[str] | None = None,
    sectors: list[str] | None = None,
    criticalities: list[str] | None = None,
    search: str | None = None,
) -> int:
    stmt = select(func.count()).select_from(Customer).where(Customer.org_id == org_id)
    if statuses:
        stmt = stmt.where(Customer.status.in_(statuses))
    if sectors:
        stmt = stmt.where(Customer.sector.in_(sectors))
    if criticalities:
        stmt = stmt.where(Customer.criticality.in_(criticalities))
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Customer.display_name).like(pattern),
                func.lower(Customer.legal_name).like(pattern),
                Customer.slug.like(pattern),
            )
        )
    return (await session.execute(stmt)).scalar_one()


async def fetch_rollups(
    session: AsyncSession, org_id: UUID, customer_ids: list[UUID]
) -> dict[UUID, dict[str, int]]:
    """Engagement, agent, framework and drift counts for a page of customers.

    One query for the whole page rather than four per row. ``drift`` counts agents
    delivered at a version the client never approved, which is the figure the list view
    exists to surface.
    """
    if not customer_ids:
        return {}

    stmt = text("""
        SELECT
            c.id AS customer_id,
            count(DISTINCT e.id)  AS engagement_count,
            count(DISTINCT ea.agent_id) AS agent_count,
            count(DISTINCT ea.agent_id) FILTER (
                WHERE ea.deployed_version_id IS DISTINCT FROM ea.accredited_version_id
            ) AS drift_count,
            count(DISTINCT cf.framework_id) AS framework_count
        FROM customers c
        LEFT JOIN engagements e
               ON e.customer_id = c.id AND e.state <> 'terminated'
        LEFT JOIN engagement_agents ea
               ON ea.engagement_id = e.id AND ea.removed_at IS NULL
        LEFT JOIN customer_frameworks cf
               ON cf.customer_id = c.id
        WHERE c.org_id = :org_id AND c.id = ANY(:customer_ids)
        GROUP BY c.id
    """)
    rows = await session.execute(
        stmt, {"org_id": str(org_id), "customer_ids": [str(i) for i in customer_ids]}
    )
    return {
        row.customer_id: {
            "engagement_count": row.engagement_count,
            "agent_count": row.agent_count,
            "framework_count": row.framework_count,
            "drift_count": row.drift_count,
        }
        for row in rows
    }


# ----------------------------------------------------------------------
# Contacts
# ----------------------------------------------------------------------


async def close_contact(
    session: AsyncSession, org_id: UUID, customer_id: UUID, role: str, at: datetime
) -> None:
    """End the current holder's validity window. Never deletes: who reviewed at the
    time of an approval has to remain answerable afterwards."""
    stmt = (
        update(CustomerContact)
        .where(
            CustomerContact.org_id == org_id,
            CustomerContact.customer_id == customer_id,
            CustomerContact.role == role,
            CustomerContact.valid_to.is_(None),
        )
        .values(valid_to=at)
    )
    await session.execute(stmt)


async def insert_contact(
    session: AsyncSession, org_id: UUID, customer_id: UUID, values: dict[str, Any]
) -> CustomerContact:
    stmt = (
        insert(CustomerContact)
        .values(org_id=org_id, customer_id=customer_id, **values)
        .returning(CustomerContact)
    )
    return (await session.execute(stmt)).scalar_one()


async def list_current_contacts(
    session: AsyncSession, org_id: UUID, customer_id: UUID
) -> list[CustomerContact]:
    stmt = (
        select(CustomerContact)
        .where(
            CustomerContact.org_id == org_id,
            CustomerContact.customer_id == customer_id,
            CustomerContact.valid_to.is_(None),
        )
        .order_by(CustomerContact.role)
    )
    return list((await session.execute(stmt)).scalars())


# ----------------------------------------------------------------------
# Frameworks
# ----------------------------------------------------------------------


async def get_framework(
    session: AsyncSession, org_id: UUID, framework_id: UUID
) -> Framework | None:
    """Visible when we shipped it (``org_id IS NULL``) or this tenant authored it."""
    stmt = select(Framework).where(
        Framework.id == framework_id,
        or_(Framework.org_id.is_(None), Framework.org_id == org_id),
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_frameworks(
    session: AsyncSession, org_id: UUID, *, kinds: list[str] | None = None
) -> list[tuple[Framework, int]]:
    """Every framework visible to this tenant, with its control count.

    Sector and jurisdiction matching is deliberately not done here. The suggestion
    logic needs to know *which* criterion matched in order to state a reason and a
    confidence, and a SQL predicate that has already filtered the rows cannot tell it
    that. So the service reads the whole (small) list and matches in Python.
    """
    control_count = (
        select(func.count())
        .select_from(FrameworkControl)
        .where(FrameworkControl.framework_id == Framework.id)
        .correlate(Framework)
        .scalar_subquery()
    )

    stmt = select(Framework, control_count.label("control_count")).where(
        or_(Framework.org_id.is_(None), Framework.org_id == org_id)
    )
    if kinds:
        stmt = stmt.where(Framework.kind.in_(kinds))

    stmt = stmt.order_by(Framework.kind, Framework.name)
    return [(row[0], row[1]) for row in (await session.execute(stmt)).all()]


async def insert_requirement(
    session: AsyncSession, org_id: UUID, customer_id: UUID, values: dict[str, Any]
) -> CustomerFramework:
    stmt = (
        insert(CustomerFramework)
        .values(org_id=org_id, customer_id=customer_id, **values)
        .returning(CustomerFramework)
    )
    return (await session.execute(stmt)).scalar_one()


async def delete_requirement(
    session: AsyncSession, org_id: UUID, customer_id: UUID, framework_id: UUID
) -> int:
    """Returns the number of rows removed, via RETURNING rather than ``rowcount``.

    ``rowcount`` is driver-dependent and typed loosely; RETURNING is neither.
    """
    stmt = (
        delete(CustomerFramework)
        .where(
            CustomerFramework.org_id == org_id,
            CustomerFramework.customer_id == customer_id,
            CustomerFramework.framework_id == framework_id,
        )
        .returning(CustomerFramework.id)
    )
    return len((await session.execute(stmt)).scalars().all())


async def list_requirements(
    session: AsyncSession, org_id: UUID, customer_id: UUID
) -> list[tuple[CustomerFramework, Framework, int]]:
    control_count = (
        select(func.count())
        .select_from(FrameworkControl)
        .where(FrameworkControl.framework_id == Framework.id)
        .correlate(Framework)
        .scalar_subquery()
    )
    stmt = (
        select(CustomerFramework, Framework, control_count.label("control_count"))
        .join(Framework, Framework.id == CustomerFramework.framework_id)
        .where(
            CustomerFramework.org_id == org_id,
            CustomerFramework.customer_id == customer_id,
        )
        .order_by(CustomerFramework.level, Framework.name)
    )
    return [(r[0], r[1], r[2]) for r in (await session.execute(stmt)).all()]


async def requirement_exists(
    session: AsyncSession, org_id: UUID, customer_id: UUID, framework_id: UUID
) -> bool:
    stmt = (
        select(func.count())
        .select_from(CustomerFramework)
        .where(
            CustomerFramework.org_id == org_id,
            CustomerFramework.customer_id == customer_id,
            CustomerFramework.framework_id == framework_id,
        )
    )
    return (await session.execute(stmt)).scalar_one() > 0


# ----------------------------------------------------------------------
# Readiness
# ----------------------------------------------------------------------


async def fetch_control_coverage(
    session: AsyncSession, org_id: UUID, customer_id: UUID
) -> list[Any]:
    """Every control this customer demands, with how well the platform answers it.

    Written as one statement rather than a loop over frameworks because a tier-1 client
    can require four frameworks totalling several hundred controls, and the readiness
    screen must render in one round trip.

    ``scoped_controls`` being empty means the whole framework, which is why the scope
    predicate is an OR rather than a join.
    """
    stmt = text("""
        WITH scoped AS (
            SELECT
                cf.framework_id,
                cf.level,
                f.slug   AS framework_slug,
                f.name   AS framework_name,
                fc.id    AS control_id,
                fc.control_ref,
                fc.title,
                fc.answer_mode
            FROM customer_frameworks cf
            JOIN frameworks f ON f.id = cf.framework_id
            JOIN framework_controls fc ON fc.framework_id = cf.framework_id
            WHERE cf.org_id = :org_id
              AND cf.customer_id = :customer_id
              AND (
                    cardinality(cf.scoped_controls) = 0
                 OR fc.control_ref = ANY(cf.scoped_controls)
              )
        )
        SELECT
            s.framework_id,
            s.framework_slug,
            s.framework_name,
            s.level,
            s.control_id,
            s.control_ref,
            s.title,
            s.answer_mode,
            count(cm.id) AS mapping_count,
            count(cm.id) FILTER (WHERE cm.strength = 'satisfies') AS full_count
        FROM scoped s
        LEFT JOIN control_mappings cm
               ON cm.control_id = s.control_id
              AND (cm.org_id IS NULL OR cm.org_id = :org_id)
        GROUP BY s.framework_id, s.framework_slug, s.framework_name, s.level,
                 s.control_id, s.control_ref, s.title, s.answer_mode
        ORDER BY s.framework_name, s.control_ref
    """)
    result = await session.execute(stmt, {"org_id": str(org_id), "customer_id": str(customer_id)})
    return list(result.all())


async def fetch_framework_control_counts(
    session: AsyncSession, framework_ids: list[UUID]
) -> dict[UUID, int]:
    if not framework_ids:
        return {}
    stmt = (
        select(FrameworkControl.framework_id, func.count().label("n"))
        .where(FrameworkControl.framework_id.in_(framework_ids))
        .group_by(FrameworkControl.framework_id)
    )
    return {row[0]: row[1] for row in (await session.execute(stmt)).all()}


__all__ = [
    "close_contact",
    "count_customers",
    "delete_requirement",
    "fetch_control_coverage",
    "fetch_framework_control_counts",
    "fetch_rollups",
    "get_customer",
    "get_customer_by_slug",
    "get_framework",
    "insert_contact",
    "insert_customer",
    "insert_requirement",
    "list_current_contacts",
    "list_customers",
    "list_frameworks",
    "list_requirements",
    "requirement_exists",
    "update_customer",
]
