"""Composition API and obligation bounds against real Postgres."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.bom import service as bom_svc
from app.domains.composition import service as composition_svc
from app.domains.composition.schemas import ReconciliationStatus
from app.domains.operations import service as operations_svc
from app.domains.operations.schemas import RunBatch, ToolCallReport, ToolSurface
from app.domains.registry import service as registry_svc
from app.domains.registry.schemas import LifecycleState, VersionPublish
from tests.integration.test_operations import make_agent, report

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _descriptor(urn: str) -> dict[str, Any]:
    return {
        "aap_version": "0.1",
        "agent": {"urn": urn, "version": "1.0.0"},
        "accountability": {
            "owning_team": "Platform",
            "accountable_person": "person:qa@test.example",
        },
        "runtime": {"framework": "langgraph"},
        "tools": [{"name": "declared_tool"}],
        "references": {"mcp_servers": [{"name": "stripe", "url": "https://mcp.internal/stripe"}]},
        "models": [{"provider": "anthropic", "id": "claude-sonnet-4"}],
        "composition": {
            "model_policy": {
                "selection_mode": "pinned",
                "pin": {"provider": "anthropic", "id": "claude-sonnet-4"},
            },
            "rule_sources": [
                {
                    "name": "agents_md",
                    "kind": "agents_md",
                    "path": "AGENTS.md",
                    "digest": "sha256:" + "a" * 64,
                }
            ],
            "rule_obligations": [
                {
                    "id": "OBL-001",
                    "source_ref": "agents_md",
                    "category": "pii",
                    "polarity": "forbid",
                    "statement": "Must not send PII off-prem.",
                    "strength": "binding",
                    "digest": "sha256:" + "b" * 64,
                }
            ],
            "skills": [
                {
                    "name": "refund",
                    "path": ".cursor/skills/refund/SKILL.md",
                    "digest": "sha256:" + "c" * 64,
                }
            ],
        },
    }


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
    await bom_svc.persist_components(session, org_id, version.id, _descriptor(urn))
    return version.id


async def test_obligation_statement_rejected_over_512_bytes_at_publish(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    agent = await make_agent(session, org_id)
    bad = _descriptor(agent.urn)
    bad["composition"]["rule_obligations"][0]["statement"] = "x" * 600
    with pytest.raises(registry_svc.InvalidDescriptorError):
        await registry_svc.publish_version(
            session,
            org_id,
            agent.id,
            VersionPublish(
                semver="1.1.0",
                descriptor=bad,
                environment=LifecycleState.PRODUCTION,
                published_by="person:qa@test.example",
            ),
        )


async def test_obligation_persisted_with_database_check(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    agent = await make_agent(session, org_id)
    version_id = await _publish(session, org_id, agent.id, agent.urn)
    await composition_svc.sync_obligations_from_descriptor(
        session, org_id, version_id, _descriptor(agent.urn)
    )
    count = (
        await session.execute(
            text(
                "SELECT count(*) FROM composition_rule_obligations "
                "WHERE org_id = :o AND agent_version_id = :v"
            ),
            {"o": org_id, "v": version_id},
        )
    ).scalar_one()
    assert int(count) == 1


async def test_reconciliation_three_directions(session: AsyncSession, org_id: uuid.UUID) -> None:
    agent = await make_agent(session, org_id)
    await _publish(session, org_id, agent.id, agent.urn)

    await operations_svc.record_runs(
        session,
        org_id,
        RunBatch(
            runs=[
                report(
                    agent.id,
                    tools=[
                        ToolCallReport(surface=ToolSurface.NATIVE, tool_name="undeclared_tool"),
                        ToolCallReport(
                            surface=ToolSurface.MCP,
                            server_name="stripe",
                            tool_name="list_charges",
                        ),
                    ],
                )
            ]
        ),
    )

    page = await composition_svc.reconcile_agent(session, org_id, agent.id, window_days=7)
    by_key = {(e.kind.value, e.key): e for e in page.elements}

    assert by_key[("tool", "declared_tool")].status == ReconciliationStatus.DECLARED_ONLY
    assert by_key[("tool", "undeclared_tool")].status == ReconciliationStatus.OBSERVED_ONLY
    assert by_key[("mcp_server", "stripe")].status == ReconciliationStatus.ALIGNED


async def test_cross_tenant_cannot_load_composition_summary(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    agent = await make_agent(session, org_id)
    version_id = await _publish(session, org_id, agent.id, agent.urn)

    await composition_svc.get_composition_summary(
        session, org_id, agent.id, version_id, window_days=7
    )

    denied = (
        composition_svc.CompositionAgentNotFoundError,
        composition_svc.CompositionVersionNotFoundError,
    )
    with pytest.raises(denied):
        await composition_svc.get_composition_summary(
            session, other_org_id, agent.id, version_id, window_days=7
        )


async def test_cross_tenant_cannot_reconcile(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    agent = await make_agent(session, org_id)
    await _publish(session, org_id, agent.id, agent.urn)

    with pytest.raises(composition_svc.CompositionAgentNotFoundError):
        await composition_svc.reconcile_agent(session, other_org_id, agent.id, window_days=7)


async def test_database_rejects_obligation_statement_over_512_bytes(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    agent = await make_agent(session, org_id)
    version_id = await _publish(session, org_id, agent.id, agent.urn)
    with pytest.raises(Exception):  # noqa: B017 — any DBAPI error is fine here
        await session.execute(
            text(
                """
                INSERT INTO composition_rule_obligations (
                    org_id, agent_version_id, obligation_id, source_ref,
                    category, polarity, strength, statement, digest
                ) VALUES (
                    :o, :v, 'OBL-BAD', 'agents_md', 'pii', 'forbid',
                    'binding', :stmt, 'sha256:abc'
                )
                """
            ),
            {"o": org_id, "v": version_id, "stmt": "x" * 600},
        )
        await session.flush()
