"""Model routing against real Postgres."""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.assurance import Finding, PolicyDecision
from app.domains.model_routing import service as routing_svc
from app.domains.model_routing.schemas import (
    CatalogEntryCreate,
    ClassificationState,
    EnforcementLevel,
    ModelRoutingEvaluateRequest,
)
from app.domains.operations import service as operations_svc
from app.domains.operations.schemas import (
    RunBatch,
    RunOutcome,
    StepKind,
    StepReport,
)
from app.domains.registry import service as registry_svc
from app.domains.registry.schemas import LifecycleState, VersionPublish
from tests.integration.test_operations import NOW, make_agent, report

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _descriptor(urn: str, *, cross_border: str = "prohibited") -> dict[str, Any]:
    return {
        "aap_version": "0.1",
        "agent": {"urn": urn, "version": "1.0.0", "lifecycle_state": "production"},
        "accountability": {
            "owning_team": "Platform",
            "accountable_person": "person:qa@test.example",
        },
        "runtime": {"framework": "langgraph"},
        "data": {
            "classes": ["customer_pii"],
            "residency": {
                "permitted_regions": ["eu-west-1"],
                "cross_border": cross_border,
                "basis": "gdpr_art_46",
            },
        },
        "models": [{"provider": "anthropic", "id": "claude-sonnet-4"}],
        "composition": {
            "model_policy": {
                "selection_mode": "allowlist",
                "allowlist": ["anthropic/claude-sonnet-4"],
                "enforcement_level": "blocking",
            },
        },
    }


async def _seed_catalog_eu(session: AsyncSession, org_id: uuid.UUID) -> None:
    await routing_svc.create_catalog_entry(
        session,
        org_id,
        CatalogEntryCreate(
            provider="anthropic",
            model_id="claude-sonnet-4",
            primary_region="eu-west-1",
            jurisdiction="EU",
            classification_state=ClassificationState.CLASSIFIED,
        ),
    )


async def _publish(
    session: AsyncSession, org_id: uuid.UUID, agent_id: uuid.UUID, urn: str
) -> uuid.UUID:
    version = await registry_svc.publish_version(
        session,
        org_id,
        agent_id,
        VersionPublish(
            semver="1.1.0",
            descriptor=_descriptor(urn),
            environment=LifecycleState.PRODUCTION,
            published_by="person:qa@test.example",
        ),
    )
    return version.id


async def test_evaluate_and_gateway_config_agree(session: AsyncSession, org_id: uuid.UUID) -> None:
    agent = await make_agent(session, org_id)
    version_id = await _publish(session, org_id, agent.id, agent.urn)
    await _seed_catalog_eu(session, org_id)

    compiled = await routing_svc.compile_agent_model_policy(session, org_id, agent.id, version_id)
    emitted = routing_svc.build_litellm_config(compiled)
    assert emitted.fallback_access_enforced is True

    for deployment in compiled.allowed_deployments:
        result = await routing_svc.evaluate_pre_dispatch(
            session,
            org_id,
            ModelRoutingEvaluateRequest(
                agent_id=agent.id,
                agent_version_id=version_id,
                model_provider=deployment.provider,
                model_id=deployment.model_id,
                environment=LifecycleState.PRODUCTION.value,
            ),
        )
        assert result.outcome == "allow"
        assert result.compiled_rules_digest == compiled.rules_digest

    denied = await routing_svc.evaluate_pre_dispatch(
        session,
        org_id,
        ModelRoutingEvaluateRequest(
            agent_id=agent.id,
            agent_version_id=version_id,
            model_provider="anthropic",
            model_id="never-seen-model",
            environment=LifecycleState.PRODUCTION.value,
        ),
    )
    assert denied.outcome == "deny"
    assert denied.would_block is True
    assert denied.policy_decision_id is not None


