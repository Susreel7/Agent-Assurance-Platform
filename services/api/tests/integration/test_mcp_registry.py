"""The MCP registry against real Postgres.

What is checked here is the sequence the product exists for: register a server, discover
what it advertises, approve that, grant it, and then have the server change underneath.
The drift detection, the snapshot immutability and the pinning behaviour are each a
read-compare-write against a locked row, so none of them can be tested without a database.
"""

from __future__ import annotations

import hashlib
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.mcp_registry import service
from app.domains.mcp_registry.schemas import (
    CapabilityDeclared,
    CapabilityKind,
    CapabilityReview,
    GrantCreate,
    HealthState,
    Quarantine,
    RiskTier,
    ServerRegister,
    ServerState,
    SnapshotSubmit,
    Transport,
)
from app.domains.registry.schemas import LifecycleState

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

ACTOR = "person:it@test.example"
ENV = LifecycleState.PRODUCTION


def _tool(name: str, *, schema: str | None = None, read_only: bool = True) -> CapabilityDeclared:
    """A declared tool. The schema digest defaults to one derived from the name, so two
    calls for the same tool agree and two different tools do not collide."""
    return CapabilityDeclared(
        kind=CapabilityKind.TOOL,
        name=name,
        input_schema_digest=schema or hashlib.sha256(name.encode()).hexdigest(),
        declared_read_only=read_only,
    )


async def _server(
    session: AsyncSession,
    org_id: uuid.UUID,
    slug: str = "files",
    *,
    environments: list[LifecycleState] | None = None,
) -> uuid.UUID:
    out = await service.register_server(
        session,
        org_id,
        ServerRegister(
            slug=slug,
            name="Files",
            transport=Transport.HTTP,
            endpoint_url="https://files.test.example/mcp",
            environments=environments or [ENV],
        ),
        actor=ACTOR,
    )
    return out.id


