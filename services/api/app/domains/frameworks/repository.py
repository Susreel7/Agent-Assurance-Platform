"""Framework persistence. SQL only — no business logic, no HTTP concerns."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.company import ControlMapping, Framework, FrameworkControl


async def list_frameworks(
    session: AsyncSession, org_id: UUID, *, kinds: list[str] | None = None
) -> list[tuple[Framework, int]]:
    control_count = (
        select(func.count())
        .select_from(FrameworkControl)
        .where(FrameworkControl.framework_id == Framework.id)
        .correlate(Framework)
        .scalar_subquery()
    )
    stmt = select(Framework, control_count.label("control_count")).where(
        or_(Framework.org_id.is_(None), Framework.org_id == org_id)
    )
    if kinds:
        stmt = stmt.where(Framework.kind.in_(kinds))
    stmt = stmt.order_by(Framework.kind, Framework.name)
    return [(row[0], row[1]) for row in (await session.execute(stmt)).all()]


async def get_framework(
    session: AsyncSession, org_id: UUID, framework_id: UUID
) -> Framework | None:
    stmt = select(Framework).where(
        Framework.id == framework_id,
        or_(Framework.org_id.is_(None), Framework.org_id == org_id),
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_framework_by_slug(session: AsyncSession, org_id: UUID, slug: str) -> Framework | None:
    stmt = select(Framework).where(
        Framework.slug == slug,
        or_(Framework.org_id.is_(None), Framework.org_id == org_id),
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def insert_framework(
    session: AsyncSession, org_id: UUID, values: dict[str, Any]
) -> Framework:
    stmt = insert(Framework).values(org_id=org_id, **values).returning(Framework)
    return (await session.execute(stmt)).scalar_one()


async def list_controls(
    session: AsyncSession, org_id: UUID, framework_id: UUID
) -> list[FrameworkControl]:
    fw = await get_framework(session, org_id, framework_id)
    if fw is None:
        return []
    stmt = (
        select(FrameworkControl)
        .where(FrameworkControl.framework_id == framework_id)
        .order_by(
            FrameworkControl.section.asc().nulls_first(),
            FrameworkControl.ordinal,
            FrameworkControl.control_ref,
        )
    )
    return list((await session.execute(stmt)).scalars())


async def get_control(
    session: AsyncSession, org_id: UUID, control_id: UUID
) -> FrameworkControl | None:
    stmt = (
        select(FrameworkControl)
        .join(Framework, Framework.id == FrameworkControl.framework_id)
        .where(
            FrameworkControl.id == control_id,
            or_(Framework.org_id.is_(None), Framework.org_id == org_id),
        )
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def bulk_insert_controls(
    session: AsyncSession, org_id: UUID, framework_id: UUID, rows: list[dict[str, Any]]
) -> list[FrameworkControl]:
    if not rows:
        return []
    payload = [{**r, "framework_id": framework_id, "org_id": org_id} for r in rows]
    stmt = insert(FrameworkControl).values(payload).returning(FrameworkControl)
    return list((await session.execute(stmt)).scalars())


async def upsert_control_mapping(
    session: AsyncSession, org_id: UUID, control_id: UUID, values: dict[str, Any]
) -> ControlMapping:
    stmt = (
        pg_insert(ControlMapping)
        .values(org_id=org_id, control_id=control_id, **values)
        .on_conflict_do_update(
            index_elements=["control_id", "evidence_kind", "org_id"],
            set_={
                "strength": values["strength"],
                "producer": values["producer"],
                "narrative_template": values.get("narrative_template"),
            },
        )
        .returning(ControlMapping)
    )
    return (await session.execute(stmt)).scalar_one()


async def bind_obligation_templates(
    session: AsyncSession,
    org_id: UUID,
    links: Iterable[tuple[str, str, str, str]],
) -> int:
    """Attach shipped obligation templates to global control mappings (idempotent)."""
    updated = 0
    for slug, control_ref, template_id, polarity in links:
        stmt = text("""
            UPDATE control_mappings cm
            SET obligation_template_id = :template_id,
                required_polarity = :polarity
            FROM framework_controls fc
            JOIN frameworks f ON f.id = fc.framework_id
            WHERE cm.control_id = fc.id
              AND f.slug = :slug
              AND fc.control_ref = :control_ref
              AND cm.org_id IS NULL
              AND f.org_id IS NULL
        """)
        result = await session.execute(
            stmt,
            {
                "template_id": template_id,
                "polarity": polarity,
                "slug": slug,
                "control_ref": control_ref,
            },
        )
        updated += int(getattr(result, "rowcount", 0) or 0)
    return updated


async def fetch_coverage(session: AsyncSession, org_id: UUID, framework_id: UUID) -> list[Any]:
    """Per-control mapping presence for one framework visible to this tenant."""
    stmt = text("""
        SELECT
            fc.id AS control_id,
            fc.control_ref,
            fc.title,
            fc.answer_mode,
            count(cm.id) AS mapping_count
        FROM framework_controls fc
        JOIN frameworks f ON f.id = fc.framework_id
        LEFT JOIN control_mappings cm
               ON cm.control_id = fc.id
              AND (cm.org_id IS NULL OR cm.org_id = :org_id)
        WHERE fc.framework_id = :framework_id
          AND (f.org_id IS NULL OR f.org_id = :org_id)
        GROUP BY fc.id, fc.control_ref, fc.title, fc.answer_mode
        ORDER BY fc.section NULLS FIRST, fc.ordinal, fc.control_ref
    """)
    result = await session.execute(stmt, {"org_id": str(org_id), "framework_id": str(framework_id)})
    return list(result.all())
