"""Policy persistence. SQL only — no business logic, no HTTP concerns."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.assurance import Policy, PolicyDecision, PolicyVersion


async def insert_policy(session: AsyncSession, org_id: UUID, values: dict[str, Any]) -> Policy:
    stmt = insert(Policy).values(org_id=org_id, **values).returning(Policy)
    return (await session.execute(stmt)).scalar_one()


async def get_policy(session: AsyncSession, org_id: UUID, policy_id: UUID) -> Policy | None:
    stmt = select(Policy).where(Policy.id == policy_id, Policy.org_id == org_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_policy_by_slug(session: AsyncSession, org_id: UUID, slug: str) -> Policy | None:
    stmt = select(Policy).where(Policy.slug == slug, Policy.org_id == org_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_policies(session: AsyncSession, org_id: UUID) -> list[Policy]:
    stmt = select(Policy).where(Policy.org_id == org_id).order_by(Policy.slug)
    return list((await session.execute(stmt)).scalars())


async def insert_policy_version(
    session: AsyncSession, org_id: UUID, values: dict[str, Any]
) -> PolicyVersion:
    stmt = insert(PolicyVersion).values(org_id=org_id, **values).returning(PolicyVersion)
    return (await session.execute(stmt)).scalar_one()


async def get_current_version(
    session: AsyncSession, org_id: UUID, policy_id: UUID
) -> PolicyVersion | None:
    stmt = select(PolicyVersion).where(
        PolicyVersion.org_id == org_id,
        PolicyVersion.policy_id == policy_id,
        PolicyVersion.effective_to.is_(None),
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_versions(
    session: AsyncSession, org_id: UUID, policy_id: UUID
) -> list[PolicyVersion]:
    stmt = (
        select(PolicyVersion)
        .where(PolicyVersion.org_id == org_id, PolicyVersion.policy_id == policy_id)
        .order_by(PolicyVersion.effective_from.desc())
    )
    return list((await session.execute(stmt)).scalars())


async def close_current_version(
    session: AsyncSession, org_id: UUID, policy_id: UUID, effective_to: datetime
) -> int:
    stmt = (
        update(PolicyVersion)
        .where(
            PolicyVersion.org_id == org_id,
            PolicyVersion.policy_id == policy_id,
            PolicyVersion.effective_to.is_(None),
        )
        .values(effective_to=effective_to)
        .returning(PolicyVersion.id)
    )
    return len((await session.execute(stmt)).all())


async def insert_decision(
    session: AsyncSession, org_id: UUID, values: dict[str, Any]
) -> PolicyDecision:
    stmt = insert(PolicyDecision).values(org_id=org_id, **values).returning(PolicyDecision)
    return (await session.execute(stmt)).scalar_one()


async def list_decisions(
    session: AsyncSession,
    org_id: UUID,
    *,
    outcomes: list[str] | None = None,
    agent_id: UUID | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[PolicyDecision]:
    stmt = select(PolicyDecision).where(PolicyDecision.org_id == org_id)
    if outcomes:
        stmt = stmt.where(PolicyDecision.outcome.in_(outcomes))
    if agent_id:
        stmt = stmt.where(PolicyDecision.agent_id == agent_id)
    stmt = stmt.order_by(PolicyDecision.occurred_at.desc()).limit(limit).offset(offset)
    return list((await session.execute(stmt)).scalars())


async def count_decisions(
    session: AsyncSession,
    org_id: UUID,
    *,
    outcomes: list[str] | None = None,
    agent_id: UUID | None = None,
) -> int:
    stmt = select(func.count()).select_from(PolicyDecision).where(PolicyDecision.org_id == org_id)
    if outcomes:
        stmt = stmt.where(PolicyDecision.outcome.in_(outcomes))
    if agent_id:
        stmt = stmt.where(PolicyDecision.agent_id == agent_id)
    return (await session.execute(stmt)).scalar_one()