async def _approved(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    slug: str = "files",
    tools: list[str] | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    """A server whose current capability set has been reviewed and approved."""
    server_id = await _server(session, org_id, slug)
    snapshot = await service.submit_snapshot(
        session,
        org_id,
        server_id,
        SnapshotSubmit(capabilities=[_tool(name) for name in (tools or ["read_file"])]),
        actor="service:discovery",
    )
    await service.approve_snapshot(session, org_id, server_id, snapshot.id, actor=ACTOR)
    return server_id, snapshot.id


# ---- registration confers nothing -----------------------------------------------------


async def test_a_registered_server_denies_every_call_until_it_is_approved(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """Registration is an intent to govern, not a permission.

    The direction that matters: a server appearing in the registry must not become callable
    as a side effect of being written down.
    """
    server_id = await _server(session, org_id)
    server = await service.get_server(session, org_id, server_id)
    assert server.state is ServerState.DRAFT
    assert server.approved_snapshot_id is None

    decision = await service.decide(
        session,
        org_id,
        server_slug="files",
        capability_name="read_file",
        subjects=[("agent", uuid.uuid4())],
        environment=ENV.value,
    )
    assert not decision.allowed


async def test_an_approved_server_still_denies_a_subject_with_no_grant(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """Approval says the tools were reviewed, not that anyone may call them."""
    await _approved(session, org_id)

    decision = await service.decide(
        session,
        org_id,
        server_slug="files",
        capability_name="read_file",
        subjects=[("agent", uuid.uuid4())],
        environment=ENV.value,
    )
    assert not decision.allowed
    assert decision.reason_code


async def test_an_approved_and_granted_call_is_allowed(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """The positive path, so the denials above are not passing for the wrong reason."""
    server_id, _ = await _approved(session, org_id)
    agent_id = uuid.uuid4()
    await service.grant(
        session,
        org_id,
        server_id,
        GrantCreate(subject_kind="agent", subject_id=agent_id, environments=[ENV]),
        actor=ACTOR,
    )

    decision = await service.decide(
        session,
        org_id,
        server_slug="files",
        capability_name="read_file",
        subjects=[("agent", agent_id)],
        environment=ENV.value,
    )
    assert decision.allowed


async def test_a_grant_does_not_reach_an_environment_it_does_not_name(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """A staging grant that works in production is the whole point of having environments."""
    server_id = await _server(
        session,
        org_id,
        environments=[LifecycleState.STAGING, LifecycleState.PRODUCTION],
    )
    snapshot = await service.submit_snapshot(
        session,
        org_id,
        server_id,
        SnapshotSubmit(capabilities=[_tool("read_file")]),
        actor="service:discovery",
    )
    await service.approve_snapshot(session, org_id, server_id, snapshot.id, actor=ACTOR)
    agent_id = uuid.uuid4()
    await service.grant(
        session,
        org_id,
        server_id,
        GrantCreate(
            subject_kind="agent",
            subject_id=agent_id,
            environments=[LifecycleState.STAGING],
        ),
        actor=ACTOR,
    )

    decision = await service.decide(
        session,
        org_id,
        server_slug="files",
        capability_name="read_file",
        subjects=[("agent", agent_id)],
        environment=LifecycleState.PRODUCTION.value,
    )
    assert not decision.allowed


# ---- drift ----------------------------------------------------------------------------


async def test_rediscovering_the_same_capabilities_is_not_drift(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """Discovery runs continuously, so an unchanged server must stay quiet.

    It also must not grow the snapshot table: one row per distinct capability set is what
    keeps this bounded when discovery runs every few minutes against thousands of servers.
    """
    server_id, first = await _approved(session, org_id)

    again = await service.submit_snapshot(
        session,
        org_id,
        server_id,
        SnapshotSubmit(capabilities=[_tool("read_file")]),
        actor="service:discovery",
    )
    assert again.id == first

    server = await service.get_server(session, org_id, server_id)
    assert server.health is HealthState.HEALTHY

    count = await session.scalar(
        text("SELECT count(*) FROM mcp_snapshots WHERE server_id = :id"), {"id": server_id}
    )
    assert count == 1


async def test_a_new_tool_appearing_is_drift_and_is_not_auto_granted(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """The attack this registry exists to stop.

    A server that adds a tool after approval must not have it callable, and the console has
    to be able to say which tool appeared.
    """
    server_id, approved_id = await _approved(session, org_id)
    agent_id = uuid.uuid4()
    await service.grant(
        session,
        org_id,
        server_id,
        GrantCreate(subject_kind="agent", subject_id=agent_id, environments=[ENV]),
        actor=ACTOR,
    )

    observed = await service.submit_snapshot(
        session,
        org_id,
        server_id,
        SnapshotSubmit(capabilities=[_tool("read_file"), _tool("delete_everything")]),
        actor="service:discovery",
    )
    assert observed.id != approved_id

    server = await service.get_server(session, org_id, server_id)
    assert server.health is HealthState.DRIFT
    assert server.approved_snapshot_id == approved_id

    detail = await service.server_detail(session, org_id, server_id)
    assert detail.summary.drifted
    assert detail.added_capability_names == ["delete_everything"]

    decision = await service.decide(
        session,
        org_id,
        server_slug="files",
        capability_name="delete_everything",
        subjects=[("agent", agent_id)],
        environment=ENV.value,
    )
    assert not decision.allowed


async def test_a_tool_whose_schema_changed_is_reported_as_changed_not_added(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """Same name, different shape — the substitution a name-only comparison would miss.

    The console has to distinguish it from an addition, because "read_file grew a `write_to`
    argument" and "a new tool appeared" need different reviews.
    """
    server_id, _ = await _approved(session, org_id)

    await service.submit_snapshot(
        session,
        org_id,
        server_id,
        SnapshotSubmit(capabilities=[_tool("read_file", schema="b" * 64)]),
        actor="service:discovery",
    )

    detail = await service.server_detail(session, org_id, server_id)
    assert detail.changed_capability_names == ["read_file"]
    assert detail.added_capability_names == []
    assert detail.removed_capability_names == []


async def test_a_tool_disappearing_is_reported_as_removed(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    server_id, _ = await _approved(session, org_id, tools=["read_file", "list_files"])

    await service.submit_snapshot(
        session,
        org_id,
        server_id,
        SnapshotSubmit(capabilities=[_tool("read_file")]),
        actor="service:discovery",
    )

    detail = await service.server_detail(session, org_id, server_id)
    assert detail.removed_capability_names == ["list_files"]


async def test_approving_the_observed_snapshot_clears_the_drift(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """Drift is a question, and this is the answer that closes it."""
    server_id, _ = await _approved(session, org_id)
    observed = await service.submit_snapshot(
        session,
        org_id,
        server_id,
        SnapshotSubmit(capabilities=[_tool("read_file"), _tool("write_file")]),
        actor="service:discovery",
    )

    await service.approve_snapshot(session, org_id, server_id, observed.id, actor=ACTOR)

    server = await service.get_server(session, org_id, server_id)
    assert server.health is HealthState.HEALTHY
    assert server.approved_snapshot_id == observed.id


async def test_an_undiscovered_server_is_unknown_rather_than_drifted(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """A server nobody has reached yet is not a change to review.

    Conflating the two puts every newly registered server in the drift queue, which is how
    the queue stops meaning anything.
    """
    server_id = await _server(session, org_id)
    server = await service.get_server(session, org_id, server_id)
    assert server.health is HealthState.UNKNOWN

    detail = await service.server_detail(session, org_id, server_id)
    assert not detail.summary.drifted


# ---- pinning --------------------------------------------------------------------------


async def test_approving_a_new_snapshot_does_not_widen_a_pinned_grant(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """Pinning is the default precisely so approval is not a back door to wider access.

    Without it, approving a snapshot that added a tool hands that tool to every existing
    grant, and nobody reviewed that.
    """
    server_id, _ = await _approved(session, org_id)
    agent_id = uuid.uuid4()
    await service.grant(
        session,
        org_id,
        server_id,
        GrantCreate(subject_kind="agent", subject_id=agent_id, environments=[ENV]),
        actor=ACTOR,
    )

    widened = await service.submit_snapshot(
        session,
        org_id,
        server_id,
        SnapshotSubmit(capabilities=[_tool("read_file"), _tool("delete_everything")]),
        actor="service:discovery",
    )
    await service.approve_snapshot(session, org_id, server_id, widened.id, actor=ACTOR)

    still_denied = await service.decide(
        session,
        org_id,
        server_slug="files",
        capability_name="delete_everything",
        subjects=[("agent", agent_id)],
        environment=ENV.value,
    )
    assert not still_denied.allowed

    # The tool the grant was reviewed against keeps working.
    unaffected = await service.decide(
        session,
        org_id,
        server_slug="files",
        capability_name="read_file",
        subjects=[("agent", agent_id)],
        environment=ENV.value,
    )
    assert unaffected.allowed


async def test_an_unpinned_grant_follows_the_current_approval(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """The opt-out exists for internal servers the same team owns.

    Tested so the pinned case above is known to be doing something, rather than pinning
    being the only behaviour the code has.
    """
    server_id, _ = await _approved(session, org_id)
    agent_id = uuid.uuid4()
    await service.grant(
        session,
        org_id,
        server_id,
        GrantCreate(
            subject_kind="agent",
            subject_id=agent_id,
            environments=[ENV],
            pin_approved_snapshot=False,
        ),
        actor=ACTOR,
    )

    widened = await service.submit_snapshot(
        session,
        org_id,
        server_id,
        SnapshotSubmit(capabilities=[_tool("read_file"), _tool("summarise")]),
        actor="service:discovery",
    )
    await service.approve_snapshot(session, org_id, server_id, widened.id, actor=ACTOR)

    decision = await service.decide(
        session,
        org_id,
        server_slug="files",
        capability_name="summarise",
        subjects=[("agent", agent_id)],
        environment=ENV.value,
    )
    assert decision.allowed


# ---- immutability and review ----------------------------------------------------------


async def test_an_approved_snapshot_cannot_be_rewritten(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """ "These are the tools we reviewed" is the claim everything else rests on.

    Enforced by a trigger, so the only way to see it is through a real server.
    """
    _, snapshot_id = await _approved(session, org_id)

    with pytest.raises(Exception, match="immutable"):
        await session.execute(
            text("UPDATE mcp_snapshots SET capability_digest = :digest WHERE id = :id"),
            {"digest": b"\x00" * 32, "id": snapshot_id},
        )
        await session.flush()


async def test_an_approval_cannot_be_reattributed(session: AsyncSession, org_id: uuid.UUID) -> None:
    """An approval moved to a different name is an approval that person never gave."""
    _, snapshot_id = await _approved(session, org_id)

    with pytest.raises(Exception, match="already recorded"):
        await session.execute(
            text("UPDATE mcp_snapshots SET approved_by = :who WHERE id = :id"),
            {"who": "person:someone-else@test.example", "id": snapshot_id},
        )
        await session.flush()


async def test_a_reviewer_can_still_record_a_verdict_on_a_frozen_snapshot(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """The distinction the trigger is built around.

    What the server *said* is frozen evidence; what a human *concluded* is an opinion that
    may be corrected. A trigger written too broadly would make review impossible, which is
    the failure mode that looks like the feature working.
    """
    server_id, _ = await _approved(session, org_id)
    detail = await service.server_detail(session, org_id, server_id)
    capability = detail.capabilities[0]

    reviewed = await service.review_capability(
        session,
        org_id,
        capability.id,
        CapabilityReview(
            verified_risk=RiskTier.HIGH,
            verified_write=True,
            verified_irreversible=True,
            review_note="Writes outside the sandbox root.",
        ),
        actor=ACTOR,
    )

    assert reviewed.verified_irreversible
    assert reviewed.reviewed_by == ACTOR
    # The server declared read-only; review found a write. That contradiction is the
    # registry's most useful single signal, so it is surfaced rather than merely stored.
    assert reviewed.annotation_mismatch


# ---- quarantine -----------------------------------------------------------------------


async def test_quarantine_denies_everything_without_unpicking_the_grants(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """One row, and the server stops. Revoking grants individually is the slow, lossy
    version of the same intent — and the state to restore afterwards is already recorded."""
    server_id, _ = await _approved(session, org_id)
    agent_id = uuid.uuid4()
    await service.grant(
        session,
        org_id,
        server_id,
        GrantCreate(subject_kind="agent", subject_id=agent_id, environments=[ENV]),
        actor=ACTOR,
    )

    await service.quarantine(
        session, org_id, server_id, Quarantine(reason="Credential exfiltration suspected.")
    )

    blocked = await service.decide(
        session,
        org_id,
        server_slug="files",
        capability_name="read_file",
        subjects=[("agent", agent_id)],
        environment=ENV.value,
    )
    assert not blocked.allowed

    await service.release(session, org_id, server_id)

    restored = await service.decide(
        session,
        org_id,
        server_slug="files",
        capability_name="read_file",
        subjects=[("agent", agent_id)],
        environment=ENV.value,
    )
    assert restored.allowed


async def test_releasing_a_server_with_nothing_approved_lands_in_review(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """Returning it to `approved` would have the console claim it works while every call
    is denied, which is the hardest kind of outage to diagnose."""
    server_id = await _server(session, org_id)
    await service.quarantine(session, org_id, server_id, Quarantine(reason="Unknown provenance."))

    released = await service.release(session, org_id, server_id)
    assert released.state is ServerState.IN_REVIEW


# ---- tenancy --------------------------------------------------------------------------


async def test_one_account_cannot_decide_against_another_accounts_server(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    """Slugs are unique per account, so `files` exists in many of them.

    An unscoped lookup here would resolve one customer's request against another's server.
    """
    server_id, _ = await _approved(session, org_id)
    agent_id = uuid.uuid4()
    await service.grant(
        session,
        org_id,
        server_id,
        GrantCreate(subject_kind="agent", subject_id=agent_id, environments=[ENV]),
        actor=ACTOR,
    )

    decision = await service.decide(
        session,
        other_org_id,
        server_slug="files",
        capability_name="read_file",
        subjects=[("agent", agent_id)],
        environment=ENV.value,
    )
    assert not decision.allowed


async def test_the_same_slug_can_exist_in_two_accounts(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    first = await _server(session, org_id, "files")
    second = await _server(session, other_org_id, "files")
    assert first != second

    with pytest.raises(service.DuplicateServerError):
        await _server(session, org_id, "files")
