"""Synthetic demo estate.

    python -m seed.generate --agents 40 --teams 5 --days 30

Builds a plausible IT-services fleet: client customers with engagements and service
levels, a fleet of agents owned by delivery teams, a version history per agent, releases
whose verdicts come out of the real materiality engine, accreditations in several states,
an evidence chain that has actually been sealed, findings, SLOs with measurements and
breaches, and a dependency graph.

Two rules shape the whole file.

**It calls services, never repositories.** A seed built on raw inserts would populate
tables that no code path can produce, so the console would show an estate the product
cannot actually create. Going through `service.py` means every row here obeys the same
validation, ownership and state-machine rules a real user is held to — and a seed run is
therefore also a broad smoke test of the write path. When the seed breaks, that is
usually the product telling you something.

**It is deterministic.** Same seed, same estate, down to the version digests. A demo you
can rehearse is worth more than a fresh random one, and a bug reproduces.

The one exception to the first rule is the organisation lookup. No domain owns
`organizations` — there is no provisioning path at all (Q-009) — so this reads that one
table through the ORM model directly.
"""

from __future__ import annotations

import argparse
import asyncio
import random
import sys
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models.registry import Organization
from app.db.session import admin_session, dispose_engine, tenant_session
from app.domains.accreditation import schemas as acc_schemas
from app.domains.accreditation import service as accreditation_svc
from app.domains.assurance import repository as assurance_repo
from app.domains.assurance import schemas as assurance_schemas
from app.domains.assurance import service as assurance_svc
from app.domains.bom import service as bom_svc
from app.domains.customers import schemas as customer_schemas
from app.domains.customers import service as customers_svc
from app.domains.engagements import schemas as engagement_schemas
from app.domains.engagements import service as engagements_svc
from app.domains.evidence import schemas as evidence_schemas
from app.domains.evidence import service as evidence_svc
from app.domains.frameworks import schemas as framework_schemas
from app.domains.frameworks import service as frameworks_svc
from app.domains.graph import service as graph_svc
from app.domains.registry import schemas as registry_schemas
from app.domains.registry import service as registry_svc
from app.domains.releases import schemas as release_schemas
from app.domains.releases import service as releases_svc
from app.domains.sla import schemas as sla_schemas
from app.domains.sla import service as sla_svc
from seed.operations import backfill_run_steps, run_steps_missing, seed_operations

DEFAULT_SEED = 20260913

# --------------------------------------------------------------------------------------
# The narrative
# --------------------------------------------------------------------------------------
# Fixed rather than generated. A demo needs names a human can hold in their head and
# refer back to, and the interesting part of this estate is the relationships between
# these rows, not how many of them there are.


@dataclass(frozen=True)
class CustomerSpec:
    slug: str
    legal_name: str
    display_name: str
    sector: customer_schemas.Sector
    criticality: customer_schemas.CriticalityTier
    home: str
    operating: tuple[str, ...]
    regions: tuple[str, ...]
    cross_border: engagement_schemas.CrossBorderTransfer
    data_classes: tuple[str, ...]
    reviewer: str
    dpo: str


CUSTOMERS: tuple[CustomerSpec, ...] = (
    CustomerSpec(
        slug="northwind-bank",
        legal_name="Northwind Retail Bank plc",
        display_name="Northwind Bank",
        sector=customer_schemas.Sector.FINANCIAL_SERVICES,
        criticality=customer_schemas.CriticalityTier.TIER_1,
        home="GB",
        operating=("GB", "IE"),
        regions=("eu-west-2",),
        cross_border=engagement_schemas.CrossBorderTransfer.PROHIBITED,
        data_classes=("customer_pii", "financial_account"),
        reviewer="person:r.mehta@northwind-bank.example",
        dpo="person:dpo@northwind-bank.example",
    ),
    CustomerSpec(
        slug="helvetia-insure",
        legal_name="Helvetia Insurance AG",
        display_name="Helvetia Insure",
        sector=customer_schemas.Sector.INSURANCE,
        criticality=customer_schemas.CriticalityTier.TIER_1,
        home="CH",
        operating=("CH", "DE", "AT"),
        regions=("eu-central-1", "eu-west-1"),
        cross_border=engagement_schemas.CrossBorderTransfer.PERMITTED_WITH_SAFEGUARDS,
        data_classes=("customer_pii", "health_data"),
        reviewer="person:s.brunner@helvetia-insure.example",
        dpo="person:datenschutz@helvetia-insure.example",
    ),
    CustomerSpec(
        slug="mercia-nhs-trust",
        legal_name="Mercia University Hospitals NHS Trust",
        display_name="Mercia NHS Trust",
        sector=customer_schemas.Sector.HEALTHCARE,
        criticality=customer_schemas.CriticalityTier.TIER_1,
        home="GB",
        operating=("GB",),
        regions=("eu-west-2",),
        cross_border=engagement_schemas.CrossBorderTransfer.PROHIBITED,
        data_classes=("patient_record", "customer_pii"),
        reviewer="person:ig.lead@mercia-nhs.example",
        dpo="person:caldicott@mercia-nhs.example",
    ),
    CustomerSpec(
        slug="vehicle-services-agency",
        legal_name="Vehicle Services Agency",
        display_name="Vehicle Services",
        sector=customer_schemas.Sector.PUBLIC_SECTOR,
        criticality=customer_schemas.CriticalityTier.TIER_2,
        home="GB",
        operating=("GB",),
        regions=("eu-west-2",),
        cross_border=engagement_schemas.CrossBorderTransfer.PERMITTED_WITH_CONSENT,
        data_classes=("customer_pii",),
        reviewer="person:assurance@vsa.gov.example",
        dpo="person:dpo@vsa.gov.example",
    ),
    CustomerSpec(
        slug="linden-retail",
        legal_name="Linden Retail Group Limited",
        display_name="Linden Retail",
        sector=customer_schemas.Sector.RETAIL,
        criticality=customer_schemas.CriticalityTier.TIER_3,
        home="GB",
        operating=("GB", "FR", "ES"),
        regions=("eu-west-1", "eu-west-2"),
        cross_border=engagement_schemas.CrossBorderTransfer.PERMITTED,
        data_classes=("customer_pii", "order_history"),
        reviewer="person:infosec@linden-retail.example",
        dpo="person:privacy@linden-retail.example",
    ),
)

