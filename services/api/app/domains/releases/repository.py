"""Release persistence. SQL only — roll-up columns are maintained by triggers."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.registry import Agent, AgentVersion, Release, ReleaseChange

# ----------------------------------------------------------------------
# Releases
# ----------------------------------------------------------------------


async def insert_release(session: AsyncSession, org_id: UUID, values: dict[str, Any]) -> Release:
    stmt = insert(Release).values(org_id=org_id, **values).returning(Release)
    return (await session.execute(stmt)).scalar_one()


async def get_release(session: AsyncSession, org_id: UUID, release_id: UUID) -> Release | None:
    stmt = select(Release).where(Release.id == release_id, Release.org_id == org_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def fetch_release_row(session: AsyncSession, org_id: UUID, release_id: UUID) -> Any | None:
    from_semver = (
        select(AgentVersion.semver)
        .where(AgentVersion.id == Release.from_version_id)
        .correlate(Release)
        .scalar_subquery()
    )
    to_semver = (
        select(AgentVersion.semver)
        .where(AgentVersion.id == Release.to_version_id)
        .correlate(Release)
        .scalar_subquery()
    )
    stmt = (
        select(
            Release,
            Agent.urn.label("agent_urn"),
            from_semver.label("from_semver"),
            to_semver.label("to_semver"),
        )
        .join(Agent, Agent.id == Release.agent_id)
        .where(
            Release.id == release_id,
            Release.org_id == org_id,
            Agent.org_id == org_id,
        )
    )
    return (await session.execute(stmt)).one_or_none()


async def fetch_version_digest(session: AsyncSession, org_id: UUID, version_id: UUID) -> str | None:
    stmt = select(AgentVersion.descriptor_digest).where(
        AgentVersion.id == version_id,
        AgentVersion.org_id == org_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def update_release_state(
    session: AsyncSession,
    org_id: UUID,
    release_id: UUID,
    values: dict[str, Any],
) -> Release | None:
    if not values:
        return await get_release(session, org_id, release_id)
    stmt = (
        update(Release)
        .where(Release.id == release_id, Release.org_id == org_id)
        .values(**values)
        .returning(Release)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_releases(
    session: AsyncSession,
    org_id: UUID,
    *,
    states: list[str] | None = None,
    agent_id: UUID | None = None,
    material_only: bool = False,
    categories: list[str] | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Any]:
    from_semver = (
        select(AgentVersion.semver)
        .where(AgentVersion.id == Release.from_version_id)
        .correlate(Release)
        .scalar_subquery()
    )
    to_semver = (
        select(AgentVersion.semver)
        .where(AgentVersion.id == Release.to_version_id)
        .correlate(Release)
        .scalar_subquery()
    )

    stmt = (
        select(
            Release,
            Agent.urn.label("agent_urn"),
            from_semver.label("from_semver"),
            to_semver.label("to_semver"),
        )
        .join(Agent, Agent.id == Release.agent_id)
        .where(Release.org_id == org_id, Agent.org_id == org_id)
    )

    if states:
        stmt = stmt.where(Release.state.in_(states))
    if agent_id is not None:
        stmt = stmt.where(Release.agent_id == agent_id)
    if material_only:
        stmt = stmt.where(Release.material_count > 0)
    if categories:
        stmt = stmt.where(Release.categories.overlap(categories))
    if created_from is not None:
        stmt = stmt.where(Release.created_at >= created_from)
    if created_to is not None:
        stmt = stmt.where(Release.created_at <= created_to)

    stmt = stmt.order_by(Release.created_at.desc()).limit(limit).offset(offset)
    return list((await session.execute(stmt)).all())


async def count_releases(
    session: AsyncSession,
    org_id: UUID,
    *,
    states: list[str] | None = None,
    agent_id: UUID | None = None,
    material_only: bool = False,
    categories: list[str] | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
) -> int:
    stmt = select(func.count()).select_from(Release).where(Release.org_id == org_id)
    if states:
        stmt = stmt.where(Release.state.in_(states))
    if agent_id is not None:
        stmt = stmt.where(Release.agent_id == agent_id)
    if material_only:
        stmt = stmt.where(Release.material_count > 0)
    if categories:
        stmt = stmt.where(Release.categories.overlap(categories))
    if created_from is not None:
        stmt = stmt.where(Release.created_at >= created_from)
    if created_to is not None:
        stmt = stmt.where(Release.created_at <= created_to)
    return (await session.execute(stmt)).scalar_one()


# ----------------------------------------------------------------------
# Changes — append-only except adjudication fields
# ----------------------------------------------------------------------


async def insert_release_changes(
    session: AsyncSession, org_id: UUID, release_id: UUID, rows: list[dict[str, Any]]
) -> None:
    if not rows:
        return
    for row in rows:
        stmt = insert(ReleaseChange).values(org_id=org_id, release_id=release_id, **row)
        await session.execute(stmt)


async def fetch_changes(
    session: AsyncSession, org_id: UUID, release_id: UUID
) -> list[ReleaseChange]:
    stmt = (
        select(ReleaseChange)
        .where(ReleaseChange.release_id == release_id, ReleaseChange.org_id == org_id)
        .order_by(ReleaseChange.category, ReleaseChange.created_at)
    )
    return list((await session.execute(stmt)).scalars())


async def get_change(
    session: AsyncSession, org_id: UUID, release_id: UUID, change_id: UUID
) -> ReleaseChange | None:
    stmt = select(ReleaseChange).where(
        ReleaseChange.id == change_id,
        ReleaseChange.release_id == release_id,
        ReleaseChange.org_id == org_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def update_change_adjudication(
    session: AsyncSession,
    org_id: UUID,
    release_id: UUID,
    change_id: UUID,
    values: dict[str, Any],
) -> ReleaseChange | None:
    stmt = (
        update(ReleaseChange)
        .where(
            ReleaseChange.id == change_id,
            ReleaseChange.release_id == release_id,
            ReleaseChange.org_id == org_id,
        )
        .values(**values)
        .returning(ReleaseChange)
    )
    return (await session.execute(stmt)).scalar_one_or_none()
