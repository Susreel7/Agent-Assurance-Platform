"""Portal persistence — every query is scoped by engagement_id."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.assurance import Accreditation, AccreditationPack
from app.db.models.company import Customer, Engagement, EngagementAgent


async def get_engagement_by_slug(
    session: AsyncSession, org_id: UUID, customer_slug: str, engagement_slug: str
) -> Engagement | None:
    """Resolve a portal link to exactly one engagement.

    Both slugs are required because an engagement slug is unique per *customer*, not per
    organisation — `engagements_slug_unique` is `(org_id, customer_id, slug)`. Matching
    on the engagement slug alone returned every client who had used the same name, which
    is not a near-miss: it is a query that cannot answer correctly, because picking one
    would show one client another's estate. It raised instead, and the portal was a 500
    for the entire seeded demo. See D-035.
    """
    stmt = (
        select(Engagement)
        .join(Customer, Customer.id == Engagement.customer_id)
        .where(
            Engagement.org_id == org_id,
            Customer.slug == customer_slug,
            Engagement.slug == engagement_slug,
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_engagement(
    session: AsyncSession, org_id: UUID, engagement_id: UUID
) -> Engagement | None:
    stmt = select(Engagement).where(
        Engagement.id == engagement_id,
        Engagement.org_id == org_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_engagement_agents(
    session: AsyncSession, org_id: UUID, engagement_id: UUID
) -> list[EngagementAgent]:
    stmt = select(EngagementAgent).where(
        EngagementAgent.org_id == org_id,
        EngagementAgent.engagement_id == engagement_id,
        EngagementAgent.removed_at.is_(None),
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_accreditations_for_engagement(
    session: AsyncSession, org_id: UUID, engagement_id: UUID
) -> list[Accreditation]:
    stmt = select(Accreditation).where(
        Accreditation.org_id == org_id,
        Accreditation.engagement_id == engagement_id,
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_current_packs(
    session: AsyncSession, org_id: UUID, accreditation_id: UUID
) -> list[AccreditationPack]:
    stmt = select(AccreditationPack).where(
        AccreditationPack.org_id == org_id,
        AccreditationPack.accreditation_id == accreditation_id,
        AccreditationPack.is_current.is_(True),
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_pack_for_engagement(
    session: AsyncSession,
    org_id: UUID,
    engagement_id: UUID,
    pack_id: UUID,
) -> AccreditationPack | None:
    stmt = (
        select(AccreditationPack)
        .join(Accreditation, Accreditation.id == AccreditationPack.accreditation_id)
        .where(
            AccreditationPack.id == pack_id,
            AccreditationPack.org_id == org_id,
            Accreditation.engagement_id == engagement_id,
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()