TEAMS: tuple[tuple[str, str], ...] = (
    ("Claims Platform", "person:a.okafor@northwind-digital.example"),
    ("Underwriting AI", "person:l.tanaka@northwind-digital.example"),
    ("Customer Operations", "person:m.dubois@northwind-digital.example"),
    ("Risk and Controls", "person:p.nayar@northwind-digital.example"),
    ("Service Desk Automation", "person:j.keane@northwind-digital.example"),
    ("Payments Intelligence", "person:h.olsen@northwind-digital.example"),
    ("Clinical Coding", "person:s.rahman@northwind-digital.example"),
)

# Agent archetypes. The purpose of each is a real job an IT services company would
# actually build an agent for, because "agent-17" tells a viewer nothing.
ARCHETYPES: tuple[tuple[str, str, str], ...] = (
    ("claims-triage", "Claims Triage", "Classifies inbound claims and routes by severity."),
    ("fnol-intake", "FNOL Intake", "Captures first notification of loss from voice and email."),
    ("policy-qa", "Policy Question Answering", "Answers cover questions from policy wordings."),
    ("fraud-signal", "Fraud Signal Review", "Flags claims matching known fraud patterns."),
    ("subrogation", "Subrogation Finder", "Identifies recoverable third-party liability."),
    ("underwriting-assist", "Underwriting Assistant", "Drafts risk summaries for underwriters."),
    ("kyc-refresh", "KYC Refresh", "Re-verifies customer identity documents on renewal."),
    ("dispute-resolution", "Dispute Resolution", "Prepares case files for payment disputes."),
    ("arrears-outreach", "Arrears Outreach", "Drafts forbearance options for accounts in arrears."),
    (
        "complaint-router",
        "Complaint Router",
        "Classifies complaints against regulatory categories.",
    ),
    ("service-desk-l1", "Service Desk Tier 1", "Resolves password and access requests."),
    ("change-risk", "Change Risk Scoring", "Scores change requests before CAB review."),
    ("incident-summary", "Incident Summariser", "Writes incident timelines from telemetry."),
    ("clinical-coding", "Clinical Coding Assistant", "Suggests ICD-10 codes from discharge notes."),
    (
        "appointment-triage",
        "Appointment Triage",
        "Prioritises referrals against clinical criteria.",
    ),
    ("supplier-onboard", "Supplier Onboarding", "Checks supplier documents against policy."),
    ("contract-review", "Contract Review", "Extracts obligations and liability caps."),
    ("invoice-match", "Invoice Matching", "Reconciles invoices to purchase orders."),
    ("demand-forecast", "Demand Forecasting", "Projects stock requirements per store."),
    ("returns-assess", "Returns Assessment", "Decides refund eligibility from returns data."),
)

MODEL_CHOICES: tuple[dict[str, str], ...] = (
    {
        "provider": "anthropic",
        "family": "claude",
        "id": "claude-sonnet-4-5",
        "hosting": "cloud_managed",
        "data_retention": "zero_retention",
    },
    {
        "provider": "openai",
        "family": "gpt",
        "id": "gpt-4.1",
        "hosting": "cloud_managed",
        "data_retention": "zero_retention",
    },
    {
        "provider": "azure_openai",
        "family": "gpt",
        "id": "gpt-4o",
        "hosting": "cloud_managed",
        "data_retention": "thirty_days",
    },
    {
        "provider": "self_hosted",
        "family": "llama",
        "id": "llama-3.3-70b",
        "hosting": "self_hosted",
        "data_retention": "zero_retention",
    },
    {
        "provider": "mistral",
        "family": "mistral",
        "id": "mistral-large-2",
        "hosting": "cloud_managed",
        "data_retention": "zero_retention",
    },
)

TOOL_CHOICES: tuple[dict[str, str], ...] = (
    {"name": "policy_lookup", "kind": "http", "effect": "read"},
    {"name": "claims_db", "kind": "database", "effect": "read"},
    {"name": "document_store", "kind": "http", "effect": "read"},
    {"name": "crm_search", "kind": "http", "effect": "read"},
    {"name": "notify_customer", "kind": "http", "effect": "write"},
    {"name": "ticket_update", "kind": "http", "effect": "write"},
    {"name": "payment_initiate", "kind": "http", "effect": "write"},
)

# What the agents are built on. LangGraph leads because that is what most teams
# reaching for a graph runtime pick, and a realistic estate is never all one thing --
# the frameworks panel is only worth having if it can show a migration in progress.
FRAMEWORK_CHOICES: tuple[str, ...] = ("langgraph", "langgraph", "langgraph", "cursor-sdk")
FRAMEWORK_TAIL: tuple[str, ...] = ("crewai", "autogen", "semantic-kernel", "llamaindex")

# MCP servers, declared as URLs because that is what the AAP descriptor holds -- see
# `references.mcp_servers` in the schema. The last path segment is the name the runtime
# reports, and reconciling those two is the job `operations.service` does.
MCP_SERVERS: tuple[dict[str, Any], ...] = (
    {"url": "https://mcp.northwind.internal/github", "tools": ("search_code", "get_file")},
    {"url": "https://mcp.northwind.internal/postgres", "tools": ("query", "describe_table")},
    {"url": "https://mcp.northwind.internal/confluence", "tools": ("search_pages", "get_page")},
    {"url": "https://mcp.northwind.internal/jira", "tools": ("search_issues", "create_issue")},
    {"url": "https://mcp.northwind.internal/slack", "tools": ("post_message", "read_channel")},
    {"url": "https://mcp.northwind.internal/filesystem", "tools": ("read_file", "list_dir")},
    {"url": "https://mcp.vendor.example.com/stripe", "tools": ("create_charge", "get_balance")},
)


