"""Materiality persistence. SQL only.

Two things this module reads that the rules engine cannot derive from a diff: the
baseline's approved data classes and regions, and which components carry an open
critical finding. Both arrive in ``MaterialityContext`` so ``rules.py`` stays pure.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.assurance import Accreditation, Finding
from app.db.models.registry import Agent, AgentVersion, Release, ReleaseChange

# ----------------------------------------------------------------------
# Context inputs
# ----------------------------------------------------------------------


async def fetch_baseline_scope(
    session: AsyncSession, org_id: UUID, agent_id: UUID
) -> tuple[frozenset[str], frozenset[str]]:
    """Data classes and regions the agent's *baseline* was approved for.

    Read from the baseline rather than from the current version, which is the whole
    point: materiality is measured against what was signed off, not against what
    happens to be deployed. Comparing a change to the current version would let a
    sequence of individually small steps carry an agent anywhere without ever
    tripping a rule.
    """
    stmt = (
        select(AgentVersion.descriptor_json)
        .join(Agent, Agent.baseline_version_id == AgentVersion.id)
        .where(Agent.id == agent_id, Agent.org_id == org_id)
    )
    descriptor = (await session.execute(stmt)).scalar_one_or_none()
    if not descriptor:
        return frozenset(), frozenset()

    data = descriptor.get("data") or {}
    classes = {str(c).lower() for c in (data.get("classes") or [])}
    classes |= {str(c).lower() for c in (data.get("special_categories") or [])}
    residency = data.get("residency") or {}
    regions = {str(r).lower() for r in (residency.get("permitted_regions") or [])}

    return frozenset(classes), frozenset(regions)


async def fetch_critical_cve_components(
    session: AsyncSession, org_id: UUID, agent_id: UUID | None = None
) -> frozenset[str]:
    """Components with an open critical finding, as ``name`` and ``name@version``.

    Both forms because a CVE is pinned to a version while a descriptor may name
    either, and a rule that matched only one of them would miss half the cases.
    """
    stmt = select(Finding.component_name, Finding.component_version).where(
        Finding.org_id == org_id,
        Finding.severity == "critical",
        Finding.state.in_(("open", "triaged")),
        Finding.component_name.is_not(None),
    )
    if agent_id is not None:
        stmt = stmt.where(Finding.agent_id == agent_id)

    out: set[str] = set()
    for name, version in (await session.execute(stmt)).all():
        if not name:
            continue
        out.add(str(name).lower())
        if version:
            out.add(f"{str(name).lower()}@{str(version).lower()}")
    return frozenset(out)


async def fetch_rule_overrides(session: AsyncSession, org_id: UUID) -> dict[str, str]:
    """Standing overrides, keyed by rule id.

    Stored as adjudications carrying a rule scope rather than in a table of their own:
    an override must always be traceable to the decision that created it, and a
    separate table would let one exist without that provenance.
    """
    rows = await session.execute(
        text(
            """
            SELECT DISTINCT ON (rule_id) rule_id, verdict
              FROM (
                    SELECT unnest(rc.rules_fired)     AS rule_id,
                           rc.verdict::text           AS verdict,
                           rc.adjudicated_at          AS decided_at
                      FROM release_changes rc
                      JOIN releases r ON r.id = rc.release_id
                     WHERE rc.org_id = :org_id
                       AND rc.adjudicated_at IS NOT NULL
                       AND rc.adjudication_reason LIKE 'rule-override:%'
                   ) AS decisions
             ORDER BY rule_id, decided_at DESC
            """
        ),
        {"org_id": str(org_id)},
    )
    return {row[0]: row[1] for row in rows.all()}


# ----------------------------------------------------------------------
# Review queue
# ----------------------------------------------------------------------


async def fetch_review_queue(
    session: AsyncSession,
    org_id: UUID,
    *,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Changes awaiting adjudication, ordered by consequence.

    The ORDER BY is the point of this query. Sorting by time buries a needs-review
    change on a live approved accreditation behind a week of development noise, and a
    queue nobody trusts is a queue nobody works.
    """
    rows = await session.execute(
        text(
            """
            SELECT rc.id                AS change_id,
                   rc.release_id,
                   a.id                 AS agent_id,
                   a.urn                AS agent_urn,
                   a.display_name       AS agent_display_name,
                   rc.category::text,
                   rc.subject,
                   rc.summary,
                   rc.severity,
                   rc.rules_fired,
                   rc.created_at,
                   coalesce(acc.accreditation_count, 0) AS accreditation_count,
                   coalesce(acc.customer_names, ARRAY[]::text[]) AS customer_names
              FROM release_changes rc
              JOIN releases r ON r.id = rc.release_id
              JOIN agents   a ON a.id = r.agent_id
              LEFT JOIN (
                    SELECT ac.agent_id,
                           count(*)                     AS accreditation_count,
                           array_agg(DISTINCT c.display_name) AS customer_names
                      FROM accreditations ac
                      LEFT JOIN customers c ON c.id = ac.customer_id
                     WHERE ac.org_id = :org_id
                       AND ac.state IN ('approved','submitted')
                     GROUP BY ac.agent_id
                   ) AS acc ON acc.agent_id = a.id
             WHERE rc.org_id = :org_id
               AND rc.verdict = 'needs_review'
               AND rc.adjudicated_at IS NULL
             ORDER BY coalesce(acc.accreditation_count, 0) DESC,
                      CASE rc.severity
                           WHEN 'critical' THEN 0
                           WHEN 'high'     THEN 1
                           WHEN 'medium'   THEN 2
                           WHEN 'low'      THEN 3
                           ELSE 4
                      END,
                      rc.created_at DESC
             LIMIT :limit OFFSET :offset
            """
        ),
        {"org_id": str(org_id), "limit": limit, "offset": offset},
    )
    return [dict(row) for row in rows.mappings().all()]


