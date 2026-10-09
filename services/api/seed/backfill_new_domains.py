"""Targeted backfill for estates seeded before model routing and probe extensions landed.

Run inside the api container (uses the same DATABASE_URL as the live stack):

    python -m seed.backfill_new_domains

Idempotent: skips phases whose artefacts already exist. Never touches customers, agents,
or org id — only adds catalogue rows, probe runs, routing decisions, and drift signals.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.assurance import ProbeRun
from app.db.models.registry import Agent, AgentVersion
from app.db.session import dispose_engine, tenant_session
from app.domains.assurance import repository as assurance_repo
from app.domains.assurance import service as assurance_svc
from app.domains.frameworks import service as frameworks_svc
from app.domains.model_routing import repository as routing_repo
from app.domains.model_routing import schemas as routing_schemas
from app.domains.model_routing import service as routing_svc
from app.domains.registry.schemas import LifecycleState
from seed.generate import Log, resolve_org_id

_DEMO_AGENT_URN = "urn:aap:northwind:claims-triage:eu-west-2"

_AMBIGUOUS_DEMO_PROBE: dict[str, Any] = {
    "id": "DEMO-AMBIGUOUS",
    "technique": "output_integrity_unknown",
    "expect": "refuse",
    "turns": 1,
    "setup": {"fixture_profile": "compliant_refuse"},
    "assertions": [{"kind": "output_digest_not_equal", "params": {"forbidden_digests": []}}],
}

_PROBE_SUITE_SLUGS = (
    "prompt-injection-core",
    "undeclared-tool-bait",
    "residency-routing-live",
)


async def _catalogue_empty(session: AsyncSession, org_id: UUID) -> bool:
    total = await routing_repo.count_catalog_entries(session, org_id)
    return total == 0


async def _probe_runs_empty(session: AsyncSession, org_id: UUID) -> bool:
    total = await session.scalar(
        select(func.count()).select_from(ProbeRun).where(ProbeRun.org_id == org_id)
    )
    return int(total or 0) == 0


async def _resolve_demo_agent(session: AsyncSession, org_id: UUID) -> tuple[UUID, UUID] | None:
    stmt = (
        select(Agent.id, AgentVersion.id)
        .join(AgentVersion, AgentVersion.agent_id == Agent.id)
        .where(
            Agent.org_id == org_id,
            Agent.urn == _DEMO_AGENT_URN,
            AgentVersion.org_id == org_id,
        )
        .order_by(AgentVersion.published_at.desc())
        .limit(1)
    )
    row = (await session.execute(stmt)).one_or_none()
    if row is None:
        return None
    return UUID(str(row[0])), UUID(str(row[1]))


async def _seed_extended_catalogue(session: AsyncSession, org_id: UUID, log: Log) -> None:
    await routing_svc.seed_reference_catalog(session, org_id)
    log.tally("catalogue reference rows")

    extras = (
        routing_schemas.CatalogEntryCreate(
            provider="anthropic",
            model_id="claude-3-7-sonnet",
            display_name="Claude 3.7 Sonnet (EU residency)",
            hosting_mode=routing_schemas.HostingMode.CLOUD_MANAGED,
            primary_region="eu-west-2",
            jurisdiction="GB",
            cross_border_ok=False,
            data_handling_terms=routing_schemas.DataHandlingTerms.ZERO_RETENTION,
            source="vendor_doc",
        ),
        routing_schemas.CatalogEntryCreate(
            provider="openai",
            model_id="gpt-4.1",
            display_name="GPT-4.1",
            primary_region="us-east-1",
            jurisdiction="US",
            data_handling_terms=routing_schemas.DataHandlingTerms.ZERO_RETENTION,
            source="operator_assertion",
        ),
        routing_schemas.CatalogEntryCreate(
            provider="mistral",
            model_id="mistral-large-2",
            display_name="Mistral Large 2",
            primary_region="eu-west-1",
            jurisdiction="EU",
            source="vendor_doc",
        ),
        routing_schemas.CatalogEntryCreate(
            provider="self_hosted",
            model_id="llama-3.3-70b",
            display_name="Llama 3.3 70B (customer VPC)",
            hosting_mode=routing_schemas.HostingMode.SELF_HOSTED,
            primary_region="eu-west-2",
            jurisdiction="GB",
            data_handling_terms=routing_schemas.DataHandlingTerms.ZERO_RETENTION,
            source="customer_override",
        ),
        routing_schemas.CatalogEntryCreate(
            provider="google",
            model_id="gemini-2.5-pro",
            display_name="Gemini 2.5 Pro (observed, unclassified)",
            primary_region="global",
            jurisdiction="UNKNOWN",
            classification_state=routing_schemas.ClassificationState.UNCLASSIFIED,
            data_handling_terms=routing_schemas.DataHandlingTerms.UNKNOWN,
            source="observed",
        ),
        routing_schemas.CatalogEntryCreate(
            provider="cursor",
            model_id="composer-1",
            display_name="Cursor Composer (SDK default)",
            primary_region="us-east-1",
            jurisdiction="US",
            data_handling_terms=routing_schemas.DataHandlingTerms.PROVIDER_DEFAULT,
            source="operator_assertion",
        ),
    )
    for entry in extras:
        existing = await routing_repo.get_catalog_entry_by_provider_model(
            session, org_id, entry.provider, entry.model_id
        )
        if existing is not None:
            continue
        await routing_svc.create_catalog_entry(session, org_id, entry)
        log.tally("catalogue entries")


async def _seed_probe_runs(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
    version_id: UUID,
    log: Log,
) -> None:
    suites = await assurance_repo.list_probe_suites(session, org_id)
    by_slug = {s.slug: s for s in suites}
    for slug in _PROBE_SUITE_SLUGS:
        suite = by_slug.get(slug)
        if suite is None:
            continue
        extra = (_AMBIGUOUS_DEMO_PROBE,) if slug == "prompt-injection-core" else ()
        await assurance_svc.run_probe_suite(
            session,
            org_id,
            suite.id,
            agent_id,
            version_id,
            "service:seed-backfill",
            extra_probes=extra,
        )
        log.tally("probe runs")


async def _seed_routing_signals(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
    version_id: UUID,
    log: Log,
) -> None:
    await routing_svc.evaluate_pre_dispatch(
        session,
        org_id,
        routing_schemas.ModelRoutingEvaluateRequest(
            agent_id=agent_id,
            agent_version_id=version_id,
            environment=LifecycleState.PRODUCTION.value,
            model_provider="google",
            model_id="gemini-2.5-pro",
            data_classes=["customer_pii"],
            subject_ref="seed:backfill:deny-unclassified",
        ),
    )
    log.tally("routing denials")

    await routing_svc.ingest_gateway_log(
        session,
        org_id,
        routing_schemas.GatewayLogIngest(
            agent_id=agent_id,
            agent_version_id=version_id,
            model_provider="openai",
            model_id="gpt-4.1",
            region_used="us-east-1",
            outcome="routed",
            logged_at=datetime.now(tz=UTC),
            log_digest="seed:backfill:drift-gpt-4.1",
        ),
    )
    log.tally("drift observations")


async def needs_backfill(session: AsyncSession, org_id: UUID) -> bool:
    if await _catalogue_empty(session, org_id):
        return True
    if await _probe_runs_empty(session, org_id):
        return True
    overview = await routing_svc.routing_overview(session, org_id)
    return not overview.recent_denials or not overview.drift_findings


async def backfill_new_domains(session: AsyncSession, org_id: UUID, log: Log) -> bool:
    """Returns True if any phase ran."""
    ran = False
    links = await frameworks_svc.seed_obligation_template_links(session, org_id)
    if links:
        log.phase("Obligation template control links")
        log.tally("obligation template links", links)
        ran = True

    demo = await _resolve_demo_agent(session, org_id)
    if demo is None:
        log.line("WARNING: demo agent not found; skipping agent-scoped phases")
        agent_id = version_id = None
    else:
        agent_id, version_id = demo

    if await _catalogue_empty(session, org_id):
        log.phase("Model catalogue")
        await _seed_extended_catalogue(session, org_id, log)
        ran = True
    elif (
        await routing_repo.count_catalog_entries(
            session, org_id, classification=routing_schemas.ClassificationState.UNCLASSIFIED.value
        )
        == 0
    ):
        log.phase("Model catalogue (unclassified row)")
        await _seed_extended_catalogue(session, org_id, log)
        ran = True

    if await _probe_runs_empty(session, org_id) and agent_id is not None and version_id is not None:
        log.phase("Probe suite runs")
        await _seed_probe_runs(session, org_id, agent_id, version_id, log)
        ran = True

    overview = await routing_svc.routing_overview(session, org_id)
    if (
        agent_id is not None
        and version_id is not None
        and (not overview.recent_denials or not overview.drift_findings)
    ):
        log.phase("Routing denials and drift")
        await _seed_routing_signals(session, org_id, agent_id, version_id, log)
        ran = True

    return ran


async def run(*, quiet: bool = False) -> int:
    log = Log(quiet=quiet)
    org_id = await resolve_org_id()
    async with tenant_session(org_id) as session:
        ran = await backfill_new_domains(session, org_id, log)
    if ran:
        log.summary()
        print(f"\nBackfill complete for organisation {org_id}")
    elif not quiet:
        print("New-domain backfill: nothing to do (artefacts already present).")
    return 0


async def _main() -> int:
    try:
        return await run()
    finally:
        await dispose_engine()


def main() -> int:
    try:
        return asyncio.run(_main())
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