def mcp_server_name(url: str) -> str:
    """The name a runtime reports for a server declared at this URL.

    The descriptor identifies an MCP server by URL; an SDK reports whatever the server
    calls itself, which in practice is the last path segment. Both the seed and the
    reconciliation in `operations.service` derive it the same way, so the demo estate
    exercises the real matching rather than a shortcut around it.
    """
    return url.rstrip("/").rsplit("/", 1)[-1]


CAPABILITY_CHOICES: tuple[dict[str, str], ...] = (
    {"name": "classify_request", "effect": "read", "human_approval": "none"},
    {"name": "summarise_case", "effect": "read", "human_approval": "none"},
    {"name": "draft_response", "effect": "write", "human_approval": "required"},
    {"name": "update_record", "effect": "write", "human_approval": "required"},
    {"name": "authorise_payment", "effect": "write", "human_approval": "required"},
)

# --------------------------------------------------------------------------------------
# Descriptor construction
# --------------------------------------------------------------------------------------


def build_descriptor(
    *,
    urn: str,
    display_name: str,
    semver: str,
    team: str,
    accountable: str,
    models: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    capabilities: list[dict[str, Any]],
    autonomy: str,
    regions: list[str],
    cross_border: str,
    data_classes: list[str],
    retention_days: int,
    lifecycle: str,
    authentication: str,
    framework: str,
    mcp_servers: list[dict[str, Any]],
) -> dict[str, Any]:
    """An AAP 0.1 descriptor.

    Shaped by hand rather than by a factory with defaults, because `publish_version`
    validates against the published schema and a silently-wrong default here would show
    up as a confusing validation error thirty frames away.
    """
    return {
        "aap_version": "0.1",
        "agent": {
            "urn": urn,
            "display_name": display_name,
            "version": semver,
            "lifecycle_state": lifecycle,
        },
        "accountability": {
            "owning_team": team,
            "accountable_person": accountable,
        },
        "runtime": {
            "framework": framework,
            "deployment": "kubernetes",
            "autonomy": autonomy,
        },
        "references": {
            "otel_service_name": urn.rsplit(":", 2)[-2],
            "mcp_servers": mcp_servers,
        },
        "models": models,
        "data": {
            "classes": data_classes,
            "retention_days": retention_days,
            "residency": {
                "permitted_regions": regions,
                "cross_border": cross_border,
            },
        },
        "capabilities": capabilities,
        "tools": tools,
        "security": {
            "authentication": authentication,
            "secrets_source": "vault",
        },
    }


# --------------------------------------------------------------------------------------
# Plan
# --------------------------------------------------------------------------------------


@dataclass
class AgentPlan:
    """One agent's whole history, decided before anything is written.

    Deciding the shape up front keeps the randomness in one place. The write phase then
    has no choices left to make, which is what makes a failure mid-run easy to read.
    """

    urn: str
    display_name: str
    description: str
    team: str
    accountable: str
    lifecycle: registry_schemas.LifecycleState
    customer: CustomerSpec
    descriptors: list[tuple[str, dict[str, Any], datetime]] = field(default_factory=list)

    # What this agent is built on and what it talks to. Held on the plan because the
    # operations phase generates runs and tool calls from the same facts the descriptor
    # declares -- otherwise the demo estate would report every tool as undeclared and
    # the reconciliation would look broken rather than clean.
    framework: str = "langgraph"
    mcp_servers: list[dict[str, Any]] = field(default_factory=list)
    native_tools: list[str] = field(default_factory=list)

    # Filled in as rows are written.
    agent_id: UUID | None = None
    version_ids: list[UUID] = field(default_factory=list)


def plan_agents(rng: random.Random, count: int, teams: int, days: int) -> list[AgentPlan]:
    now = datetime.now(UTC)
    team_pool = TEAMS[: max(1, min(teams, len(TEAMS)))]
    plans: list[AgentPlan] = []

    for index in range(count):
        archetype, title, description = ARCHETYPES[index % len(ARCHETYPES)]
        team, accountable = team_pool[index % len(team_pool)]
        customer = CUSTOMERS[index % len(CUSTOMERS)]
        generation = index // len(ARCHETYPES) + 1
        suffix = "" if generation == 1 else f"-{generation}"

        # Most of an estate is in production; the tail is where it is being built.
        lifecycle = rng.choices(
            [
                registry_schemas.LifecycleState.PRODUCTION,
                registry_schemas.LifecycleState.STAGING,
                registry_schemas.LifecycleState.TEST,
                registry_schemas.LifecycleState.DEV,
            ],
            weights=[60, 15, 10, 15],
        )[0]

        urn = f"urn:aap:northwind:{archetype}{suffix}:{customer.regions[0]}"
        plan = AgentPlan(
            urn=urn,
            display_name=f"{title}{'' if generation == 1 else f' (gen {generation})'}",
            description=description,
            team=team,
            accountable=accountable,
            lifecycle=lifecycle,
            customer=customer,
        )

        # Most of the estate is LangGraph, with a minority on something else. One agent
        # in six comes from the long tail, which is enough for the frameworks panel to
        # show a real distribution rather than a single bar.
        plan.framework = (
            rng.choice(FRAMEWORK_TAIL) if index % 6 == 5 else rng.choice(FRAMEWORK_CHOICES)
        )
        plan.mcp_servers = [dict(s) for s in rng.sample(MCP_SERVERS, k=rng.randint(1, 4))]

        # A version history: one to four releases spread over the window, oldest first.
        version_count = rng.choices([1, 2, 3, 4], weights=[15, 35, 35, 15])[0]
        models = [{"role": "primary", **rng.choice(MODEL_CHOICES)}]
        tools = list(rng.sample(TOOL_CHOICES, k=rng.randint(1, 3)))
        capabilities = list(rng.sample(CAPABILITY_CHOICES, k=rng.randint(1, 3)))
        autonomy = rng.choices(
            ["supervised", "human_in_the_loop", "semi_autonomous"], weights=[50, 30, 20]
        )[0]
        authentication = "oauth2_client_credentials"
        retention_days = rng.choice([30, 90, 180, 365])

        for step in range(version_count):
            semver = f"{1 + step // 3}.{step % 3}.0"
            age = days - int(days * (step + 1) / (version_count + 1))
            published_at = now - timedelta(days=age, hours=rng.randint(0, 23))

            # Later versions drift: that is what gives the releases screen something to
            # show. Each mutation is one the materiality engine has an opinion about.
            if step == 1 and rng.random() < 0.5:
                models = [{"role": "primary", **rng.choice(MODEL_CHOICES)}]
            if step == 2 and rng.random() < 0.5:
                tools = [*tools, dict(rng.choice(TOOL_CHOICES))]
            if step == 2 and rng.random() < 0.3:
                autonomy = "semi_autonomous"
            if step == 3 and rng.random() < 0.4:
                capabilities = [*capabilities, dict(CAPABILITY_CHOICES[-1])]

            # Deduplicate: sampling with replacement above can repeat a tool name, and
            # the schema treats the list as a set of distinct names.
            unique_tools = list({t["name"]: t for t in tools}.values())
            unique_caps = list({c["name"]: c for c in capabilities}.values())

            for model in models:
                model["endpoint_region"] = plan.customer.regions[0]

            descriptor = build_descriptor(
                urn=urn,
                display_name=plan.display_name,
                semver=semver,
                team=team,
                accountable=accountable,
                models=[dict(m) for m in models],
                tools=[dict(t) for t in unique_tools],
                capabilities=[dict(c) for c in unique_caps],
                autonomy=autonomy,
                regions=list(customer.regions),
                cross_border=customer.cross_border.value,
                data_classes=list(customer.data_classes),
                retention_days=retention_days,
                lifecycle=lifecycle.value,
                authentication=authentication,
                framework=plan.framework,
                mcp_servers=[{"url": s["url"]} for s in plan.mcp_servers],
            )
            plan.descriptors.append((semver, descriptor, published_at))

        # The tool names the final descriptor declares. The operations phase calls these
        # and, for a small minority of agents, one that is not on the list -- which is
        # what puts a genuine undeclared-tool finding in front of whoever opens the demo.
        plan.native_tools = [str(t["name"]) for t in unique_tools]

        plans.append(plan)

    return plans


