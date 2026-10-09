"""Probe runs and rule gaps against real Postgres."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.assurance import repository as assurance_repo
from app.domains.assurance import service as assurance_svc
from app.domains.assurance.probe_oracle import OracleVerdict
from app.domains.registry import service as registry_svc
from app.domains.registry.schemas import LifecycleState, VersionPublish
from tests.integration.test_operations import make_agent

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
        "composition": {
            "rule_obligations": [
                {
                    "id": "OBL-TOOL",
                    "source_ref": "agents_md",
                    "category": "tools",
                    "polarity": "require",
                    "statement": "Require tool use restricted to declared tools",
                    "strength": "binding",
                    "digest": "sha256:" + "c" * 64,
                    "template_ref": "TOOL-001-allowlist",
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
            semver="1.2.0",
            descriptor=_descriptor(urn),
            environment=LifecycleState.PRODUCTION,
            published_by="person:qa@test.example",
        ),
    )
    return version.id


async def test_probe_run_separates_execution_and_judge_counts(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    agent = await make_agent(session, org_id)
    version_id = await _publish(session, org_id, agent.id, agent.urn)
    suites = await assurance_repo.list_probe_suites(session, org_id)
    suite = next(s for s in suites if s.slug == "prompt-injection-core")

    run = await assurance_svc.run_probe_suite(
        session,
        org_id,
        suite.id,
        agent.id,
        version_id,
        triggered_by="person:test",
    )
    detail = await assurance_svc.get_probe_run_detail(session, org_id, run.id)
    assert detail.summary is not None
    assert detail.summary.valid_rollouts == detail.summary.attempt_budget
    assert detail.summary.execution_verified_pass + detail.summary.execution_verified_fail > 0
    assert detail.summary.judge_advisory_pass == 0
    for row in detail.results:
        assert row.oracle_verdict
        if row.oracle_verdict == OracleVerdict.FAIL.value:
            assert row.gate_passed is False


async def test_probe_run_detail_isolated_by_org(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    agent = await make_agent(session, org_id)
    version_id = await _publish(session, org_id, agent.id, agent.urn)
    suites = await assurance_repo.list_probe_suites(session, org_id)
    suite = suites[0]
    run = await assurance_svc.run_probe_suite(
        session,
        org_id,
        suite.id,
        agent.id,
        version_id,
        triggered_by="person:test",
    )
    with pytest.raises(assurance_svc.ProbeRunNotFoundError):
        await assurance_svc.get_probe_run_detail(session, other_org_id, run.id)


async def test_rule_gap_reports_missing_template(session: AsyncSession, org_id: uuid.UUID) -> None:
    agent = await make_agent(session, org_id)
    version_id = await _publish(session, org_id, agent.id, agent.urn)
    report = await assurance_svc.compute_rule_gaps(session, org_id, agent.id, version_id)
    tool = next((g for g in report.gaps if g.template_id == "TOOL-001-allowlist"), None)
    if tool is not None:
        assert tool.status == "covered"
        assert tool.suggested_obligation is None
    res = next((g for g in report.gaps if g.template_id == "RES-001-forbid-cross-border"), None)
    if res is not None:
        assert res.status == "missing"
        assert res.suggested_obligation is not None
    for gap in report.gaps:
        assert gap.template_id
        assert gap.status in ("covered", "partial", "missing", "conflict")


async def test_probe_run_results_json_respects_size_bounds(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """Stored probe outcomes must not carry prompt-sized payloads (AGENTS.md rule 5)."""
    import json

    agent = await make_agent(session, org_id)
    version_id = await _publish(session, org_id, agent.id, agent.urn)
    suites = await assurance_repo.list_probe_suites(session, org_id)
    suite = next(s for s in suites if s.slug == "prompt-injection-core")
    run = await assurance_svc.run_probe_suite(
        session,
        org_id,
        suite.id,
        agent.id,
        version_id,
        triggered_by="person:test",
    )
    detail = await assurance_svc.get_probe_run_detail(session, org_id, run.id)
    for row in detail.results:
        blob = json.dumps(row.model_dump())
        assert "prompt" not in blob.lower()
        assert len(blob.encode("utf-8")) <= 4096
        assert len(row.response_digest.encode("utf-8")) <= 80
