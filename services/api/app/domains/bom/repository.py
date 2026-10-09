"""BOM persistence. SQL only."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.registry import Agent, AgentVersion, BomComponent


async def insert_components(
    session: AsyncSession, org_id: UUID, rows: list[dict[str, Any]]
) -> None:
    for row in rows:
        stmt = insert(BomComponent).values(org_id=org_id, **row)
        await session.execute(stmt)


async def list_components(
    session: AsyncSession, org_id: UUID, agent_version_id: UUID
) -> list[BomComponent]:
    stmt = (
        select(BomComponent)
        .where(
            BomComponent.org_id == org_id,
            BomComponent.agent_version_id == agent_version_id,
        )
        .order_by(BomComponent.kind, BomComponent.name)
    )
    return list((await session.execute(stmt)).scalars())


async def count_by_agent_and_kind(session: AsyncSession, org_id: UUID) -> list[Any]:
    """How many components of each kind each agent's current version declares.

    Scoped to the *current* version rather than every version ever published. An agent
    that once declared six MCP servers and now declares one has one, and counting the
    history would make the estate look like it depends on far more than it does.
    """
    stmt = (
        select(
            AgentVersion.agent_id,
            BomComponent.kind,
            func.count().label("components"),
        )
        .join(AgentVersion, AgentVersion.id == BomComponent.agent_version_id)
        .join(Agent, Agent.current_version_id == AgentVersion.id)
        .where(
            BomComponent.org_id == org_id,
            AgentVersion.org_id == org_id,
            Agent.org_id == org_id,
        )
        .group_by(AgentVersion.agent_id, BomComponent.kind)
    )
    return list((await session.execute(stmt)).all())


async def fetch_usage(session: AsyncSession, org_id: UUID, kind: str, name: str) -> list[Any]:
    stmt = (
        select(
            Agent.id.label("agent_id"),
            Agent.urn,
            AgentVersion.id.label("version_id"),
            AgentVersion.semver,
            BomComponent.kind,
            BomComponent.name,
        )
        .join(AgentVersion, AgentVersion.id == BomComponent.agent_version_id)
        .join(Agent, Agent.id == AgentVersion.agent_id)
        .where(
            BomComponent.org_id == org_id,
            AgentVersion.org_id == org_id,
            Agent.org_id == org_id,
            BomComponent.kind == kind,
            BomComponent.name == name,
        )
        .order_by(Agent.display_name, AgentVersion.published_at.desc())
    )
    return list((await session.execute(stmt)).all())