# --------------------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------------------


class Log:
    """Progress on stdout. Quiet mode still reports the summary and any failure."""

    def __init__(self, *, quiet: bool) -> None:
        self.quiet = quiet
        self.counts: dict[str, int] = {}

    def phase(self, title: str) -> None:
        if not self.quiet:
            print(f"\n{title}")

    def line(self, text: str) -> None:
        if not self.quiet:
            print(f"  {text}")

    def tally(self, what: str, n: int = 1) -> None:
        self.counts[what] = self.counts.get(what, 0) + n

    def summary(self) -> None:
        print("\nSeeded:")
        for what in sorted(self.counts):
            print(f"  {self.counts[what]:>6}  {what}")


# --------------------------------------------------------------------------------------
# Phases
# --------------------------------------------------------------------------------------


async def resolve_org_id() -> UUID:
    """The tenant everything is seeded into.

    Reads `organizations` directly because no domain owns it — see the module docstring
    and Q-009. Migration 0001 seeds the row named by `default_org_slug`.
    """
    slug = get_settings().default_org_slug
    async with admin_session() as session:
        found = await session.execute(select(Organization.id).where(Organization.slug == slug))
        org_id = found.scalar_one_or_none()

    if org_id is None:
        raise SystemExit(
            f"organisation {slug!r} does not exist. Run `alembic upgrade head` first, "
            f"or set AAP_DEFAULT_ORG_SLUG to an organisation that exists."
        )
    return UUID(str(org_id))


async def already_seeded(session: AsyncSession, org_id: UUID) -> bool:
    existing, _ = await customers_svc.list_customers(session, org_id, limit=200, offset=0)
    return any(c.slug == CUSTOMERS[0].slug for c in existing)


async def seed_customers(
    session: AsyncSession, org_id: UUID, log: Log
) -> dict[str, tuple[UUID, UUID]]:
    """Customers, their named reviewers, their required frameworks, one engagement each.

    Returns slug -> (customer_id, engagement_id).
    """
    log.phase("1. Client customers and engagements")
    frameworks = await frameworks_svc.list_frameworks(session, org_id)
    by_slug: dict[str, tuple[UUID, UUID]] = {}

    for spec in CUSTOMERS:
        customer = await customers_svc.create_customer(
            session,
            org_id,
            customer_schemas.CustomerCreate(
                slug=spec.slug,
                legal_name=spec.legal_name,
                display_name=spec.display_name,
                status=customer_schemas.CustomerStatus.ACTIVE,
                sector=spec.sector,
                criticality=spec.criticality,
                home_jurisdiction=spec.home,
                operating_jurisdictions=list(spec.operating),
            ),
        )
        log.tally("customers")

        for role, principal in (
            (customer_schemas.ContactRole.SECURITY_REVIEWER, spec.reviewer),
            (customer_schemas.ContactRole.DATA_PROTECTION, spec.dpo),
        ):
            await customers_svc.set_contact(
                session,
                org_id,
                customer.id,
                customer_schemas.ContactUpsert(role=role, principal_id=principal),
            )
            log.tally("customer contacts")

        # Tier 1 clients require everything we ship; the rest take the standards only.
        if spec.criticality == customer_schemas.CriticalityTier.TIER_1:
            wanted = frameworks
        else:
            wanted = [f for f in frameworks if f.kind == framework_schemas.FrameworkKind.STANDARD]
        for framework in wanted:
            await customers_svc.require_framework(
                session,
                org_id,
                customer.id,
                customer_schemas.FrameworkRequirementCreate(
                    framework_id=framework.id,
                    level=customer_schemas.RequirementLevel.MANDATORY,
                ),
            )
            log.tally("framework requirements")

        engagement = await engagements_svc.create_engagement(
            session,
            org_id,
            engagement_schemas.EngagementCreate(
                customer_id=customer.id,
                slug="managed-ai-delivery",
                name=f"{spec.display_name} — managed AI delivery",
                description=(
                    f"Delivery of assured AI agents to {spec.display_name} under "
                    f"{spec.home} data residency."
                ),
                state=engagement_schemas.EngagementState.ACTIVE,
                permitted_regions=list(spec.regions),
                prohibited_regions=["us-east-1", "ap-south-1"],
                cross_border_transfer=spec.cross_border,
                permitted_data_classes=list(spec.data_classes),
                contract_ref=f"MSA-{spec.slug.upper()[:6]}-2026",
                starts_on=date(2026, 1, 1),
                ends_on=date(2028, 12, 31),
                delivery_lead=TEAMS[0][1],
                customer_approver=spec.reviewer,
            ),
        )
        log.tally("engagements")

        for kind, target, unit, basis in (
            (
                engagement_schemas.ServiceLevelKind.AVAILABILITY,
                Decimal("99.90"),
                "percent",
                engagement_schemas.PenaltyBasis.SERVICE_CREDIT,
            ),
            (
                engagement_schemas.ServiceLevelKind.ERROR_RATE,
                Decimal("1.00"),
                "percent",
                engagement_schemas.PenaltyBasis.NONE,
            ),
        ):
            await engagements_svc.set_service_level(
                session,
                org_id,
                engagement.id,
                engagement_schemas.ServiceLevelUpsert(
                    kind=kind,
                    target=target,
                    unit=unit,
                    measurement_window=engagement_schemas.ServiceLevelWindow.MONTHLY,
                    penalty_basis=basis,
                    penalty_detail=(
                        "5% of monthly fee per 0.1% below target"
                        if basis == engagement_schemas.PenaltyBasis.SERVICE_CREDIT
                        else None
                    ),
                ),
            )
            log.tally("service levels")

        by_slug[spec.slug] = (customer.id, engagement.id)
        log.line(f"{spec.display_name} — engagement active, {len(wanted)} framework(s) required")

    return by_slug