async def count_review_queue(session: AsyncSession, org_id: UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(ReleaseChange)
        .where(
            ReleaseChange.org_id == org_id,
            ReleaseChange.verdict == "needs_review",
            ReleaseChange.adjudicated_at.is_(None),
        )
    )
    return (await session.execute(stmt)).scalar_one()


# ----------------------------------------------------------------------
# Changes
# ----------------------------------------------------------------------


async def get_change(session: AsyncSession, org_id: UUID, change_id: UUID) -> ReleaseChange | None:
    stmt = select(ReleaseChange).where(
        ReleaseChange.id == change_id, ReleaseChange.org_id == org_id
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def update_change_verdict(
    session: AsyncSession,
    org_id: UUID,
    change_id: UUID,
    *,
    verdict: str,
    actor: str,
    reason: str,
) -> ReleaseChange | None:
    """Record a human ruling.

    ``release_changes`` is append-only for its *content*; the adjudication columns are
    the sanctioned exception, since a verdict is a decision made about the row rather
    than a claim recorded in it.
    """
    stmt = (
        update(ReleaseChange)
        .where(ReleaseChange.id == change_id, ReleaseChange.org_id == org_id)
        .values(
            verdict=verdict,
            adjudicated_by=actor,
            adjudicated_at=datetime.now(UTC),
            adjudication_reason=reason,
        )
        .returning(ReleaseChange)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def fetch_changes_for_release(
    session: AsyncSession, org_id: UUID, release_id: UUID
) -> list[ReleaseChange]:
    stmt = (
        select(ReleaseChange)
        .where(ReleaseChange.org_id == org_id, ReleaseChange.release_id == release_id)
        .order_by(ReleaseChange.category, ReleaseChange.path)
    )
    return list((await session.execute(stmt)).scalars())


async def bulk_update_verdicts(
    session: AsyncSession,
    org_id: UUID,
    assignments: list[tuple[UUID, str, list[str]]],
) -> int:
    """Write engine verdicts onto persisted changes.

    Used when a release is re-ruled under a different framework: the diff does not
    change, only the judgement about it, so the changes are updated rather than
    re-derived.
    """
    if not assignments:
        return 0

    written = 0
    for change_id, verdict, rules in assignments:
        result = await session.execute(
            update(ReleaseChange)
            .where(ReleaseChange.id == change_id, ReleaseChange.org_id == org_id)
            .values(verdict=verdict, rules_fired=rules)
            .returning(ReleaseChange.id)
        )
        written += len(result.all())
    return written


# ----------------------------------------------------------------------
# Affected approvals
# ----------------------------------------------------------------------


async def fetch_affected_accreditations(
    session: AsyncSession, org_id: UUID, agent_id: UUID
) -> list[dict[str, Any]]:
    """Live approvals for an agent, with the customer each belongs to.

    A reviewer's first question about a material change is not which rule fired but
    who has to be told, so the customer and engagement names are joined here rather
    than resolved by the console one request at a time.
    """
    rows = await session.execute(
        text(
            """
            SELECT ac.id            AS accreditation_id,
                   ac.reference,
                   ac.state::text   AS state,
                   f.name           AS framework_name,
                   c.display_name   AS customer_name,
                   e.name           AS engagement_name,
                   ac.expires_at
              FROM accreditations ac
              JOIN frameworks f   ON f.id = ac.framework_id
              LEFT JOIN customers c   ON c.id = ac.customer_id
              LEFT JOIN engagements e ON e.id = ac.engagement_id
             WHERE ac.org_id = :org_id
               AND ac.agent_id = :agent_id
               AND ac.state IN ('draft','submitted','approved','suspended')
             ORDER BY ac.state, f.name
            """
        ),
        {"org_id": str(org_id), "agent_id": str(agent_id)},
    )
    return [dict(row) for row in rows.mappings().all()]


async def get_release_with_agent(
    session: AsyncSession, org_id: UUID, release_id: UUID
) -> tuple[Release, Agent] | None:
    stmt = (
        select(Release, Agent)
        .join(Agent, Agent.id == Release.agent_id)
        .where(Release.id == release_id, Release.org_id == org_id)
    )
    row = (await session.execute(stmt)).first()
    if row is None:
        return None
    return row[0], row[1]


async def get_descriptor(
    session: AsyncSession, org_id: UUID, version_id: UUID
) -> dict[str, Any] | None:
    stmt = select(AgentVersion.descriptor_json).where(
        AgentVersion.id == version_id, AgentVersion.org_id == org_id
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def fetch_framework_for_accreditation(
    session: AsyncSession, org_id: UUID, agent_id: UUID
) -> str | None:
    """The framework slug governing this agent's strictest live approval.

    Materiality is framework-sensitive — the EU AI Act reviews every model change where
    ISO 42001 accepts a point-version bump — so the engine needs to know which rulebook
    applies. When an agent holds several approvals the strictest wins, because a change
    that breaks one approval has broken it regardless of the others.
    """
    row = await session.execute(
        text(
            """
            SELECT f.slug
              FROM accreditations ac
              JOIN frameworks f ON f.id = ac.framework_id
             WHERE ac.org_id = :org_id
               AND ac.agent_id = :agent_id
               AND ac.state IN ('approved','submitted')
             ORDER BY CASE f.slug WHEN 'eu-ai-act' THEN 0 ELSE 1 END, f.slug
             LIMIT 1
            """
        ),
        {"org_id": str(org_id), "agent_id": str(agent_id)},
    )
    value = row.scalar_one_or_none()
    return str(value) if value else None


async def count_accreditations_by_state(session: AsyncSession, org_id: UUID) -> dict[str, int]:
    stmt = (
        select(Accreditation.state, func.count())
        .where(Accreditation.org_id == org_id)
        .group_by(Accreditation.state)
    )
    return {row[0]: row[1] for row in (await session.execute(stmt)).all()}