async def test_dev_allows_unknown_production_denies(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    agent = await make_agent(session, org_id)
    version_id = await _publish(session, org_id, agent.id, agent.urn)

    prod = await routing_svc.evaluate_pre_dispatch(
        session,
        org_id,
        ModelRoutingEvaluateRequest(
            agent_id=agent.id,
            agent_version_id=version_id,
            model_provider="openai",
            model_id="mystery",
            environment=LifecycleState.PRODUCTION.value,
        ),
    )
    assert prod.outcome == "deny"

    dev = await routing_svc.evaluate_pre_dispatch(
        session,
        org_id,
        ModelRoutingEvaluateRequest(
            agent_id=agent.id,
            agent_version_id=version_id,
            model_provider="openai",
            model_id="mystery",
            environment=LifecycleState.DEV.value,
        ),
    )
    assert dev.outcome == "allow"


async def test_advisory_records_without_blocking(session: AsyncSession, org_id: uuid.UUID) -> None:
    agent = await make_agent(session, org_id)
    await _publish(session, org_id, agent.id, agent.urn)

    result = await routing_svc.evaluate_pre_dispatch(
        session,
        org_id,
        ModelRoutingEvaluateRequest(
            agent_id=agent.id,
            model_provider="openai",
            model_id="mystery",
            environment=LifecycleState.PRODUCTION.value,
            enforcement_level=EnforcementLevel.ADVISORY,
        ),
    )
    assert result.outcome == "deny"
    assert result.would_block is False
    assert result.http_status == 200
    assert result.policy_decision_id is not None


async def test_drift_detection_on_run_step(session: AsyncSession, org_id: uuid.UUID) -> None:
    agent = await make_agent(session, org_id)
    await _publish(session, org_id, agent.id, agent.urn)
    await _seed_catalog_eu(session, org_id)

    run_id = uuid.uuid4()
    await operations_svc.record_runs(
        session,
        org_id,
        RunBatch(
            runs=[
                report(
                    agent.id,
                    run_id=run_id,
                    outcome=RunOutcome.SUCCEEDED,
                    # Derived from NOW rather than the wall clock. The `report` helper
                    # starts every run at NOW, which is pinned to 12:00 UTC today, so
                    # `datetime.now(UTC)` here produced an `ended_at` before the run's
                    # own `started_at` for any run of the suite before noon UTC — and
                    # the schema rejects that, correctly. The test passed only after
                    # midday.
                    ended_at=NOW + timedelta(seconds=2),
                    steps=[
                        StepReport(
                            seq=1,
                            kind=StepKind.LLM,
                            name="primary",
                            started_at=NOW,
                            ended_at=NOW + timedelta(seconds=1),
                            outcome=RunOutcome.SUCCEEDED,
                            model="openai/gpt-4o",
                        )
                    ],
                )
            ]
        ),
    )

    scanned = await routing_svc.scan_run_for_model_drift(session, org_id, run_id)
    assert scanned == 1
    rows = (
        await session.execute(
            select(Finding).where(
                Finding.org_id == org_id,
                Finding.agent_id == agent.id,
                Finding.category == "residency_violation",
            )
        )
    ).scalars()
    assert any(r.source == "drift" for r in rows)


async def test_cross_tenant_catalog_isolated(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    await routing_svc.create_catalog_entry(
        session,
        org_id,
        CatalogEntryCreate(
            provider="tenant",
            model_id="private-model",
            primary_region="eu-west-1",
            jurisdiction="EU",
        ),
    )
    theirs = await routing_svc.list_catalog(session, other_org_id, search="private-model")
    assert theirs.total == 0


async def test_denial_writes_policy_decision(session: AsyncSession, org_id: uuid.UUID) -> None:
    agent = await make_agent(session, org_id)
    await _publish(session, org_id, agent.id, agent.urn)
    before = (
        await session.execute(
            select(func.count()).select_from(PolicyDecision).where(PolicyDecision.org_id == org_id)
        )
    ).scalar_one()
    await routing_svc.evaluate_pre_dispatch(
        session,
        org_id,
        ModelRoutingEvaluateRequest(
            agent_id=agent.id,
            model_provider="x",
            model_id="y",
            environment=LifecycleState.PRODUCTION.value,
        ),
    )
    after = (
        await session.execute(
            select(func.count()).select_from(PolicyDecision).where(PolicyDecision.org_id == org_id)
        )
    ).scalar_one()
    assert after == before + 1