async def seed_agents(
    session: AsyncSession, org_id: UUID, plans: list[AgentPlan], log: Log
) -> None:
    """Agents, their owners, their version history, BOM and graph for each version."""
    log.phase("2. Agent fleet and version history")

    for plan in plans:
        agent = await registry_svc.create_agent(
            session,
            org_id,
            registry_schemas.AgentCreate(
                urn=plan.urn,
                display_name=plan.display_name,
                description=plan.description,
                owning_team=plan.team,
                lifecycle_state=plan.lifecycle,
            ),
        )
        plan.agent_id = agent.id
        log.tally("agents")

        for role in (
            registry_schemas.OwnershipRole.ACCOUNTABLE,
            registry_schemas.OwnershipRole.APPROVER_OF_RECORD,
        ):
            await registry_svc.set_owner(
                session,
                org_id,
                agent.id,
                registry_schemas.OwnershipUpsert(role=role, principal_id=plan.accountable),
            )
            log.tally("ownership records")

        for semver, descriptor, _published_at in plan.descriptors:
            version = await registry_svc.publish_version(
                session,
                org_id,
                agent.id,
                registry_schemas.VersionPublish(
                    semver=semver,
                    descriptor=descriptor,
                    published_by=plan.accountable,
                    environment=plan.lifecycle,
                    vcs_provider="github",
                    vcs_repo=f"northwind-digital/{plan.urn.split(':')[3]}",
                    vcs_ref=f"refs/tags/v{semver}",
                ),
            )
            plan.version_ids.append(version.id)
            log.tally("agent versions")

            # Nothing wires these to publish yet — the worker's handlers are all still
            # commented out — so the seed does what the background job will do later.
            await bom_svc.persist_components(session, org_id, version.id, descriptor)
            log.tally("BOM components", len(bom_svc.extract_components(descriptor)))

            await graph_svc.rebuild_from_version(session, org_id, agent.id, version.id, descriptor)

    log.line(f"{len(plans)} agents, {log.counts.get('agent versions', 0)} versions published")


async def seed_releases(
    session: AsyncSession, org_id: UUID, plans: list[AgentPlan], log: Log
) -> None:
    """A release per consecutive version pair, verdicted by the real engine.

    No verdict is chosen here. Whether a release comes out blocking is decided by the
    materiality rules reading the two descriptors, which is the point: the demo shows
    the engine's opinion, not a scripted one.
    """
    log.phase("3. Releases through the materiality engine")
    blocking = 0

    for plan in plans:
        if plan.agent_id is None or len(plan.version_ids) < 2:
            continue
        for step in range(1, len(plan.version_ids)):
            semver = plan.descriptors[step][0]
            detail = await releases_svc.create_release(
                session,
                org_id,
                release_schemas.ReleaseCreate(
                    agent_id=plan.agent_id,
                    from_version_id=plan.version_ids[step - 1],
                    to_version_id=plan.version_ids[step],
                    release_tag=f"v{semver}",
                    title=f"{plan.display_name} v{semver}",
                    notes="Seeded release.",
                    vcs_provider="github",
                    vcs_repo=f"northwind-digital/{plan.urn.split(':')[3]}",
                    vcs_ref=f"refs/tags/v{semver}",
                    proposed_by=plan.accountable,
                ),
            )
            log.tally("releases")
            if detail.material_count:
                blocking += 1

    log.line(f"{log.counts.get('releases', 0)} releases, {blocking} carrying a material change")


