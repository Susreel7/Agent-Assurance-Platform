"""The one read this domain owns.

Bootstrap composes other domains rather than owning tables, so there is exactly one query
here: the account's own name and slug, which no other domain exposes as a service call and
which the shell paints in its header.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.registry import Organization


async def account(session: AsyncSession, org_id: UUID) -> Organization | None:
    result = await session.execute(select(Organization).where(Organization.id == org_id))
    return result.scalar_one_or_none()
