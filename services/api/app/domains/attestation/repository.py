"""Attestation persistence."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.assurance import AttestationRun


async def insert_run(session: AsyncSession, org_id: UUID, values: dict[str, Any]) -> AttestationRun:
    stmt = insert(AttestationRun).values(org_id=org_id, **values).returning(AttestationRun)
    return (await session.execute(stmt)).scalar_one()


async def update_run(
    session: AsyncSession,
    org_id: UUID,
    run_id: UUID,
    values: dict[str, Any],
) -> AttestationRun | None:
    from sqlalchemy import update

    stmt = (
        update(AttestationRun)
        .where(AttestationRun.id == run_id, AttestationRun.org_id == org_id)
        .values(**values)
        .returning(AttestationRun)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def agent_has_drift(session: AsyncSession, org_id: UUID, agent_id: UUID) -> bool:
    from sqlalchemy import select

    from app.db.models.company import EngagementAgent

    stmt = (
        select(EngagementAgent.accredited_version_id, EngagementAgent.deployed_version_id)
        .where(
            EngagementAgent.org_id == org_id,
            EngagementAgent.agent_id == agent_id,
            EngagementAgent.removed_at.is_(None),
        )
        .limit(1)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return False
    accredited, deployed = row
    return accredited is not None and deployed is not None and accredited != deployed


async def list_runs(
    session: AsyncSession,
    org_id: UUID,
    accreditation_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AttestationRun], int]:
    filters = [AttestationRun.org_id == org_id]
    if accreditation_id is not None:
        filters.append(AttestationRun.accreditation_id == accreditation_id)
    base = select(AttestationRun).where(*filters)
    total = int(
        (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    )
    rows = (
        (
            await session.execute(
                base.order_by(AttestationRun.started_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), total