async def seed_scope_and_accreditation(
    session: AsyncSession,
    org_id: UUID,
    plans: list[AgentPlan],
    engagements: dict[str, tuple[UUID, UUID]],
    rng: random.Random,
    log: Log,
) -> None:
    """Put agents in scope, then accredit some of them.

    Deliberately leaves drift behind: for a third of the scoped agents the accredited
    version is not the deployed one, which is the single most useful thing a delivery
    lead can see on the engagement screen.
    """
    log.phase("4. Engagement scope and accreditation")
    frameworks = await frameworks_svc.list_frameworks(session, org_id)
    standard = next(
        (f for f in frameworks if f.kind == framework_schemas.FrameworkKind.STANDARD),
        frameworks[0] if frameworks else None,
    )
    if standard is None:
        log.line("no frameworks available; skipping accreditation")
        return

    drifted = 0
    for plan in plans:
        if plan.agent_id is None or not plan.version_ids:
            continue
        if plan.lifecycle != registry_schemas.LifecycleState.PRODUCTION:
            continue

        _customer_id, engagement_id = engagements[plan.customer.slug]
        deployed = plan.version_ids[-1]
        # A third of the estate is running ahead of what was approved.
        accredited = (
            plan.version_ids[-2] if len(plan.version_ids) > 1 and rng.random() < 0.34 else deployed
        )
        if accredited != deployed:
            drifted += 1

        await engagements_svc.scope_agent(
            session,
            org_id,
            engagement_id,
            engagement_schemas.ScopeAgentRequest(
                agent_id=plan.agent_id,
                uptake=engagement_schemas.VersionUptake.PINNED,
                accredited_version_id=accredited,
                deployed_version_id=deployed,
            ),
        )
        log.tally("scoped agents")

        accreditation = await accreditation_svc.create_accreditation(
            session,
            org_id,
            acc_schemas.AccreditationCreate(
                agent_version_id=accredited,
                framework_id=standard.id,
                engagement_id=engagement_id,
            ),
        )
        log.tally("accreditations")
        await accreditation_svc.assemble_controls(session, org_id, accreditation.id)

        # Three states, so the queue screen has something in it. Approval uses a
        # different principal from submission because separation of duties is enforced.
        roll = rng.random()
        if roll < 0.6:
            await accreditation_svc.submit_accreditation(
                session,
                org_id,
                accreditation.id,
                acc_schemas.TransitionRequest(actor=plan.accountable, reason="Seeded submission."),
            )
            await accreditation_svc.approve_accreditation(
                session,
                org_id,
                accreditation.id,
                acc_schemas.TransitionRequest(
                    actor=plan.customer.reviewer,
                    reason="Evidence reviewed, controls satisfied.",
                ),
            )
            log.tally("accreditations approved")
        elif roll < 0.85:
            await accreditation_svc.submit_accreditation(
                session,
                org_id,
                accreditation.id,
                acc_schemas.TransitionRequest(actor=plan.accountable, reason="Seeded submission."),
            )
            log.tally("accreditations awaiting review")

    log.line(
        f"{log.counts.get('scoped agents', 0)} agents in scope, "
        f"{log.counts.get('accreditations approved', 0)} approved, {drifted} drifted"
    )


