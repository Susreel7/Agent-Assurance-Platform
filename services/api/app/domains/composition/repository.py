"""Composition SQL only."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.composition import CompositionReconciliation, CompositionRuleObligation
from app.db.models.operations import RunStep, ToolUsageDaily


async def replace_obligations(
    session: AsyncSession,
    org_id: UUID,
    agent_version_id: UUID,
    rows: list[dict[str, Any]],
) -> None:
    await session.execute(
        delete(CompositionRuleObligation).where(
            CompositionRuleObligation.org_id == org_id,
            CompositionRuleObligation.agent_version_id == agent_version_id,
        )
    )
    if not rows:
        return
    await session.execute(
        pg_insert(CompositionRuleObligation).values([{"org_id": org_id, **row} for row in rows])
    )


async def upsert_reconciliations(
    session: AsyncSession,
    org_id: UUID,
    rows: list[dict[str, Any]],
) -> None:
    if not rows:
        return
    base = pg_insert(CompositionReconciliation).values([{"org_id": org_id, **row} for row in rows])
    stmt = base.on_conflict_do_update(
        constraint="composition_reconciliations_unique",
        set_={
            "declared": base.excluded.declared,
            "observed": base.excluded.observed,
            "status": base.excluded.status,
            "observed_count": base.excluded.observed_count,
            "computed_at": base.excluded.computed_at,
        },
    )
    await session.execute(stmt)


async def list_reconciliations(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
    *,
    window_end: date | None = None,
) -> list[CompositionReconciliation]:
    stmt = select(CompositionReconciliation).where(
        CompositionReconciliation.org_id == org_id,
        CompositionReconciliation.agent_id == agent_id,
    )
    if window_end is not None:
        stmt = stmt.where(CompositionReconciliation.window_end == window_end)
    else:
        stmt = stmt.order_by(CompositionReconciliation.window_end.desc()).limit(500)
    return list((await session.execute(stmt)).scalars().all())


async def observed_tool_counts(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
    since_day: date,
) -> list[Any]:
    stmt = (
        select(
            ToolUsageDaily.tool_name.label("name"),
            func.sum(ToolUsageDaily.calls).label("calls"),
        )
        .where(
            ToolUsageDaily.org_id == org_id,
            ToolUsageDaily.agent_id == agent_id,
            ToolUsageDaily.day >= since_day,
            ToolUsageDaily.surface == "native",
        )
        .group_by(ToolUsageDaily.tool_name)
    )
    return list((await session.execute(stmt)).all())


async def observed_mcp_counts(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
    since_day: date,
) -> list[Any]:
    stmt = (
        select(
            ToolUsageDaily.server_name.label("name"),
            func.sum(ToolUsageDaily.calls).label("calls"),
        )
        .where(
            ToolUsageDaily.org_id == org_id,
            ToolUsageDaily.agent_id == agent_id,
            ToolUsageDaily.day >= since_day,
            ToolUsageDaily.surface == "mcp",
            ToolUsageDaily.server_name != "",
        )
        .group_by(ToolUsageDaily.server_name)
    )
    return list((await session.execute(stmt)).all())


async def observed_step_counts(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
    since: datetime,
    *,
    kind: str,
) -> list[Any]:
    stmt = (
        select(
            RunStep.name.label("name"),
            RunStep.model.label("model"),
            RunStep.server_name.label("server_name"),
            func.count().label("calls"),
        )
        .where(
            RunStep.org_id == org_id,
            RunStep.agent_id == agent_id,
            RunStep.started_at >= since,
            RunStep.kind == kind,
        )
        .group_by(RunStep.name, RunStep.model, RunStep.server_name)
    )
    return list((await session.execute(stmt)).all())
