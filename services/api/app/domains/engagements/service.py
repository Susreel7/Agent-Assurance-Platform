"""Engagement business logic.

The function that matters here is ``classify_drift``. Everything else is the bookkeeping
that makes it computable.

Drift is the gap between what a client approved and what they are actually being
served. Organisations currently discover it during an audit, or when a client notices
first — both of which are expensive. It is a query, provided someone has recorded the
approved version separately from the running one, which is what ``engagement_agents``
exists to do.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.engagements import repository as repo
from app.domains.engagements.schemas import (
    DriftItem,
    DriftReport,
    DriftSeverity,
    EngagementCreate,
    EngagementDetail,
    EngagementState,
    EngagementSummary,
    EngagementUpdate,
    ScopeAgentRequest,
    ScopeAgentUpdate,
    ScopedAgentOut,
    ServiceLevelOut,
    ServiceLevelUpsert,
    VersionUptake,
)
from app.domains.evidence import service as evidence_service
from app.domains.evidence.schemas import (
    DetectedBy,
    EvidenceKind,
    EvidenceOutcome,
    EvidenceRecord,
)

# ----------------------------------------------------------------------
# Domain exceptions. Translated to HTTP in router.py, never raised from there.
# ----------------------------------------------------------------------


class EngagementError(Exception):
    """Base for everything this module raises."""


class EngagementNotFoundError(EngagementError):
    def __init__(self, engagement_id: UUID) -> None:
        super().__init__(f"engagement {engagement_id} not found")
        self.engagement_id = engagement_id


class CustomerNotFoundError(EngagementError):
    def __init__(self, customer_id: UUID) -> None:
        super().__init__(f"customer {customer_id} not found")
        self.customer_id = customer_id


class EngagementSlugTakenError(EngagementError):
    def __init__(self, slug: str) -> None:
        super().__init__(f"slug {slug!r} is already used for this customer")
        self.slug = slug


class AgentNotScopedError(EngagementError):
    def __init__(self, agent_id: UUID) -> None:
        super().__init__(f"agent {agent_id} is not in scope for this engagement")
        self.agent_id = agent_id


class AgentAlreadyScopedError(EngagementError):
    def __init__(self, agent_id: UUID) -> None:
        super().__init__(f"agent {agent_id} is already in scope for this engagement")
        self.agent_id = agent_id


class ServiceLevelNotFoundError(EngagementError):
    def __init__(self, slo_id: UUID) -> None:
        super().__init__(f"service level {slo_id} not found on this engagement")
        self.slo_id = slo_id


class IllegalStateChangeError(EngagementError):
    def __init__(self, current: str, requested: str) -> None:
        super().__init__(f"an engagement cannot move from {current} to {requested}")
        self.current = current
        self.requested = requested


# A terminated engagement is final. Anything else would let a delivery be revived
# months later carrying residency terms nobody has re-checked.
_LEGAL_TRANSITIONS: dict[EngagementState, frozenset[EngagementState]] = {
    EngagementState.DRAFT: frozenset({EngagementState.ACTIVE, EngagementState.TERMINATED}),
    EngagementState.ACTIVE: frozenset({EngagementState.SUSPENDED, EngagementState.TERMINATED}),
    EngagementState.SUSPENDED: frozenset({EngagementState.ACTIVE, EngagementState.TERMINATED}),
    EngagementState.TERMINATED: frozenset(),
}


# ----------------------------------------------------------------------
# Drift classification — pure, so the severity rules can be tested directly
# ----------------------------------------------------------------------


# Worst first. Used for both the severity filter and the report ordering, so a change
# here moves both together.
_SEVERITY_RANK: dict[DriftSeverity, int] = {
    DriftSeverity.CRITICAL: 0,
    DriftSeverity.MATERIAL: 1,
    DriftSeverity.INFORMATIONAL: 2,
    DriftSeverity.NONE: 3,
}


@dataclass(slots=True, frozen=True)
class DriftFacts:
    """Everything needed to rule on one scoped agent, with no database in sight."""

    accredited_version_id: UUID | None
    deployed_version_id: UUID | None
    uptake: VersionUptake
    versions_behind: int = 0
    customer_criticality: str = "tier_2"


def classify_drift(facts: DriftFacts) -> tuple[DriftSeverity, str]:
    """Rule on whether a client is being served something they have not approved.

    The severity ladder encodes a commercial judgement, not a technical one:

    - Nothing approved yet but something deployed is **critical**. An unaccredited agent
      serving a client is the exposure the whole product exists to prevent, and it is
      worse than a stale approval because no review has happened at all.
    - A pinned client running a different version is **critical**. Pinned means they
      explicitly refused automatic uptake, so this is a broken commitment.
    - An auto-uptake client running a newer version is **informational**: they consented
      to this in advance. It still appears in the report, because "consented" is not the
      same as "nobody should look at it".
    - Anything else is **material** — a real gap that needs either a re-review or a
      rollback, and the distance widens the case for the former.

    A tier-1 client escalates material to critical. Their reviewers escalate anything
    arguable, so the platform should have flagged it first.
    """
    if facts.deployed_version_id is None:
        # Nothing running. A scoped agent awaiting deployment is not drift.
        return DriftSeverity.NONE, "no version deployed for this client yet"

    if facts.accredited_version_id is None:
        return (
            DriftSeverity.CRITICAL,
            "deployed to this client without any accredited version on record",
        )

    if facts.deployed_version_id == facts.accredited_version_id:
        return DriftSeverity.NONE, "deployed version matches the accredited version"

    behind = facts.versions_behind
    distance = (
        f"{behind} version{'s' if behind != 1 else ''} ahead of the accredited version"
        if behind > 0
        else "a different version from the accredited one"
    )

    if facts.uptake is VersionUptake.PINNED:
        return (
            DriftSeverity.CRITICAL,
            f"client is pinned but is being served {distance}",
        )

    severity = DriftSeverity.INFORMATIONAL if behind > 0 else DriftSeverity.MATERIAL
    reason = (
        f"client accepts {facts.uptake.value} uptake and is running {distance}"
        if severity is DriftSeverity.INFORMATIONAL
        else f"running {distance}, which the client's uptake setting does not cover"
    )

    if severity is DriftSeverity.MATERIAL and facts.customer_criticality == "tier_1":
        return DriftSeverity.CRITICAL, f"{reason} — raised because this client is tier 1"

    return severity, reason


def _versions_behind(sequence: list[UUID], accredited: UUID | None, deployed: UUID | None) -> int:
    """How many published versions sit between the approved one and the running one.

    Negative distances are reported as 0: a client served something *older* than they
    approved is a rollback, which is a different problem and should not be described
    with a misleading count.
    """
    if accredited is None or deployed is None:
        return 0
    try:
        gap = sequence.index(deployed) - sequence.index(accredited)
    except ValueError:
        return 0
    return max(gap, 0)


# ----------------------------------------------------------------------
# Engagements
# ----------------------------------------------------------------------


async def create_engagement(
    session: AsyncSession, org_id: UUID, payload: EngagementCreate
) -> EngagementDetail:
    names = await repo.fetch_customer_names(session, org_id, [payload.customer_id])
    if payload.customer_id not in names:
        raise CustomerNotFoundError(payload.customer_id)

    existing = await repo.get_engagement_by_slug(session, org_id, payload.customer_id, payload.slug)
    if existing is not None:
        raise EngagementSlugTakenError(payload.slug)

    values = payload.model_dump()
    values["state"] = payload.state.value
    values["cross_border_transfer"] = payload.cross_border_transfer.value
    engagement = await repo.insert_engagement(session, org_id, values)
    return await _build_detail(session, org_id, engagement.id)


async def update_engagement(
    session: AsyncSession, org_id: UUID, engagement_id: UUID, payload: EngagementUpdate
) -> EngagementDetail:
    current = await repo.get_engagement(session, org_id, engagement_id)
    if current is None:
        raise EngagementNotFoundError(engagement_id)

    values = payload.model_dump(exclude_unset=True)

    if "state" in values and values["state"] is not None:
        requested = EngagementState(values["state"])
        existing_state = EngagementState(current.state)
        if requested is not existing_state and requested not in _LEGAL_TRANSITIONS[existing_state]:
            raise IllegalStateChangeError(existing_state.value, requested.value)
        values["state"] = requested.value

    if values.get("cross_border_transfer") is not None:
        values["cross_border_transfer"] = values["cross_border_transfer"].value

    # Residency is checked across the merged result, not the patch alone. A request
    # that adds 'eu-west-1' to permitted_regions while it is still prohibited must
    # fail, and the patch on its own cannot see that.
    merged_permitted = set(values.get("permitted_regions") or current.permitted_regions)
    merged_prohibited = set(values.get("prohibited_regions") or current.prohibited_regions)
    overlap = sorted(merged_permitted & merged_prohibited)
    if overlap:
        raise EngagementError(
            f"region(s) {', '.join(overlap)} would be both permitted and prohibited"
        )

    await repo.update_engagement(session, org_id, engagement_id, values)
    return await _build_detail(session, org_id, engagement_id)


async def get_engagement_detail(
    session: AsyncSession, org_id: UUID, engagement_id: UUID
) -> EngagementDetail:
    if await repo.get_engagement(session, org_id, engagement_id) is None:
        raise EngagementNotFoundError(engagement_id)
    return await _build_detail(session, org_id, engagement_id)


async def list_engagements(
    session: AsyncSession,
    org_id: UUID,
    *,
    customer_id: UUID | None = None,
    states: list[str] | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[EngagementSummary], int]:
    rows = await repo.list_engagements(
        session,
        org_id,
        customer_id=customer_id,
        states=states,
        search=search,
        limit=limit,
        offset=offset,
    )
    total = await repo.count_engagements(
        session, org_id, customer_id=customer_id, states=states, search=search
    )

    engagements = [row[0] for row in rows]
    rollups = await repo.fetch_engagement_rollups(session, org_id, [e.id for e in engagements])

    summaries = [
        EngagementSummary.model_validate(row[0]).model_copy(
            update={
                "customer_display_name": row.customer_display_name,
                "customer_slug": row.customer_slug,
                **rollups.get(row[0].id, {}),
            }
        )
        for row in rows
    ]
    return summaries, total


async def _build_detail(
    session: AsyncSession, org_id: UUID, engagement_id: UUID
) -> EngagementDetail:
    engagement = await repo.get_engagement(session, org_id, engagement_id)
    if engagement is None:
        raise EngagementNotFoundError(engagement_id)

    names = await repo.fetch_customer_names(session, org_id, [engagement.customer_id])
    display_name, customer_slug = names.get(engagement.customer_id, ("", ""))
    service_levels = await repo.list_service_levels(session, org_id, engagement_id)
    agents = await _scoped_agents(session, org_id, engagement_id)

    detail = EngagementDetail.model_validate(engagement)
    return detail.model_copy(
        update={
            "customer_display_name": display_name,
            "customer_slug": customer_slug,
            "service_levels": [ServiceLevelOut.model_validate(s) for s in service_levels],
            "agents": agents,
        }
    )


async def _scoped_agents(
    session: AsyncSession, org_id: UUID, engagement_id: UUID
) -> list[ScopedAgentOut]:
    rows = await repo.list_scoped_agents(session, org_id, engagement_id)

    out: list[ScopedAgentOut] = []
    for row in rows:
        sequence = await repo.version_sequence(session, org_id, row.agent_id)
        behind = _versions_behind(sequence, row.accredited_version_id, row.deployed_version_id)
        severity, reason = classify_drift(
            DriftFacts(
                accredited_version_id=row.accredited_version_id,
                deployed_version_id=row.deployed_version_id,
                uptake=VersionUptake(row.uptake),
                versions_behind=behind,
            )
        )
        out.append(
            ScopedAgentOut(
                id=row.id,
                agent_id=row.agent_id,
                agent_urn=row.agent_urn,
                agent_display_name=row.agent_display_name,
                uptake=VersionUptake(row.uptake),
                in_scope_since=row.in_scope_since,
                accredited_version_id=row.accredited_version_id,
                accredited_semver=row.accredited_semver,
                deployed_version_id=row.deployed_version_id,
                deployed_semver=row.deployed_semver,
                drift=severity,
                drift_reason=reason,
            )
        )
    return out


# ----------------------------------------------------------------------
# Service levels
# ----------------------------------------------------------------------


async def set_service_level(
    session: AsyncSession, org_id: UUID, engagement_id: UUID, payload: ServiceLevelUpsert
) -> ServiceLevelOut:
    if await repo.get_engagement(session, org_id, engagement_id) is None:
        raise EngagementNotFoundError(engagement_id)

    values = payload.model_dump()
    values["kind"] = payload.kind.value
    values["measurement_window"] = payload.measurement_window.value
    values["penalty_basis"] = payload.penalty_basis.value
    row = await repo.upsert_service_level(session, org_id, engagement_id, values)
    return ServiceLevelOut.model_validate(row)


async def drop_service_level(
    session: AsyncSession, org_id: UUID, engagement_id: UUID, slo_id: UUID
) -> None:
    if await repo.get_engagement(session, org_id, engagement_id) is None:
        raise EngagementNotFoundError(engagement_id)
    if await repo.delete_service_level(session, org_id, engagement_id, slo_id) == 0:
        raise ServiceLevelNotFoundError(slo_id)


# ----------------------------------------------------------------------
# Scope
# ----------------------------------------------------------------------


async def scope_agent(
    session: AsyncSession, org_id: UUID, engagement_id: UUID, payload: ScopeAgentRequest
) -> ScopedAgentOut:
    if await repo.get_engagement(session, org_id, engagement_id) is None:
        raise EngagementNotFoundError(engagement_id)

    existing = await repo.get_scoped_agent(session, org_id, engagement_id, payload.agent_id)
    if existing is not None:
        raise AgentAlreadyScopedError(payload.agent_id)

    values = payload.model_dump()
    values["uptake"] = payload.uptake.value
    await repo.insert_scoped_agent(session, org_id, engagement_id, values)
    return await _one_scoped_agent(session, org_id, engagement_id, payload.agent_id)


async def update_scope(
    session: AsyncSession,
    org_id: UUID,
    engagement_id: UUID,
    agent_id: UUID,
    payload: ScopeAgentUpdate,
) -> ScopedAgentOut:
    """Change the approved version, the running version, or the uptake setting.

    Moving ``accredited_version_id`` forward is how an approval is recorded, so this is
    also where drift is cleared. It emits evidence, because "the client approved 2.4 on
    this date" is exactly the sort of claim that has to be provable later.
    """
    if await repo.get_engagement(session, org_id, engagement_id) is None:
        raise EngagementNotFoundError(engagement_id)

    before = await repo.get_scoped_agent(session, org_id, engagement_id, agent_id)
    if before is None:
        raise AgentNotScopedError(agent_id)
    # Read the label before the write; afterwards the old version id is gone and the
    # evidence record would only be able to say what it changed *to*.
    before_semver = (
        await _one_scoped_agent(session, org_id, engagement_id, agent_id)
    ).accredited_semver

    values = payload.model_dump(exclude_unset=True)
    if values.get("uptake") is not None:
        values["uptake"] = values["uptake"].value

    await repo.update_scoped_agent(session, org_id, engagement_id, agent_id, values)
    after = await _one_scoped_agent(session, org_id, engagement_id, agent_id)

    if "accredited_version_id" in values and (
        values["accredited_version_id"] != before.accredited_version_id
    ):
        engagement = await repo.get_engagement(session, org_id, engagement_id)
        await evidence_service.record_one(
            session,
            org_id,
            EvidenceRecord(
                kind=EvidenceKind.ACCREDITATION_DECISION,
                occurred_at=datetime.now(UTC),
                agent_id=agent_id,
                engagement_id=engagement_id,
                customer_id=engagement.customer_id if engagement else None,
                actor="service:engagements",
                action="accredited_version_set",
                outcome=EvidenceOutcome.ALLOW,
                decision=after.accredited_semver,
                reason_code="scope_updated",
                detected_by=DetectedBy.MANUAL,
                detail={
                    "from_semver": before_semver or "none",
                    "to_semver": after.accredited_semver or "none",
                },
            ),
        )

    return after


async def unscope_agent(
    session: AsyncSession, org_id: UUID, engagement_id: UUID, agent_id: UUID
) -> None:
    if await repo.get_engagement(session, org_id, engagement_id) is None:
        raise EngagementNotFoundError(engagement_id)
    removed = await repo.remove_scoped_agent(
        session, org_id, engagement_id, agent_id, datetime.now(UTC)
    )
    if removed == 0:
        raise AgentNotScopedError(agent_id)


async def _one_scoped_agent(
    session: AsyncSession, org_id: UUID, engagement_id: UUID, agent_id: UUID
) -> ScopedAgentOut:
    for scoped in await _scoped_agents(session, org_id, engagement_id):
        if scoped.agent_id == agent_id:
            return scoped
    raise AgentNotScopedError(agent_id)


# ----------------------------------------------------------------------
# Drift report
# ----------------------------------------------------------------------


async def drift_report(
    session: AsyncSession,
    org_id: UUID,
    *,
    customer_id: UUID | None = None,
    engagement_id: UUID | None = None,
    min_severity: DriftSeverity | None = None,
) -> DriftReport:
    """Estate-wide accreditation drift, worst first.

    This is the query an organisation cannot currently answer: every client who is being
    served an agent version they have not signed off, and how bad each case is.
    """
    rows = await repo.fetch_drift_rows(
        session, org_id, customer_id=customer_id, engagement_id=engagement_id
    )
    total = await repo.count_scoped_agents(
        session, org_id, customer_id=customer_id, engagement_id=engagement_id
    )

    # One sequence lookup per distinct agent, not per row: an agent scoped to forty
    # clients has the same version history for all of them.
    sequences: dict[UUID, list[UUID]] = {}

    items: list[DriftItem] = []
    for row in rows:
        if row.agent_id not in sequences:
            sequences[row.agent_id] = await repo.version_sequence(session, org_id, row.agent_id)
        behind = _versions_behind(
            sequences[row.agent_id], row.accredited_version_id, row.deployed_version_id
        )
        severity, reason = classify_drift(
            DriftFacts(
                accredited_version_id=row.accredited_version_id,
                deployed_version_id=row.deployed_version_id,
                uptake=VersionUptake(row.uptake),
                versions_behind=behind,
                customer_criticality=str(row.customer_criticality),
            )
        )
        if severity is DriftSeverity.NONE:
            continue

        items.append(
            DriftItem(
                engagement_id=row.engagement_id,
                engagement_name=row.engagement_name,
                customer_id=row.customer_id,
                customer_display_name=row.customer_display_name,
                customer_criticality=str(row.customer_criticality),
                agent_id=row.agent_id,
                agent_urn=row.agent_urn,
                agent_display_name=row.agent_display_name,
                accredited_semver=row.accredited_semver,
                accredited_at=row.accredited_at,
                deployed_semver=row.deployed_semver,
                deployed_at=row.deployed_at,
                versions_behind=behind,
                uptake=VersionUptake(row.uptake),
                severity=severity,
                reason=reason,
            )
        )

    if min_severity is not None:
        items = [i for i in items if _SEVERITY_RANK[i.severity] <= _SEVERITY_RANK[min_severity]]

    items.sort(
        key=lambda i: (
            _SEVERITY_RANK[i.severity],
            -i.versions_behind,
            i.customer_display_name,
        )
    )

    return DriftReport(
        items=items,
        total_in_scope=total,
        clean=max(total - len(items), 0),
        critical=sum(1 for i in items if i.severity is DriftSeverity.CRITICAL),
        material=sum(1 for i in items if i.severity is DriftSeverity.MATERIAL),
        informational=sum(1 for i in items if i.severity is DriftSeverity.INFORMATIONAL),
    )
