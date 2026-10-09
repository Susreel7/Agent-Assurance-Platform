"""The landing page, assembled from the domains that own the underlying facts.

This module has no repository and owns no tables, which is why it is short of the usual
domain shape. It is a read-only composition: every number here belongs to another domain
and is fetched through that domain's service, so there is exactly one implementation of
"how many agents are accredited" and this is not it.

What it adds is the join nothing else can make. `operations` knows what each agent cost
and how often it failed; `assurance`, `accreditation` and `engagements` know whether it
was approved and whether it drifted. Neither can see the other — the dependency rule
points one way and `operations` sits to the left of all of them. Putting the two halves
on one row is the whole reason this file exists, and it is the difference between a
runtime dashboard and an assurance one.

The console called `/v1/dashboard/summary` from the day the screen was written and no
such route ever existed. In mock mode the page rendered fixtures and looked complete; in
live mode it showed an error, which is how the product's first screen was broken for as
long as it had one. See D-036.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.accreditation import service as accreditation_svc
from app.domains.assurance import service as assurance_svc
from app.domains.assurance.schemas import FindingState, SeverityCounts
from app.domains.bom import service as bom_svc
from app.domains.engagements import service as engagements_svc
from app.domains.engagements.schemas import DriftReport
from app.domains.home.schemas import (
    AgentHealth,
    AgentOpsRow,
    AttentionItem,
    ComplianceBar,
    EstateTotals,
    HealthMix,
    HomeSummary,
)
from app.domains.operations import service as operations_svc
from app.domains.operations.schemas import OperationsSnapshot
from app.domains.registry import service as registry_svc
from app.domains.registry.schemas import AgentSummary
from app.domains.releases import service as releases_svc
from app.domains.sla import service as sla_svc

# How many rows the attention list may hold. Past roughly this many, a queue stops being
# something anybody works through and becomes wallpaper, and the ordering below is what
# decides which ones matter — so truncating is better than scrolling.
_MAX_ATTENTION = 8

# How many agents the landing page table carries. The estate screen is where someone
# goes to see all of them; this is the busiest handful.
_MAX_AGENTS = 12

_APPROVED = "approved"
_SUBMITTED = "submitted"

# Open, for the purposes of "does anybody still have to do something about this".
# `accepted` is excluded deliberately: somebody looked and decided to live with it, which
# is a closed decision even though the condition persists.
#
# Built from the enum rather than written as strings. The first version of this list had
# an `in_progress` in it, which is not a state this product has — a value the database
# rejected at query time rather than a value anything would have caught earlier.
_OPEN_FINDING_STATES = [FindingState.OPEN.value, FindingState.TRIAGED.value]

# Below this, an agent is failing often enough that somebody should look. Set against
# the estate's own behaviour rather than an industry figure: the seeded fleet sits near
# 98%, and a threshold nothing ever crosses is decoration.
_SUCCESS_WARNING_PCT = 97.0
_SUCCESS_AT_RISK_PCT = 90.0


async def build_home_summary(session: AsyncSession, org_id: UUID, days: int = 30) -> HomeSummary:
    drift = await engagements_svc.drift_report(session, org_id)
    findings = await assurance_svc.severity_counts(session, org_id, open_only=True)
    agents, agents_total = await registry_svc.list_agents(session, org_id, limit=500)
    _, production_total = await registry_svc.list_agents(
        session, org_id, lifecycle_states=["production"], limit=1
    )
    accreditations, _ = await accreditation_svc.list_accreditation_summaries(
        session, org_id, limit=500
    )
    releases, _ = await releases_svc.list_releases(session, org_id, limit=6)

    operations = await operations_svc.build_snapshot(session, org_id, days)
    activity = await operations_svc.agent_activity_index(session, org_id, days)

    # Findings per agent, so a row can say "two open, one critical" instead of only
    # repeating the estate total. Listed rather than counted per agent because one query
    # returning five hundred rows beats five hundred queries returning one.
    open_findings = await assurance_svc.list_findings(
        session, org_id, state=_OPEN_FINDING_STATES, limit=500
    )
    findings_by_agent: dict[UUID, list[str]] = {}
    for finding in open_findings.items:
        if finding.agent_id is not None:
            findings_by_agent.setdefault(finding.agent_id, []).append(str(finding.severity))

    accreditation_by_agent = {a.agent_id: str(a.state) for a in accreditations}
    drifted_agents = {item.agent_id for item in drift.items if item.severity != "informational"}

    rows = await _agent_rows(
        session,
        org_id,
        agents=agents,
        activity=activity,
        findings_by_agent=findings_by_agent,
        accreditation_by_agent=accreditation_by_agent,
        drifted_agents=drifted_agents,
    )

    accredited = sum(1 for a in accreditations if a.state == _APPROVED)
    waiting = [a for a in accreditations if a.state == _SUBMITTED]
    slo_pct = await _estate_attainment(session, org_id)

    return HomeSummary(
        window_days=operations.window_days,
        generated_at=datetime.now(tz=UTC),
        attention=_attention(drift, findings, len(waiting), operations)[:_MAX_ATTENTION],
        estate=EstateTotals(
            agents_total=agents_total,
            agents_in_production=production_total,
            agents_accredited=accredited,
            agents_unaccredited=max(agents_total - accredited, 0),
            agents_drifted=len(drifted_agents),
            open_findings=open_findings.total,
            open_critical_findings=findings.critical,
            approvals_waiting=len(waiting),
            slos_meeting_target_pct=slo_pct,
        ),
        health=_health_mix(rows),
        compliance=_compliance(
            agents_total=agents_total,
            accredited=accredited,
            drifted=len(drifted_agents),
            agents_with_findings=len(findings_by_agent),
            undeclared_tools=operations.tools.undeclared,
            tools_total=len(operations.tools.items),
            slo_pct=slo_pct,
        ),
        operations=operations,
        # Busiest first: the landing page should open on what is moving, and an idle
        # agent with nothing wrong is not what anybody came to look at.
        agents=sorted(rows, key=lambda r: (-r.runs, r.display_name))[:_MAX_AGENTS],
        recent_releases=releases,
    )


async def _agent_rows(
    session: AsyncSession,
    org_id: UUID,
    *,
    agents: list[AgentSummary],
    activity: dict[UUID, dict[str, Any]],
    findings_by_agent: dict[UUID, list[str]],
    accreditation_by_agent: dict[UUID, str],
    drifted_agents: set[UUID],
) -> list[AgentOpsRow]:
    counts = await bom_svc.component_counts_by_agent(session, org_id)
    no_bom = {"mcp_servers": 0, "tools": 0}

    rows: list[AgentOpsRow] = []
    for agent in agents:
        stats = activity.get(agent.id, {})
        severities = findings_by_agent.get(agent.id, [])
        accreditation = accreditation_by_agent.get(agent.id)
        lifecycle = str(agent.lifecycle_state)
        drifted = agent.id in drifted_agents
        runs = int(stats.get("runs", 0))
        success = float(stats.get("success_rate_pct", 100.0))
        bom = counts.get(agent.id, no_bom)

        rows.append(
            AgentOpsRow(
                id=agent.id,
                display_name=agent.display_name,
                urn=agent.urn,
                lifecycle_state=lifecycle,
                runtime_framework=agent.runtime_framework,
                semver=agent.current_semver,
                health=_health_of(
                    lifecycle=lifecycle,
                    severities=severities,
                    drifted=drifted,
                    accreditation=accreditation,
                    success_rate_pct=success,
                    runs=runs,
                ),
                accreditation_state=accreditation,
                drifted=drifted,
                open_findings=len(severities),
                open_critical_findings=sum(1 for s in severities if s == "critical"),
                runs=runs,
                success_rate_pct=success,
                cost_micros=int(stats.get("cost_micros", 0)),
                p95_duration_ms=int(stats.get("p95_duration_ms", 0)),
                escalations=int(stats.get("escalations", 0)),
                running_now=int(stats.get("running_now", 0)),
                last_run_at=stats.get("last_run_at"),
                mcp_servers=bom["mcp_servers"],
                tools=bom["tools"],
            )
        )
    return rows


def _health_of(
    *,
    lifecycle: str,
    severities: list[str],
    drifted: bool,
    accreditation: str | None,
    success_rate_pct: float,
    runs: int,
) -> AgentHealth:
    """One word per agent, from governance state and runtime behaviour together.

    The ordering encodes a judgement worth stating plainly: an unapproved agent serving
    production is `critical` even if it is running perfectly, because "working" and
    "allowed" are different questions and this product exists to keep them apart. A
    purely operational dashboard would show that agent as green.

    Reliability alone never reaches `critical`. A failing agent is visible in a dozen
    other places and usually already has someone on it; the point of this column is to
    surface what nothing else is watching.
    """
    if "critical" in severities:
        return AgentHealth.CRITICAL
    if lifecycle == "production" and accreditation != _APPROVED:
        return AgentHealth.CRITICAL
    if drifted or "high" in severities or success_rate_pct < _SUCCESS_AT_RISK_PCT:
        return AgentHealth.AT_RISK
    if severities or (runs and success_rate_pct < _SUCCESS_WARNING_PCT):
        return AgentHealth.WARNING
    return AgentHealth.HEALTHY


def _health_mix(rows: list[AgentOpsRow]) -> HealthMix:
    mix = HealthMix()
    for row in rows:
        match row.health:
            case AgentHealth.CRITICAL:
                mix.critical += 1
            case AgentHealth.AT_RISK:
                mix.at_risk += 1
            case AgentHealth.WARNING:
                mix.warning += 1
            case AgentHealth.HEALTHY:
                mix.healthy += 1
    return mix


def _compliance(
    *,
    agents_total: int,
    accredited: int,
    drifted: int,
    agents_with_findings: int,
    undeclared_tools: int,
    tools_total: int,
    slo_pct: float,
) -> list[ComplianceBar]:
    """Four ratios, each with the numbers behind it and a sentence saying what it means.

    `explain` is not decoration. Every one of these is the sort of figure that ends up in
    a board pack, and a percentage whose definition lives only in the code that computed
    it will eventually be quoted to mean something it does not.
    """

    def bar(ident: str, label: str, covered: int, applicable: int, explain: str) -> ComplianceBar:
        pct = round(covered * 100.0 / applicable, 1) if applicable else 100.0
        return ComplianceBar(
            id=ident,
            label=label,
            covered=covered,
            applicable=applicable,
            pct=pct,
            explain=explain,
        )

    return [
        bar(
            "accreditation",
            "Approved to run",
            accredited,
            agents_total,
            "Agents with a signed-off accreditation, out of every agent in the registry.",
        ),
        bar(
            "no_drift",
            "Running what was approved",
            max(agents_total - drifted, 0),
            agents_total,
            "Agents whose live version matches the one their client agreed to.",
        ),
        bar(
            "clean",
            "No open findings",
            max(agents_total - agents_with_findings, 0),
            agents_total,
            "Agents with nothing outstanding from a scan, probe or review.",
        ),
        bar(
            "declared_tools",
            "Tools declared",
            max(tools_total - undeclared_tools, 0),
            tools_total,
            "Tools and MCP servers where every agent calling them declared them first.",
        ),
    ]


def _attention(
    drift: DriftReport,
    findings: SeverityCounts,
    waiting: int,
    operations: OperationsSnapshot,
) -> list[AttentionItem]:
    """The queue, ordered by what it costs to ignore each item."""
    now = datetime.now(tz=UTC)
    items: list[AttentionItem] = []

    # Drift first, and by severity. An agent serving a client a version that client never
    # agreed to is the failure this product exists to prevent, so it outranks anything
    # else that could be on this list.
    for item in drift.items:
        if item.severity == "informational":
            continue
        items.append(
            AttentionItem(
                id=f"drift:{item.engagement_id}:{item.agent_id}",
                title=f"{item.customer_display_name} is running an unapproved version of "
                f"{item.agent_display_name}",
                consequence=(
                    f"They approved {item.accredited_semver or 'nothing'} and are being "
                    f"served {item.deployed_semver or 'an unknown version'}."
                ),
                href=f"/engagements/{item.engagement_id}",
                severity="critical",
                occurred_at=item.deployed_at or now,
            )
        )

    critical = findings.critical
    if critical:
        items.append(
            AttentionItem(
                id="findings:critical",
                title=f"{critical} critical {'issue' if critical == 1 else 'issues'} open",
                consequence="Critical issues block approval and may already affect a client.",
                href="/findings",
                severity="critical",
                occurred_at=now,
            )
        )

    undeclared = operations.tools.undeclared
    if undeclared:
        items.append(
            AttentionItem(
                id="tools:undeclared",
                title=f"{undeclared} {'tool is' if undeclared == 1 else 'tools are'} being "
                f"called without being declared",
                consequence=(
                    "An agent is using a capability its approved descriptor never "
                    "mentioned, so nobody reviewed it."
                ),
                href="/tools?declared=false",
                severity="warning",
                occurred_at=now,
            )
        )

    if waiting:
        items.append(
            AttentionItem(
                id="accreditations:submitted",
                title=f"{waiting} "
                f"{'approval is' if waiting == 1 else 'approvals are'} waiting on a decision",
                consequence="Nothing can go live for these clients until somebody signs them off.",
                href="/accreditations?state=submitted",
                severity="warning",
                occurred_at=now,
            )
        )

    escalations = operations.escalations
    if escalations:
        items.append(
            AttentionItem(
                id="runs:escalated",
                title=f"{escalations} runs were handed to a person",
                consequence="Each one is work an agent was expected to finish on its own.",
                href="/runs?escalated=true",
                severity="info",
                occurred_at=now,
            )
        )

    return items


# Service levels whose measurement is already a percentage and where more is better.
# Everything else — the latency and resolution-time kinds — is measured in milliseconds
# or hours, and is met by coming in *under* its target.
_HIGHER_IS_BETTER = ("availability", "success_rate")


async def _estate_attainment(session: AsyncSession, org_id: UUID) -> float:
    """The share of service levels currently meeting their target.

    Not the mean of their attainments, which is what this computed before and which was
    wrong in a way worth recording: `compute_attainment` returns the measured value in
    the service level's own unit, so averaging an availability of 99.9 with a p95 latency
    of 1,200 ms produced 1173.1 and rendered as "1173.1%" on the landing page. Mixing
    units in a mean is not a rounding problem, it is a category error, and no amount of
    formatting fixes it.

    Counting targets met is unit-free, cannot exceed 100, and answers the question the
    number is on the page for. It is coarser — a service level missed by a hair counts
    the same as one missed by a mile — and the service levels screen is where that
    difference is visible.

    A service level with no measurements yet is excluded rather than counted as missed:
    nothing has been observed, which is not the same as having fallen short. Nothing
    promised at all reads as 100, because a fresh install should not open on a failure.
    """
    slos = await sla_svc.list_slos(session, org_id)
    if not slos:
        return 100.0

    measured = 0
    met = 0
    for slo in slos:
        attainment = await sla_svc.compute_attainment(session, org_id, slo.id)
        if attainment is None:
            continue
        measured += 1
        higher_is_better = str(slo.kind) in _HIGHER_IS_BETTER
        target = float(slo.target)
        value = float(attainment)
        if (value >= target) if higher_is_better else (value <= target):
            met += 1

    if not measured:
        return 100.0
    return round(met * 100.0 / measured, 1)
