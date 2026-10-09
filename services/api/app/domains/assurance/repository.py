"""Assurance persistence — findings, probes and posture scores."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, insert, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.assurance import Accreditation as AccModel
from app.db.models.assurance import Finding, PostureScore, ProbeRun, ProbeSuite
from app.db.models.company import EngagementAgent

_OPEN_STATES = ("open", "triaged")


async def insert_finding(session: AsyncSession, org_id: UUID, values: dict[str, Any]) -> Finding:
    stmt = insert(Finding).values(org_id=org_id, **values).returning(Finding)
    return (await session.execute(stmt)).scalar_one()


async def get_finding(session: AsyncSession, org_id: UUID, finding_id: UUID) -> Finding | None:
    stmt = select(Finding).where(Finding.id == finding_id, Finding.org_id == org_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_finding_by_fingerprint(
    session: AsyncSession, org_id: UUID, fingerprint: str
) -> Finding | None:
    stmt = select(Finding).where(Finding.org_id == org_id, Finding.fingerprint == fingerprint)
    return (await session.execute(stmt)).scalar_one_or_none()


async def update_finding(
    session: AsyncSession, org_id: UUID, finding_id: UUID, values: dict[str, Any]
) -> Finding | None:
    if not values:
        return await get_finding(session, org_id, finding_id)
    stmt = (
        update(Finding)
        .where(Finding.id == finding_id, Finding.org_id == org_id)
        .values(**values)
        .returning(Finding)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def list_findings(
    session: AsyncSession,
    org_id: UUID,
    *,
    severity: list[str] | None = None,
    source: list[str] | None = None,
    category: list[str] | None = None,
    state: list[str] | None = None,
    agent_id: UUID | None = None,
    overdue_only: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[Finding], int]:
    filters = [Finding.org_id == org_id]
    if severity:
        filters.append(Finding.severity.in_(severity))
    if source:
        filters.append(Finding.source.in_(source))
    if category:
        filters.append(Finding.category.in_(category))
    if state:
        filters.append(Finding.state.in_(state))
    if agent_id is not None:
        filters.append(Finding.agent_id == agent_id)
    if overdue_only:
        now = datetime.now(tz=UTC)
        filters.append(Finding.remediation_due.is_not(None))
        filters.append(Finding.remediation_due < now)
        filters.append(Finding.state.in_(_OPEN_STATES))

    base = select(Finding).where(*filters)
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        (
            await session.execute(
                base.order_by(Finding.last_seen_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), int(total)


async def fetch_severity_counts(
    session: AsyncSession,
    org_id: UUID,
    *,
    agent_id: UUID | None = None,
    open_only: bool = True,
) -> dict[str, int]:
    filters = [Finding.org_id == org_id]
    if agent_id is not None:
        filters.append(Finding.agent_id == agent_id)
    if open_only:
        filters.append(Finding.state.in_(_OPEN_STATES))

    stmt = select(Finding.severity, func.count()).where(*filters).group_by(Finding.severity)
    rows = (await session.execute(stmt)).all()
    out = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0}
    for sev, count in rows:
        if sev in out:
            out[sev] = int(count)
    return out


async def list_probe_suites(session: AsyncSession, org_id: UUID) -> list[ProbeSuite]:
    stmt = select(ProbeSuite).where(or_(ProbeSuite.org_id.is_(None), ProbeSuite.org_id == org_id))
    return list((await session.execute(stmt)).scalars().all())


async def update_probe_suite_digest(
    session: AsyncSession, suite_id: UUID, content_digest: str
) -> None:
    from sqlalchemy import update as sql_update

    stmt = (
        sql_update(ProbeSuite)
        .where(ProbeSuite.id == suite_id)
        .values(content_digest=content_digest)
    )
    await session.execute(stmt)


async def get_probe_run(session: AsyncSession, org_id: UUID, run_id: UUID) -> ProbeRun | None:
    stmt = select(ProbeRun).where(ProbeRun.id == run_id, ProbeRun.org_id == org_id)
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_probe_run_with_suite(
    session: AsyncSession, org_id: UUID, run_id: UUID
) -> tuple[ProbeRun, ProbeSuite] | None:
    stmt = (
        select(ProbeRun, ProbeSuite)
        .join(ProbeSuite, ProbeSuite.id == ProbeRun.suite_id)
        .where(ProbeRun.id == run_id, ProbeRun.org_id == org_id)
    )
    row = (await session.execute(stmt)).one_or_none()
    if row is None:
        return None
    return row[0], row[1]


async def fetch_latest_probe_run_for_suite(
    session: AsyncSession,
    org_id: UUID,
    agent_version_id: UUID,
    suite_id: UUID,
) -> ProbeRun | None:
    stmt = (
        select(ProbeRun)
        .where(
            ProbeRun.org_id == org_id,
            ProbeRun.agent_version_id == agent_version_id,
            ProbeRun.suite_id == suite_id,
        )
        .order_by(ProbeRun.started_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def fetch_obligation_requirements(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
    *,
    framework_slug: str | None = None,
) -> list[dict[str, Any]]:
    """Mapped templates for frameworks tied to this agent's customer engagements."""
    from sqlalchemy import text

    stmt = text("""
        SELECT DISTINCT
            ot.id AS template_id,
            ot.statement AS required_statement,
            cm.required_polarity,
            ot.category,
            fc.control_ref,
            f.slug AS framework_slug
        FROM engagement_agents ea
        JOIN engagements e ON e.id = ea.engagement_id AND e.org_id = ea.org_id
        JOIN customer_frameworks cf ON cf.customer_id = e.customer_id AND cf.org_id = e.org_id
        JOIN frameworks f ON f.id = cf.framework_id
        JOIN framework_controls fc ON fc.framework_id = f.id
        JOIN control_mappings cm ON cm.control_id = fc.id
        JOIN obligation_templates ot ON ot.id = cm.obligation_template_id
        WHERE ea.org_id = :org_id
          AND ea.agent_id = :agent_id
          AND ea.removed_at IS NULL
          AND cm.obligation_template_id IS NOT NULL
          AND (f.org_id IS NULL OR f.org_id = :org_id)
          AND (cm.org_id IS NULL OR cm.org_id = :org_id)
          AND (
              CAST(:framework_slug AS text) IS NULL
              OR f.slug = CAST(:framework_slug AS text)
          )
        ORDER BY f.slug, fc.control_ref, ot.id
    """)
    rows = (
        await session.execute(
            stmt,
            {
                "org_id": str(org_id),
                "agent_id": str(agent_id),
                "framework_slug": framework_slug,
            },
        )
    ).mappings()
    return [dict(r) for r in rows]


