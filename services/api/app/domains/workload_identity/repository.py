"""SQL for projects and workload credentials."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.access import Member
from app.db.models.registry import Agent
from app.db.models.workload_identity import (
    Project,
    WorkloadCredential,
    WorkloadCredentialGeneration,
)


async def insert_project(
    session: AsyncSession,
    org_id: UUID,
    row: dict[str, Any],
) -> Project:
    project = Project(org_id=org_id, **row)
    session.add(project)
    await session.flush()
    return project


async def get_project(session: AsyncSession, org_id: UUID, project_id: UUID) -> Project | None:
    result = await session.execute(
        select(Project).where(Project.org_id == org_id, Project.id == project_id)
    )
    return result.scalar_one_or_none()


async def update_project(
    session: AsyncSession,
    org_id: UUID,
    project_id: UUID,
    values: dict[str, Any],
) -> Project | None:
    result = await session.execute(
        update(Project)
        .where(Project.org_id == org_id, Project.id == project_id)
        .values(**values)
        .returning(Project)
    )
    return result.scalar_one_or_none()


async def list_projects(
    session: AsyncSession,
    org_id: UUID,
    *,
    limit: int,
    offset: int,
) -> tuple[list[Project], int]:
    base = select(Project).where(Project.org_id == org_id)
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = await session.execute(base.order_by(Project.slug).limit(limit).offset(offset))
    return list(rows.scalars()), int(total or 0)


async def agent_belongs_to_org(session: AsyncSession, org_id: UUID, agent_id: UUID) -> bool:
    found = await session.execute(
        select(Agent.id).where(Agent.org_id == org_id, Agent.id == agent_id)
    )
    return found.scalar_one_or_none() is not None


async def member_belongs_to_org(session: AsyncSession, org_id: UUID, member_id: UUID) -> bool:
    found = await session.execute(
        select(Member.id).where(Member.org_id == org_id, Member.id == member_id)
    )
    return found.scalar_one_or_none() is not None


async def insert_credential(
    session: AsyncSession,
    org_id: UUID,
    row: dict[str, Any],
) -> WorkloadCredential:
    cred = WorkloadCredential(org_id=org_id, **row)
    session.add(cred)
    await session.flush()
    return cred


async def insert_generation(
    session: AsyncSession,
    org_id: UUID,
    row: dict[str, Any],
) -> WorkloadCredentialGeneration:
    gen = WorkloadCredentialGeneration(org_id=org_id, **row)
    session.add(gen)
    await session.flush()
    return gen


async def set_active_generation(
    session: AsyncSession,
    org_id: UUID,
    credential_id: UUID,
    generation_id: UUID,
) -> None:
    await session.execute(
        update(WorkloadCredential)
        .where(
            WorkloadCredential.org_id == org_id,
            WorkloadCredential.id == credential_id,
        )
        .values(active_generation_id=generation_id)
    )


async def get_credential(
    session: AsyncSession, org_id: UUID, credential_id: UUID
) -> WorkloadCredential | None:
    result = await session.execute(
        select(WorkloadCredential).where(
            WorkloadCredential.org_id == org_id,
            WorkloadCredential.id == credential_id,
        )
    )
    return result.scalar_one_or_none()


async def get_credential_for_update(
    session: AsyncSession, org_id: UUID, credential_id: UUID
) -> WorkloadCredential | None:
    result = await session.execute(
        select(WorkloadCredential)
        .where(
            WorkloadCredential.org_id == org_id,
            WorkloadCredential.id == credential_id,
        )
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def list_credentials(
    session: AsyncSession,
    org_id: UUID,
    *,
    project_id: UUID | None,
    limit: int,
    offset: int,
) -> tuple[list[WorkloadCredential], int]:
    base = select(WorkloadCredential).where(WorkloadCredential.org_id == org_id)
    if project_id is not None:
        base = base.where(WorkloadCredential.project_id == project_id)
    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = await session.execute(
        base.order_by(WorkloadCredential.created_at.desc()).limit(limit).offset(offset)
    )
    return list(rows.scalars()), int(total or 0)


async def get_generation_with_credential(
    session: AsyncSession,
    org_id: UUID,
    generation_id: UUID,
) -> tuple[WorkloadCredential, WorkloadCredentialGeneration] | None:
    result = await session.execute(
        select(WorkloadCredential, WorkloadCredentialGeneration)
        .join(
            WorkloadCredentialGeneration,
            WorkloadCredentialGeneration.credential_id == WorkloadCredential.id,
        )
        .where(
            WorkloadCredentialGeneration.org_id == org_id,
            WorkloadCredentialGeneration.id == generation_id,
            WorkloadCredential.org_id == org_id,
        )
    )
    row = result.first()
    if row is None:
        return None
    credential, generation = row
    return credential, generation


async def get_generation(
    session: AsyncSession,
    org_id: UUID,
    generation_id: UUID,
) -> WorkloadCredentialGeneration | None:
    result = await session.execute(
        select(WorkloadCredentialGeneration).where(
            WorkloadCredentialGeneration.org_id == org_id,
            WorkloadCredentialGeneration.id == generation_id,
        )
    )
    return result.scalar_one_or_none()


async def revoke_generation(
    session: AsyncSession,
    org_id: UUID,
    generation_id: UUID,
    revoked_at: datetime,
) -> None:
    await session.execute(
        update(WorkloadCredentialGeneration)
        .where(
            WorkloadCredentialGeneration.org_id == org_id,
            WorkloadCredentialGeneration.id == generation_id,
            WorkloadCredentialGeneration.revoked_at.is_(None),
        )
        .values(revoked_at=revoked_at)
    )


async def revoke_credential(
    session: AsyncSession,
    org_id: UUID,
    credential_id: UUID,
    revoked_at: datetime,
) -> None:
    await session.execute(
        update(WorkloadCredential)
        .where(
            WorkloadCredential.org_id == org_id,
            WorkloadCredential.id == credential_id,
            WorkloadCredential.revoked_at.is_(None),
        )
        .values(revoked_at=revoked_at)
    )


async def touch_last_used(
    session: AsyncSession,
    org_id: UUID,
    credential_id: UUID,
    used_at: datetime,
) -> None:
    await session.execute(
        update(WorkloadCredential)
        .where(
            WorkloadCredential.org_id == org_id,
            WorkloadCredential.id == credential_id,
        )
        .values(last_used_at=used_at)
    )


async def max_generation_number(session: AsyncSession, org_id: UUID, credential_id: UUID) -> int:
    value = await session.scalar(
        select(func.coalesce(func.max(WorkloadCredentialGeneration.generation_number), 0)).where(
            WorkloadCredentialGeneration.org_id == org_id,
            WorkloadCredentialGeneration.credential_id == credential_id,
        )
    )
    return int(value or 0)
