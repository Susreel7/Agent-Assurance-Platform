"""Customer-scoped trust portal — structurally impossible to leak another client's data.

Every query path begins from an ``engagement_id`` resolved from the slug the customer
was given. Agent lists, accreditations, packs and finding counts never join without that
predicate.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.assurance import service as assurance_service
from app.domains.assurance.schemas import SeverityCounts
from app.domains.evidence import service as evidence_service
from app.domains.portal import repository as repo
from app.domains.portal.schemas import PortalAgentSummary, PortalViewOut
from app.domains.sla import service as sla_service


class PortalError(Exception):
    """Base for everything this module raises."""


class EngagementNotFoundError(PortalError):
    def __init__(self, customer_slug: str, engagement_slug: str) -> None:
        super().__init__(f"engagement {customer_slug}/{engagement_slug} not found")
        self.customer_slug = customer_slug
        self.engagement_slug = engagement_slug


class ScopeRow(Protocol):
    """Shape of one ``engagement_agents`` row, declared structurally so the isolation
    filter can be tested with plain objects rather than a live query result."""

    agent_id: UUID
    engagement_id: UUID


def scope_agents_to_engagement(
    engagement_agents: Sequence[ScopeRow],
    engagement_id: UUID,
    *,
    other_engagement_agents: Sequence[ScopeRow] | None = None,
) -> list[UUID]:
    """Agent ids in scope for exactly this engagement.

    The portal is the one surface a customer's own staff reach, so this filter is the
    isolation boundary. It is a separate pure function purely so a unit test can assert
    that no other customer's agent can pass through it.
    """
    scoped = [row.agent_id for row in engagement_agents if row.engagement_id == engagement_id]
    if other_engagement_agents:
        foreign = {
            row.agent_id for row in other_engagement_agents if row.engagement_id != engagement_id
        }
        leaked = set(scoped) & foreign
        if leaked:
            # Raise rather than assert: assertions vanish under ``python -O``, and this
            # is the check that stops one client seeing another's estate.
            raise PortalError(f"cross-customer agent leak: {sorted(map(str, leaked))}")
    return scoped


async def build_portal_view(
    session: AsyncSession,
    org_id: UUID,
    engagement_id: UUID,
) -> PortalViewOut:
    engagement = await repo.get_engagement(session, org_id, engagement_id)
    if engagement is None:
        raise PortalError(f"engagement {engagement_id} not found")

    agents_in_scope = await repo.list_engagement_agents(session, org_id, engagement_id)
    agent_ids = scope_agents_to_engagement(agents_in_scope, engagement_id)
    accreditations = await repo.list_accreditations_for_engagement(session, org_id, engagement_id)
    acc_by_agent = {a.agent_id: a for a in accreditations}

    summaries: list[PortalAgentSummary] = []
    for agent_id in agent_ids:
        acc = acc_by_agent.get(agent_id)
        refs: list[str] = []
        if acc is not None:
            packs = await repo.list_current_packs(session, org_id, acc.id)
            refs = [pack.pack_uri for pack in packs]
        summaries.append(
            PortalAgentSummary(
                agent_id=agent_id,
                accreditation_state=acc.state if acc else None,
                pack_download_refs=refs,
            )
        )

    summary = await sla_service.summarise_engagement(session, org_id, engagement_id)
    slo_map = {s.kind: s.attainment for s in summary.slos}

    counts = SeverityCounts()
    for agent_id in agent_ids:
        partial = await assurance_service.severity_counts(
            session, org_id, agent_id=agent_id, open_only=True
        )
        counts.critical += partial.critical
        counts.high += partial.high
        counts.medium += partial.medium
        counts.low += partial.low
        counts.info += partial.info

    chain = await evidence_service.verify_chain(session, org_id, max_batches=20)

    return PortalViewOut(
        engagement_id=engagement_id,
        engagement_slug=engagement.slug,
        agents=summaries,
        slo_attainment=slo_map,
        finding_counts=counts,
        residency_summary="Processing limited to permitted engagement regions",
        chain_valid=chain.is_valid,
        chain_checked_at=datetime.now(tz=UTC),
    )


async def build_portal_view_by_slug(
    session: AsyncSession,
    org_id: UUID,
    customer_slug: str,
    engagement_slug: str,
) -> PortalViewOut:
    engagement = await repo.get_engagement_by_slug(session, org_id, customer_slug, engagement_slug)
    if engagement is None:
        raise EngagementNotFoundError(customer_slug, engagement_slug)
    return await build_portal_view(session, org_id, engagement.id)


async def get_pack_download(
    session: AsyncSession,
    org_id: UUID,
    customer_slug: str,
    engagement_slug: str,
    pack_id: UUID,
) -> str:
    engagement = await repo.get_engagement_by_slug(session, org_id, customer_slug, engagement_slug)
    if engagement is None:
        raise EngagementNotFoundError(customer_slug, engagement_slug)
    pack = await repo.get_pack_for_engagement(session, org_id, engagement.id, pack_id)
    if pack is None:
        raise PortalError("pack not found for this engagement")
    return pack.pack_uri
