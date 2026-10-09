"""Registry persistence. SQL only — no business logic, no HTTP concerns."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.registry import Agent, AgentOwnership, AgentVersion

# ----------------------------------------------------------------------
# Agents
# ----------------------------------------------------------------------


async def insert_agent(session: AsyncSession, org_id: UUID, values: dict[str, Any]) -> Agent:
    stmt = insert(Agent).values(org_id=org_id, **values).returning(Agent)
    return (await session.execute(stmt)).scalar_one()


async def get_agent(session: AsyncSession, org_id: UUID, agent_id: UUID) -> Agent | None:
    stmt = select(Agent).where(Agent.id == agent_id, Agent.org_id == org_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_agent_by_urn(session: AsyncSession, org_id: UUID, urn: str) -> Agent | None:
    stmt = select(Agent).where(Agent.urn == urn, Agent.org_id == org_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def update_agent(
    session: AsyncSession, org_id: UUID, agent_id: UUID, values: dict[str, Any]
) -> Agent | None:
    if not values:
        return await get_agent(session, org_id, agent_id)
    stmt = (
        update(Agent)
        .where(Agent.id == agent_id, Agent.org_id == org_id)
        .values(**values)
        .returning(Agent)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_agents(
    session: AsyncSession,
    org_id: UUID,
    *,
    lifecycle_states: list[str] | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Any]:
    """Agents with the version each one is currently on.

    The join carries `runtime_framework` and `semver`, which every caller that lists
    agents turned out to want: a list saying only that an agent exists cannot answer
    "what is it built on" or "which version is live" without a query per row. Outer,
    because an agent that has never published a version is still an agent.
    """
    stmt = (
        select(
            Agent,
            AgentVersion.runtime_framework.label("runtime_framework"),
            AgentVersion.semver.label("current_semver"),
        )
        .outerjoin(AgentVersion, AgentVersion.id == Agent.current_version_id)
        .where(Agent.org_id == org_id)
    )
    if lifecycle_states:
        stmt = stmt.where(Agent.lifecycle_state.in_(lifecycle_states))
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Agent.display_name).like(pattern),
                func.lower(Agent.urn).like(pattern),
            )
        )
    stmt = stmt.order_by(Agent.display_name).limit(limit).offset(offset)
    return list((await session.execute(stmt)).all())


async def count_agents(
    session: AsyncSession,
    org_id: UUID,
    *,
    lifecycle_states: list[str] | None = None,
    search: str | None = None,
) -> int:
    stmt = select(func.count()).select_from(Agent).where(Agent.org_id == org_id)
    if lifecycle_states:
        stmt = stmt.where(Agent.lifecycle_state.in_(lifecycle_states))
    if search:
        pattern = f"%{search.lower()}%"
        stmt = stmt.where(
            or_(
                func.lower(Agent.display_name).like(pattern),
                func.lower(Agent.urn).like(pattern),
            )
        )
    return (await session.execute(stmt)).scalar_one()


# ----------------------------------------------------------------------
# Versions — append-only at the database layer
# ----------------------------------------------------------------------


async def insert_version(
    session: AsyncSession, org_id: UUID, agent_id: UUID, values: dict[str, Any]
) -> AgentVersion:
    stmt = (
        insert(AgentVersion)
        .values(org_id=org_id, agent_id=agent_id, **values)
        .returning(AgentVersion)
    )
    return (await session.execute(stmt)).scalar_one()


async def get_version(
    session: AsyncSession, org_id: UUID, agent_id: UUID, version_id: UUID
) -> AgentVersion | None:
    stmt = select(AgentVersion).where(
        AgentVersion.id == version_id,
        AgentVersion.agent_id == agent_id,
        AgentVersion.org_id == org_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_version_by_id(
    session: AsyncSession, org_id: UUID, version_id: UUID
) -> AgentVersion | None:
    stmt = select(AgentVersion).where(
        AgentVersion.id == version_id,
        AgentVersion.org_id == org_id,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_latest_version(
    session: AsyncSession, org_id: UUID, agent_id: UUID
) -> AgentVersion | None:
    stmt = (
        select(AgentVersion)
        .where(AgentVersion.agent_id == agent_id, AgentVersion.org_id == org_id)
        .order_by(AgentVersion.published_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_versions(session: AsyncSession, org_id: UUID, agent_id: UUID) -> list[AgentVersion]:
    stmt = (
        select(AgentVersion)
        .where(AgentVersion.agent_id == agent_id, AgentVersion.org_id == org_id)
        .order_by(AgentVersion.published_at.desc())
    )
    return list((await session.execute(stmt)).scalars())


async def exists_semver(session: AsyncSession, org_id: UUID, agent_id: UUID, semver: str) -> bool:
    stmt = (
        select(func.count())
        .select_from(AgentVersion)
        .where(
            AgentVersion.agent_id == agent_id,
            AgentVersion.org_id == org_id,
            AgentVersion.semver == semver,
        )
    )
    return (await session.execute(stmt)).scalar_one() > 0


# ----------------------------------------------------------------------
# Ownership
# ----------------------------------------------------------------------


async def close_owner(
    session: AsyncSession, org_id: UUID, agent_id: UUID, role: str, at: datetime
) -> None:
    stmt = (
        update(AgentOwnership)
        .where(
            AgentOwnership.org_id == org_id,
            AgentOwnership.agent_id == agent_id,
            AgentOwnership.role == role,
            AgentOwnership.valid_to.is_(None),
        )
        .values(valid_to=at)
    )
    await session.execute(stmt)


async def insert_owner(
    session: AsyncSession, org_id: UUID, agent_id: UUID, values: dict[str, Any]
) -> AgentOwnership:
    stmt = (
        insert(AgentOwnership)
        .values(org_id=org_id, agent_id=agent_id, **values)
        .returning(AgentOwnership)
    )
    return (await session.execute(stmt)).scalar_one()


async def list_current_owners(
    session: AsyncSession, org_id: UUID, agent_id: UUID
) -> list[AgentOwnership]:
    stmt = (
        select(AgentOwnership)
        .where(
            AgentOwnership.org_id == org_id,
            AgentOwnership.agent_id == agent_id,
            AgentOwnership.valid_to.is_(None),
        )
        .order_by(AgentOwnership.role)
    )
    return list((await session.execute(stmt)).scalars())


# ----------------------------------------------------------------------
# Drift
# ----------------------------------------------------------------------


async def fetch_drift_rows(session: AsyncSession, org_id: UUID) -> list[Any]:
    """Agents whose running version differs from the signed-off baseline."""
    stmt = text("""
        SELECT
            a.id AS agent_id,
            a.urn,
            a.baseline_version_id,
            a.current_version_id,
            bv.semver AS baseline_semver,
            cv.semver AS current_semver
        FROM agents a
        LEFT JOIN agent_versions bv
               ON bv.id = a.baseline_version_id AND bv.org_id = a.org_id
        LEFT JOIN agent_versions cv
               ON cv.id = a.current_version_id AND cv.org_id = a.org_id
        WHERE a.org_id = :org_id
          AND a.lifecycle_state <> 'retired'
          AND (
                a.baseline_version_id IS NULL
             OR a.current_version_id IS NULL
             OR a.current_version_id IS DISTINCT FROM a.baseline_version_id
          )
        ORDER BY a.display_name
    """)
    result = await session.execute(stmt, {"org_id": str(org_id)})
    return list(result.all())
