"""SLO persistence."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.assurance import SloBreach, SloDefinition, SloMeasurement
from app.db.models.company import Engagement


async def insert_slo_definition(
    session: AsyncSession, org_id: UUID, values: dict[str, Any]
) -> SloDefinition:
    stmt = insert(SloDefinition).values(org_id=org_id, **values).returning(SloDefinition)
    return (await session.execute(stmt)).scalar_one()


async def get_slo_definition(
    session: AsyncSession, org_id: UUID, slo_id: UUID
) -> SloDefinition | None:
    stmt = select(SloDefinition).where(SloDefinition.id == slo_id, SloDefinition.org_id == org_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_slo_definitions(
    session: AsyncSession,
    org_id: UUID,
    engagement_id: UUID | None = None,
) -> list[SloDefinition]:
    filters = [SloDefinition.org_id == org_id]
    if engagement_id is not None:
        filters.append(SloDefinition.engagement_id == engagement_id)
    stmt = select(SloDefinition).where(*filters).order_by(SloDefinition.created_at.desc())
    return list((await session.execute(stmt)).scalars().all())


async def insert_measurement(
    session: AsyncSession, org_id: UUID, values: dict[str, Any]
) -> SloMeasurement:
    stmt = insert(SloMeasurement).values(org_id=org_id, **values).returning(SloMeasurement)
    return (await session.execute(stmt)).scalar_one()


async def get_measurement_for_bucket(
    session: AsyncSession,
    org_id: UUID,
    slo_id: UUID,
    bucket_start: datetime,
) -> SloMeasurement | None:
    stmt = select(SloMeasurement).where(
        SloMeasurement.org_id == org_id,
        SloMeasurement.slo_id == slo_id,
        SloMeasurement.bucket_start == bucket_start,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def update_measurement(
    session: AsyncSession,
    org_id: UUID,
    measurement_id: UUID,
    values: dict[str, Any],
) -> SloMeasurement | None:
    stmt = (
        update(SloMeasurement)
        .where(SloMeasurement.id == measurement_id, SloMeasurement.org_id == org_id)
        .values(**values)
        .returning(SloMeasurement)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_measurements_since(
    session: AsyncSession,
    org_id: UUID,
    slo_id: UUID,
    since: datetime,
) -> list[SloMeasurement]:
    stmt = (
        select(SloMeasurement)
        .where(
            SloMeasurement.org_id == org_id,
            SloMeasurement.slo_id == slo_id,
            SloMeasurement.bucket_start >= since,
        )
        .order_by(SloMeasurement.bucket_start.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_open_breach(session: AsyncSession, org_id: UUID, slo_id: UUID) -> SloBreach | None:
    stmt = (
        select(SloBreach)
        .where(
            SloBreach.org_id == org_id,
            SloBreach.slo_id == slo_id,
            SloBreach.ended_at.is_(None),
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def insert_breach(session: AsyncSession, org_id: UUID, values: dict[str, Any]) -> SloBreach:
    stmt = insert(SloBreach).values(org_id=org_id, **values).returning(SloBreach)
    return (await session.execute(stmt)).scalar_one()


async def update_breach(
    session: AsyncSession, org_id: UUID, breach_id: UUID, values: dict[str, Any]
) -> SloBreach | None:
    stmt = (
        update(SloBreach)
        .where(SloBreach.id == breach_id, SloBreach.org_id == org_id)
        .values(**values)
        .returning(SloBreach)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_breach(session: AsyncSession, org_id: UUID, breach_id: UUID) -> SloBreach | None:
    stmt = select(SloBreach).where(SloBreach.id == breach_id, SloBreach.org_id == org_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_breaches(session: AsyncSession, org_id: UUID, slo_id: UUID) -> list[SloBreach]:
    stmt = (
        select(SloBreach)
        .where(SloBreach.org_id == org_id, SloBreach.slo_id == slo_id)
        .order_by(SloBreach.started_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def count_open_breaches(session: AsyncSession, org_id: UUID, slo_id: UUID) -> int:
    stmt = select(func.count()).where(
        SloBreach.org_id == org_id,
        SloBreach.slo_id == slo_id,
        SloBreach.ended_at.is_(None),
    )
    return int((await session.execute(stmt)).scalar_one())


async def sum_breach_credits(session: AsyncSession, org_id: UUID, slo_id: UUID) -> Decimal:
    stmt = select(func.coalesce(func.sum(SloBreach.credit_amount), 0)).where(
        SloBreach.org_id == org_id,
        SloBreach.slo_id == slo_id,
    )
    return Decimal(str((await session.execute(stmt)).scalar_one()))


async def engagement_exists(session: AsyncSession, org_id: UUID, engagement_id: UUID) -> bool:
    stmt = select(func.count()).where(
        Engagement.id == engagement_id,
        Engagement.org_id == org_id,
    )
    return int((await session.execute(stmt)).scalar_one()) > 0
