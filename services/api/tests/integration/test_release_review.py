"""Release review brief and digest-bound approval."""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.registry import service as registry_svc
from app.domains.registry.schemas import AgentCreate, LifecycleState, VersionPublish
from app.domains.releases import service as releases_svc
from app.domains.releases.schemas import ReleaseCreate, ReleaseState, ReleaseTransitionRequest

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


def _descriptor(urn: str, version: str, **extra: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "aap_version": "0.1",
        "agent": {"urn": urn, "version": version, "lifecycle_state": "production"},
        "accountability": {
            "owning_team": "Platform",
            "accountable_person": "person:qa@test.example",
        },
        "runtime": {"framework": "langgraph", "autonomy": "supervised"},
        "models": [{"provider": "anthropic", "id": "claude-sonnet-4", "role": "primary"}],
        "data": {"classes": ["customer_pii"]},
    }
    base.update(extra)
    return base


async def _agent_with_two_versions(
    session: AsyncSession, org_id: uuid.UUID
) -> tuple[Any, uuid.UUID, uuid.UUID, str]:
    slug = uuid.uuid4().hex[:8]
    urn = f"urn:aap:review:qa:{slug}"
    agent = await registry_svc.create_agent(
        session,
        org_id,
        AgentCreate(
            urn=urn,
            display_name="Review Agent",
            lifecycle_state=LifecycleState.PRODUCTION,
        ),
    )
    v1 = await registry_svc.publish_version(
        session,
        org_id,
        agent.id,
        VersionPublish(
            semver="1.0.0",
            descriptor=_descriptor(urn, "1.0.0"),
            environment=LifecycleState.PRODUCTION,
            published_by="person:qa@test.example",
        ),
    )
    v2 = await registry_svc.publish_version(
        session,
        org_id,
        agent.id,
        VersionPublish(
            semver="1.1.0",
            descriptor=_descriptor(
                urn,
                "1.1.0",
                runtime={"framework": "langgraph", "autonomy": "autonomous"},
            ),
            environment=LifecycleState.PRODUCTION,
            published_by="person:qa@test.example",
        ),
    )
    return agent, v1.id, v2.id, v2.descriptor_digest


async def test_review_brief_endpoint(session: AsyncSession, org_id: uuid.UUID) -> None:
    agent, v1_id, v2_id, digest = await _agent_with_two_versions(session, org_id)
    release = await releases_svc.create_release(
        session,
        org_id,
        ReleaseCreate(
            agent_id=agent.id,
            from_version_id=v1_id,
            to_version_id=v2_id,
            release_tag=f"rel-{uuid.uuid4().hex[:6]}",
            proposed_by="person:qa@test.example",
        ),
    )
    brief = await releases_svc.get_review_brief(session, org_id, release.id)
    assert brief.descriptor_digest == digest
    assert brief.re_accreditation
    assert all(s.rule_ids for s in brief.re_accreditation)


async def test_approval_requires_matching_digest(session: AsyncSession, org_id: uuid.UUID) -> None:
    agent, v1_id, v2_id, digest = await _agent_with_two_versions(session, org_id)
    release = await releases_svc.create_release(
        session,
        org_id,
        ReleaseCreate(
            agent_id=agent.id,
            from_version_id=v1_id,
            to_version_id=v2_id,
            release_tag=f"rel-{uuid.uuid4().hex[:6]}",
            proposed_by="person:qa@test.example",
        ),
    )
    await releases_svc.transition_release(
        session,
        org_id,
        release.id,
        ReleaseTransitionRequest(
            target_state=ReleaseState.PROPOSED,
            actor="person:qa@test.example",
        ),
    )
    with pytest.raises(releases_svc.DigestMismatchError):
        await releases_svc.transition_release(
            session,
            org_id,
            release.id,
            ReleaseTransitionRequest(
                target_state=ReleaseState.APPROVED,
                actor="person:approver@test.example",
                reviewed_descriptor_digest="sha256:" + "f" * 64,
            ),
        )
    approved = await releases_svc.transition_release(
        session,
        org_id,
        release.id,
        ReleaseTransitionRequest(
            target_state=ReleaseState.APPROVED,
            actor="person:approver@test.example",
            reviewed_descriptor_digest=digest,
        ),
    )
    assert approved.reviewed_descriptor_digest == digest


async def test_cross_tenant_cannot_read_review_brief(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    agent, v1_id, v2_id, _digest = await _agent_with_two_versions(session, org_id)
    release = await releases_svc.create_release(
        session,
        org_id,
        ReleaseCreate(
            agent_id=agent.id,
            from_version_id=v1_id,
            to_version_id=v2_id,
            release_tag=f"rel-{uuid.uuid4().hex[:6]}",
        ),
    )
    with pytest.raises(releases_svc.ReleaseNotFoundError):
        await releases_svc.get_review_brief(session, other_org_id, release.id)