async def get_probe_suite(session: AsyncSession, org_id: UUID, suite_id: UUID) -> ProbeSuite | None:
    stmt = select(ProbeSuite).where(
        ProbeSuite.id == suite_id,
        or_(ProbeSuite.org_id.is_(None), ProbeSuite.org_id == org_id),
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def insert_probe_run(session: AsyncSession, org_id: UUID, values: dict[str, Any]) -> ProbeRun:
    stmt = insert(ProbeRun).values(org_id=org_id, **values).returning(ProbeRun)
    return (await session.execute(stmt)).scalar_one()


async def list_probe_runs(
    session: AsyncSession,
    org_id: UUID,
    *,
    agent_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[ProbeRun], int]:
    filters = [ProbeRun.org_id == org_id]
    if agent_id is not None:
        filters.append(ProbeRun.agent_id == agent_id)
    base = select(ProbeRun).where(*filters)
    total = (await session.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (
        (
            await session.execute(
                base.order_by(ProbeRun.started_at.desc()).limit(limit).offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return list(rows), int(total)


async def insert_posture_score(
    session: AsyncSession, org_id: UUID, values: dict[str, Any]
) -> PostureScore:
    stmt = insert(PostureScore).values(org_id=org_id, **values).returning(PostureScore)
    return (await session.execute(stmt)).scalar_one()


async def get_latest_posture_score(
    session: AsyncSession, org_id: UUID, agent_id: UUID
) -> PostureScore | None:
    stmt = (
        select(PostureScore)
        .where(PostureScore.org_id == org_id, PostureScore.agent_id == agent_id)
        .order_by(PostureScore.computed_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def fetch_deployed_version_id(
    session: AsyncSession, org_id: UUID, agent_id: UUID
) -> UUID | None:
    stmt = (
        select(EngagementAgent.deployed_version_id)
        .where(
            EngagementAgent.org_id == org_id,
            EngagementAgent.agent_id == agent_id,
            EngagementAgent.removed_at.is_(None),
        )
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def fetch_posture_inputs(
    session: AsyncSession, org_id: UUID, agent_id: UUID
) -> dict[str, Any]:
    """Aggregate the signals posture scoring needs in one round trip where possible."""
    now = datetime.now(tz=UTC)

    crit_stmt = select(func.count()).where(
        Finding.org_id == org_id,
        Finding.agent_id == agent_id,
        Finding.severity == "critical",
        Finding.state.in_(_OPEN_STATES),
    )
    high_stmt = select(func.count()).where(
        Finding.org_id == org_id,
        Finding.agent_id == agent_id,
        Finding.severity == "high",
        Finding.state.in_(_OPEN_STATES),
    )
    overdue_stmt = select(func.count()).where(
        Finding.org_id == org_id,
        Finding.agent_id == agent_id,
        Finding.state.in_(_OPEN_STATES),
        Finding.remediation_due.is_not(None),
        Finding.remediation_due < now,
    )

    crit = (await session.execute(crit_stmt)).scalar_one()
    high = (await session.execute(high_stmt)).scalar_one()
    overdue = (await session.execute(overdue_stmt)).scalar_one()

    suspended_stmt = select(func.count()).where(
        AccModel.org_id == org_id,
        AccModel.agent_id == agent_id,
        AccModel.state == "suspended",
    )
    suspended = int((await session.execute(suspended_stmt)).scalar_one()) > 0

    drift_stmt = select(func.count()).where(
        EngagementAgent.org_id == org_id,
        EngagementAgent.agent_id == agent_id,
        EngagementAgent.removed_at.is_(None),
        EngagementAgent.accredited_version_id.is_not(None),
        EngagementAgent.deployed_version_id.is_not(None),
        EngagementAgent.accredited_version_id != EngagementAgent.deployed_version_id,
    )
    drift = int((await session.execute(drift_stmt)).scalar_one()) > 0

    return {
        "open_critical_count": int(crit),
        "open_high_count": int(high),
        "accreditation_suspended": suspended,
        "accreditation_drift": drift,
        "overdue_remediation_count": int(overdue),
        "unmapped_control_count": 0,
        "missing_ownership": False,
        "declared_not_observed_edge_count": 0,
    }