async def seed_evidence(
    session: AsyncSession,
    org_id: UUID,
    plans: list[AgentPlan],
    engagements: dict[str, tuple[UUID, UUID]],
    days: int,
    rng: random.Random,
    log: Log,
) -> None:
    """An evidence stream over the window, then seal it into a chain.

    Sealing more than once matters: a single batch proves nothing about the chain, and
    the trust portal's whole claim is that batch N commits to batch N-1.
    """
    log.phase("5. Evidence stream and Merkle chain")

    # Every seeded event is dated behind the seal lag. `seal_pending` deliberately
    # leaves recent events alone so a collector replaying a disk buffer can still be
    # anchored in the window it belongs to — correct in production, but on a fresh demo
    # it would leave a handful of events sitting unsealed, which reads as a backlog the
    # product failed to clear. Derived from the constant rather than hardcoded, so it
    # cannot drift away from the behaviour it is compensating for.
    latest = datetime.now(UTC) - evidence_svc.SEAL_LAG - timedelta(minutes=5)
    kinds = (
        evidence_schemas.EvidenceKind.MODEL_INVENTORY,
        evidence_schemas.EvidenceKind.TOOL_PERMISSION_INVENTORY,
        evidence_schemas.EvidenceKind.DATA_CLASS_INVENTORY,
        evidence_schemas.EvidenceKind.RESIDENCY_PROOF,
        evidence_schemas.EvidenceKind.OVERSIGHT_RECORD,
        evidence_schemas.EvidenceKind.OWNERSHIP_RECORD,
        evidence_schemas.EvidenceKind.CHANGE_HISTORY,
        evidence_schemas.EvidenceKind.POLICY_DECISION,
        evidence_schemas.EvidenceKind.GUARDRAIL_ACTIVATION,
        evidence_schemas.EvidenceKind.ACCESS_REVIEW,
    )

    live = [p for p in plans if p.agent_id is not None and p.version_ids]
    # Seal in slices so the chain has real links rather than one long batch.
    slices = 5
    per_slice = max(1, len(live) * 3 // slices)

    pending: list[evidence_schemas.EvidenceRecord] = []
    sealed = 0

    for index, plan in enumerate(live):
        assert plan.agent_id is not None
        customer_id, engagement_id = engagements[plan.customer.slug]

        for _ in range(3):
            kind = rng.choice(kinds)
            occurred = latest - timedelta(
                days=rng.randint(0, max(0, days - 1)),
                hours=rng.randint(0, 23),
                minutes=rng.randint(0, 59),
            )
            outcome = rng.choices(
                [
                    evidence_schemas.EvidenceOutcome.OBSERVED,
                    evidence_schemas.EvidenceOutcome.ALLOW,
                    evidence_schemas.EvidenceOutcome.REDACT,
                    evidence_schemas.EvidenceOutcome.DENY,
                ],
                weights=[55, 30, 10, 5],
            )[0]
            pending.append(
                evidence_schemas.EvidenceRecord(
                    kind=kind,
                    occurred_at=occurred,
                    agent_id=plan.agent_id,
                    agent_version_id=plan.version_ids[-1],
                    engagement_id=engagement_id,
                    customer_id=customer_id,
                    actor="service:collector",
                    action=kind.value,
                    outcome=outcome,
                    subject_ref=plan.urn,
                    region=plan.customer.regions[0],
                    data_classes=list(plan.customer.data_classes),
                    decision=outcome.value,
                    reason_code=None if outcome.value == "observed" else f"{kind.value}_rule",
                    detail={"source": "seed", "team": plan.team},
                    detected_by=evidence_schemas.DetectedBy.COLLECTOR,
                )
            )

        if len(pending) >= per_slice or index == len(live) - 1:
            result = await evidence_svc.record_events(session, org_id, pending)
            log.tally("evidence events", result.accepted)
            if result.rejected:
                log.line(f"WARNING: {result.rejected} evidence event(s) rejected")
            pending = []

            seal = await evidence_svc.seal_pending(session, org_id, sealed_by="service:seed")
            if seal.batch is not None:
                sealed += 1
                log.tally("merkle batches")

    verification = await evidence_svc.verify_chain(session, org_id)
    log.line(
        f"{log.counts.get('evidence events', 0)} events in {sealed} sealed batch(es); "
        f"chain valid: {verification.is_valid}"
    )
    if not verification.is_valid:
        raise SystemExit("seeded evidence chain does not verify — refusing to leave it in place")


async def seed_assurance(
    session: AsyncSession, org_id: UUID, plans: list[AgentPlan], rng: random.Random, log: Log
) -> None:
    """Findings and posture. A clean estate demos nothing, so this leaves real gaps."""
    log.phase("6. Findings and posture")
    categories = (
        (assurance_schemas.FindingSource.PROBE, assurance_schemas.FindingCategory.PROMPT_INJECTION),
        (assurance_schemas.FindingSource.PROBE, assurance_schemas.FindingCategory.JAILBREAK),
        (assurance_schemas.FindingSource.CVE, assurance_schemas.FindingCategory.DEPENDENCY),
        (assurance_schemas.FindingSource.DRIFT, assurance_schemas.FindingCategory.MODEL_CHANGE),
        (assurance_schemas.FindingSource.POLICY, assurance_schemas.FindingCategory.OVERSIGHT_GAP),
        (
            assurance_schemas.FindingSource.POLICY,
            assurance_schemas.FindingCategory.RESIDENCY_VIOLATION,
        ),
        (
            assurance_schemas.FindingSource.MANUAL,
            assurance_schemas.FindingCategory.EXCESSIVE_AGENCY,
        ),
    )
    titles = {
        assurance_schemas.FindingCategory.PROMPT_INJECTION: (
            "Indirect prompt injection via retrieved document"
        ),
        assurance_schemas.FindingCategory.JAILBREAK: "Role-play jailbreak bypassed refusal",
        assurance_schemas.FindingCategory.DEPENDENCY: "Vulnerable transitive dependency in runtime",
        assurance_schemas.FindingCategory.MODEL_CHANGE: "Deployed model differs from accredited",
        assurance_schemas.FindingCategory.OVERSIGHT_GAP: (
            "Write capability has no human approval step"
        ),
        assurance_schemas.FindingCategory.RESIDENCY_VIOLATION: (
            "Model endpoint outside permitted region"
        ),
        assurance_schemas.FindingCategory.EXCESSIVE_AGENCY: (
            "Tool permits payment initiation without cap"
        ),
    }

    live = [p for p in plans if p.agent_id is not None and p.version_ids]
    for plan in live:
        assert plan.agent_id is not None
        for _ in range(rng.choices([0, 1, 2, 3], weights=[40, 30, 20, 10])[0]):
            source, category = rng.choice(categories)
            severity = rng.choices(
                [
                    assurance_schemas.Severity.CRITICAL,
                    assurance_schemas.Severity.HIGH,
                    assurance_schemas.Severity.MEDIUM,
                    assurance_schemas.Severity.LOW,
                ],
                weights=[5, 20, 45, 30],
            )[0]
            finding = await assurance_svc.record_finding(
                session,
                org_id,
                assurance_schemas.FindingCreate(
                    agent_id=plan.agent_id,
                    agent_version_id=plan.version_ids[-1],
                    source=source,
                    category=category,
                    severity=severity,
                    title=titles[category],
                    detail=f"Raised against {plan.display_name} by the {source.value} pipeline.",
                    subject_ref=plan.urn,
                    remediation_due=datetime.now(UTC) + timedelta(days=rng.randint(3, 45)),
                ),
            )
            log.tally("findings")

            # Some have been looked at. An all-open queue looks abandoned.
            roll = rng.random()
            if roll < 0.45:
                await assurance_svc.triage_finding(
                    session,
                    org_id,
                    finding.id,
                    assurance_schemas.FindingTriage(
                        triaged_by=plan.accountable,
                        remediation_due=datetime.now(UTC) + timedelta(days=rng.randint(5, 30)),
                    ),
                )
                log.tally("findings triaged")
            if roll < 0.2:
                await assurance_svc.resolve_finding(
                    session,
                    org_id,
                    finding.id,
                    assurance_schemas.FindingResolve(
                        state=assurance_schemas.FindingState.FALSE_POSITIVE,
                        resolved_by=plan.accountable,
                        resolution_note="Probe matched a quoted example, not a live capability.",
                    ),
                )
                log.tally("findings closed")

        await assurance_svc.compute_posture(session, org_id, plan.agent_id)
        log.tally("posture scores")

    if live:
        first = live[0]
        assert first.agent_id is not None and first.version_ids
        suites = await assurance_repo.list_probe_suites(session, org_id)
        core = next((s for s in suites if s.slug == "prompt-injection-core"), None)
        if core is not None:
            await assurance_svc.run_probe_suite(
                session,
                org_id,
                core.id,
                first.agent_id,
                first.version_ids[-1],
                triggered_by="service:seed",
            )
            log.tally("probe runs")

    log.line(
        f"{log.counts.get('findings', 0)} findings across the estate, "
        f"{log.counts.get('posture scores', 0)} posture scores computed, "
        f"{log.counts.get('probe runs', 0)} probe suite run(s)"
    )


async def seed_slos(
    session: AsyncSession,
    org_id: UUID,
    engagements: dict[str, tuple[UUID, UUID]],
    days: int,
    rng: random.Random,
    log: Log,
) -> None:
    """Availability and latency SLOs with daily measurements, some of them breaching."""
    log.phase("7. Service levels and attainment")
    now = datetime.now(UTC)

    for spec in CUSTOMERS:
        _customer_id, engagement_id = engagements[spec.slug]

        for kind, target, unit in (
            (sla_schemas.SloKind.AVAILABILITY, Decimal("99.90"), "percent"),
            (sla_schemas.SloKind.LATENCY_P95, Decimal("2500"), "milliseconds"),
        ):
            slo = await sla_svc.define_slo(
                session,
                org_id,
                sla_schemas.SloCreate(
                    engagement_id=engagement_id,
                    kind=kind,
                    target=target,
                    unit=unit,
                    measurement_window="monthly",
                    penalty_model={
                        "basis": "percentage_of_monthly_fee",
                        "tiers": [
                            {"below": 99.9, "credit_pct": 5},
                            {"below": 99.0, "credit_pct": 10},
                        ],
                    }
                    if kind == sla_schemas.SloKind.AVAILABILITY
                    else {},
                ),
            )
            log.tally("SLOs")

            for day in range(min(days, 30)):
                start = (now - timedelta(days=day)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                if kind == sla_schemas.SloKind.AVAILABILITY:
                    # Mostly comfortable, with the occasional bad day.
                    value = (
                        Decimal(str(round(rng.uniform(98.40, 99.79), 2)))
                        if rng.random() < 0.12
                        else Decimal(str(round(rng.uniform(99.90, 100.0), 2)))
                    )
                else:
                    value = Decimal(str(rng.randint(1400, 3100)))
                await sla_svc.record_measurement(
                    session,
                    org_id,
                    slo.id,
                    sla_schemas.MeasurementCreate(
                        bucket_start=start,
                        bucket_end=start + timedelta(days=1),
                        value=value,
                        sample_count=rng.randint(4000, 20000),
                    ),
                )
                log.tally("SLO measurements")

            breach = await sla_svc.detect_breaches(session, org_id, slo.id)
            if breach is not None:
                log.tally("SLO breaches")

    log.line(
        f"{log.counts.get('SLOs', 0)} SLOs, {log.counts.get('SLO measurements', 0)} measurements, "
        f"{log.counts.get('SLO breaches', 0)} breach(es) detected"
    )


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="python -m seed.generate",
        description="Populate a database with a deterministic demo estate.",
    )
    parser.add_argument("--agents", type=int, default=40, help="agents to create (default 40)")
    parser.add_argument("--teams", type=int, default=5, help="delivery teams to spread them across")
    parser.add_argument("--days", type=int, default=30, help="how far back history reaches")
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="RNG seed; the same value always produces the same estate",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="seed again even if this database already has a seeded estate",
    )
    parser.add_argument("--quiet", action="store_true", help="only print the summary")
    return parser.parse_args(argv)


