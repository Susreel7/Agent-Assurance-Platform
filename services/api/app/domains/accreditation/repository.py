"""Accreditation persistence."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.assurance import (
    Accreditation,
    AccreditationControl,
    AccreditationPack,
    AccreditationTransition,
)
from app.db.models.company import (
    ControlMapping,
    CustomerFramework,
    Engagement,
    EngagementAgent,
    Framework,
    FrameworkControl,
)
from app.db.models.evidence import EvidenceEvent
from app.db.models.registry import AgentVersion, Release

_LIVE_STATES = ("draft", "submitted", "approved", "suspended")


async def insert_accreditation(
    session: AsyncSession, org_id: UUID, values: dict[str, Any]
) -> Accreditation:
    stmt = insert(Accreditation).values(org_id=org_id, **values).returning(Accreditation)
    return (await session.execute(stmt)).scalar_one()


async def get_accreditation(
    session: AsyncSession, org_id: UUID, accreditation_id: UUID
) -> Accreditation | None:
    stmt = select(Accreditation).where(
        Accreditation.id == accreditation_id,
        Accreditation.org_id == org_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_accreditations(
    session: AsyncSession,
    org_id: UUID,
    *,
    state: list[str] | None = None,
    engagement_id: UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Accreditation], int]:
    filters = [Accreditation.org_id == org_id]
    if state:
        filters.append(Accreditation.state.in_(state))
    if engagement_id is not None:
        filters.append(Accreditation.engagement_id == engagement_id)
    base = select(Accreditation).where(*filters)
    total = int(
        (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    )
    rows = (
        (
            await session.execute(
                base.order_by(Accreditation.updated_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), total


async def update_accreditation(
    session: AsyncSession,
    org_id: UUID,
    accreditation_id: UUID,
    values: dict[str, Any],
) -> Accreditation | None:
    stmt = (
        update(Accreditation)
        .where(Accreditation.id == accreditation_id, Accreditation.org_id == org_id)
        .values(**values)
        .returning(Accreditation)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def insert_transition(
    session: AsyncSession, org_id: UUID, values: dict[str, Any]
) -> AccreditationTransition:
    stmt = (
        insert(AccreditationTransition)
        .values(org_id=org_id, **values)
        .returning(AccreditationTransition)
    )
    return (await session.execute(stmt)).scalar_one()


async def list_transitions(
    session: AsyncSession, org_id: UUID, accreditation_id: UUID
) -> list[AccreditationTransition]:
    stmt = (
        select(AccreditationTransition)
        .where(
            AccreditationTransition.org_id == org_id,
            AccreditationTransition.accreditation_id == accreditation_id,
        )
        .order_by(AccreditationTransition.created_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_framework_controls(
    session: AsyncSession, framework_id: UUID
) -> list[FrameworkControl]:
    stmt = (
        select(FrameworkControl)
        .where(FrameworkControl.framework_id == framework_id)
        .order_by(FrameworkControl.ordinal.asc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def list_mappings_for_control(
    session: AsyncSession, control_id: UUID
) -> list[ControlMapping]:
    stmt = select(ControlMapping).where(ControlMapping.control_id == control_id)
    return list((await session.execute(stmt)).scalars().all())


async def count_evidence_for_agent_kind(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
    evidence_kind: str,
) -> int:
    stmt = select(func.count()).where(
        EvidenceEvent.org_id == org_id,
        EvidenceEvent.agent_id == agent_id,
        EvidenceEvent.kind == evidence_kind,
    )
    return int((await session.execute(stmt)).scalar_one())


async def delete_controls_for_accreditation(
    session: AsyncSession, org_id: UUID, accreditation_id: UUID
) -> None:
    stmt = delete(AccreditationControl).where(
        AccreditationControl.org_id == org_id,
        AccreditationControl.accreditation_id == accreditation_id,
    )
    await session.execute(stmt)


async def insert_accreditation_control(
    session: AsyncSession, org_id: UUID, values: dict[str, Any]
) -> AccreditationControl:
    stmt = (
        insert(AccreditationControl).values(org_id=org_id, **values).returning(AccreditationControl)
    )
    return (await session.execute(stmt)).scalar_one()


async def list_accreditation_controls(
    session: AsyncSession, org_id: UUID, accreditation_id: UUID
) -> list[AccreditationControl]:
    stmt = select(AccreditationControl).where(
        AccreditationControl.org_id == org_id,
        AccreditationControl.accreditation_id == accreditation_id,
    )
    return list((await session.execute(stmt)).scalars().all())


async def demote_current_packs(
    session: AsyncSession, org_id: UUID, accreditation_id: UUID, fmt: str
) -> None:
    stmt = (
        update(AccreditationPack)
        .where(
            AccreditationPack.org_id == org_id,
            AccreditationPack.accreditation_id == accreditation_id,
            AccreditationPack.format == fmt,
            AccreditationPack.is_current.is_(True),
        )
        .values(is_current=False)
    )
    await session.execute(stmt)


async def insert_pack(
    session: AsyncSession, org_id: UUID, values: dict[str, Any]
) -> AccreditationPack:
    stmt = insert(AccreditationPack).values(org_id=org_id, **values).returning(AccreditationPack)
    return (await session.execute(stmt)).scalar_one()


async def list_packs(
    session: AsyncSession, org_id: UUID, accreditation_id: UUID
) -> list[AccreditationPack]:
    stmt = (
        select(AccreditationPack)
        .where(
            AccreditationPack.org_id == org_id,
            AccreditationPack.accreditation_id == accreditation_id,
        )
        .order_by(AccreditationPack.rendered_at.desc())
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_pack(session: AsyncSession, org_id: UUID, pack_id: UUID) -> AccreditationPack | None:
    stmt = select(AccreditationPack).where(
        AccreditationPack.id == pack_id,
        AccreditationPack.org_id == org_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_engagement_customer(
    session: AsyncSession, org_id: UUID, engagement_id: UUID
) -> UUID | None:
    stmt = select(Engagement.customer_id).where(
        Engagement.id == engagement_id,
        Engagement.org_id == org_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_live_accreditations_for_version(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
    from_version_id: UUID,
) -> list[Accreditation]:
    stmt = select(Accreditation).where(
        Accreditation.org_id == org_id,
        Accreditation.agent_id == agent_id,
        Accreditation.agent_version_id == from_version_id,
        Accreditation.state.in_(("approved", "suspended")),
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_release(session: AsyncSession, org_id: UUID, release_id: UUID) -> Release | None:
    stmt = select(Release).where(Release.id == release_id, Release.org_id == org_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def fetch_customer_frameworks(
    session: AsyncSession, org_id: UUID, customer_id: UUID
) -> list[tuple[Framework, CustomerFramework]]:
    stmt = (
        select(Framework, CustomerFramework)
        .join(CustomerFramework, CustomerFramework.framework_id == Framework.id)
        .where(
            CustomerFramework.org_id == org_id,
            CustomerFramework.customer_id == customer_id,
            CustomerFramework.level == "mandatory",
        )
    )
    rows = (await session.execute(stmt)).all()
    return [(f, cf) for f, cf in rows]


async def get_latest_checkpoint_id(session: AsyncSession, org_id: UUID) -> UUID | None:
    from app.db.models.evidence import EvidenceCheckpoint

    stmt = (
        select(EvidenceCheckpoint.id)
        .where(EvidenceCheckpoint.org_id == org_id)
        .order_by(EvidenceCheckpoint.published_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_agent_version(
    session: AsyncSession, org_id: UUID, version_id: UUID
) -> AgentVersion | None:
    stmt = select(AgentVersion).where(
        AgentVersion.id == version_id,
        AgentVersion.org_id == org_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def advance_engagement_baseline(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
    from_version_id: UUID,
    to_version_id: UUID,
) -> None:
    stmt = (
        update(EngagementAgent)
        .where(
            EngagementAgent.org_id == org_id,
            EngagementAgent.agent_id == agent_id,
            EngagementAgent.accredited_version_id == from_version_id,
        )
        .values(accredited_version_id=to_version_id)
    )
    await session.execute(stmt)


async def list_due_for_attestation(
    session: AsyncSession, org_id: UUID, now: datetime
) -> list[Accreditation]:
    stmt = select(Accreditation).where(
        Accreditation.org_id == org_id,
        Accreditation.state == "approved",
        Accreditation.next_attestation_due.is_not(None),
        Accreditation.next_attestation_due <= now,
    )
    return list((await session.execute(stmt)).scalars().all())