async def run(args: argparse.Namespace) -> int:
    if args.agents < 1:
        raise SystemExit("--agents must be at least 1")

    log = Log(quiet=args.quiet)
    rng = random.Random(args.seed)
    org_id = await resolve_org_id()

    async with tenant_session(org_id) as session:
        if await already_seeded(session, org_id) and not args.force:
            did_work = False
            if await run_steps_missing(session, org_id):
                from app.db.models.registry import Agent

                plans = plan_agents(rng, args.agents, args.teams, args.days)
                by_urn = {
                    urn: agent_id
                    for agent_id, urn in (
                        await session.execute(
                            select(Agent.id, Agent.urn).where(Agent.org_id == org_id)
                        )
                    ).all()
                }
                for plan in plans:
                    plan.agent_id = by_urn.get(plan.urn)
                log = Log(quiet=args.quiet)
                await backfill_run_steps(session, org_id, plans, rng, log)
                if not args.quiet:
                    print("Backfilled run step traces for the existing demo estate.")
                did_work = True
            from seed.backfill_new_domains import backfill_new_domains, needs_backfill

            if await needs_backfill(session, org_id):
                log = Log(quiet=args.quiet)
                if await backfill_new_domains(session, org_id, log):
                    did_work = True
                    if not args.quiet:
                        log.summary()
                        print("Backfilled model routing, probe runs, and routing signals.")
            if did_work:
                return 0
            print(
                "This database already has a seeded estate. Nothing to do.\n"
                "Use --force to add another generation, or reset the database first "
                "(scripts\\aap-reset.cmd, or `docker compose down -v`)."
            )
            return 0

    if not args.quiet:
        print(
            f"Seeding organisation {org_id} — {args.agents} agents across "
            f"{args.teams} team(s), {args.days} days of history, rng seed {args.seed}."
        )

    plans = plan_agents(rng, args.agents, args.teams, args.days)

    # A session per phase. Each phase is independently meaningful, and a failure in a
    # later one leaves the earlier ones committed and inspectable rather than rolling
    # back forty agents' worth of work to report one bad SLO row.
    async with tenant_session(org_id) as session:
        engagements = await seed_customers(session, org_id, log)
    async with tenant_session(org_id) as session:
        from app.domains.model_routing import service as model_routing_svc

        await model_routing_svc.seed_reference_catalog(session, org_id)
        if not args.quiet:
            log.line("Model catalogue reference rows seeded")
    async with tenant_session(org_id) as session:
        await seed_agents(session, org_id, plans, log)
    async with tenant_session(org_id) as session:
        await seed_releases(session, org_id, plans, log)
    async with tenant_session(org_id) as session:
        await seed_scope_and_accreditation(session, org_id, plans, engagements, rng, log)
    async with tenant_session(org_id) as session:
        await seed_evidence(session, org_id, plans, engagements, args.days, rng, log)
    async with tenant_session(org_id) as session:
        await seed_assurance(session, org_id, plans, rng, log)
    async with tenant_session(org_id) as session:
        await seed_slos(session, org_id, engagements, args.days, rng, log)
    # Last, and in its own session: it writes more rows than every other phase combined,
    # so a failure here should leave the governance estate intact and inspectable.
    async with tenant_session(org_id) as session:
        await seed_operations(session, org_id, plans, args.days, rng, log)

    log.summary()
    print(f"\nOrganisation id for the console and the API: {org_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return asyncio.run(_main(args))
    except KeyboardInterrupt:
        return 130


async def _main(args: argparse.Namespace) -> int:
    try:
        return await run(args)
    finally:
        await dispose_engine()


if __name__ == "__main__":
    sys.exit(main())
