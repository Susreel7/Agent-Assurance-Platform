"""Repository behaviour against a real Postgres.

Scoped to what a mocked session cannot show: partition routing, the append-only
triggers, upsert conflict targets, recursive CTEs and tenant scoping. Every test here
corresponds to something that was either broken or unproven until the migrations met a
real server.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.evidence import repository as evidence_repo
from app.domains.graph import repository as graph_repo
from app.domains.registry import repository as registry_repo

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


async def make_agent(session: AsyncSession, org_id: uuid.UUID, *, urn: str | None = None) -> Any:
    return await registry_repo.insert_agent(
        session,
        org_id,
        {
            "id": uuid.uuid4(),
            "urn": urn or f"urn:aap:it:{uuid.uuid4().hex[:8]}:eu",
            "display_name": "Integration Agent",
            "lifecycle_state": "production",
        },
    )


async def make_version(
    session: AsyncSession, org_id: uuid.UUID, agent_id: uuid.UUID, semver: str = "1.0.0"
) -> Any:
    version = await registry_repo.insert_version(
        session,
        org_id,
        agent_id,
        {
            "id": uuid.uuid4(),
            "semver": semver,
            "descriptor_json": {"aap_version": "0.1"},
            "descriptor_digest": "sha256:" + uuid.uuid4().hex * 2,
            "environment": "production",
            "published_by": "person:it@test.example",
        },
    )
    await session.flush()
    return version


def event_row(
    org_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    occurred_at: datetime,
    digest_seed: str,
    kind: str = "policy_decision",
) -> dict[str, Any]:
    return {
        "id": uuid.uuid4(),
        "org_id": org_id,
        "occurred_at": occurred_at,
        "kind": kind,
        "agent_id": agent_id,
        "actor": "service:collector",
        "action": "policy.evaluate",
        "outcome": "allow",
        "detected_by": "collector",
        "subject_ref": "integration",
        "detail": {},
        "content_digest": "sha256:" + digest_seed.ljust(64, "0")[:64],
    }


# ----------------------------------------------------------------------
# Registry
# ----------------------------------------------------------------------


async def test_an_agent_round_trips(session: AsyncSession, org_id: uuid.UUID) -> None:
    agent = await make_agent(session, org_id)
    await session.flush()

    found = await registry_repo.get_agent(session, org_id, agent.id)
    assert found is not None
    assert found.urn == agent.urn


async def test_an_agent_is_invisible_to_another_tenant(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    """The org_id filter, verified rather than assumed.

    Every repository read takes org_id. This test fails if one forgets it, which is the
    single highest-consequence bug class in a multi-tenant control plane.
    """
    agent = await make_agent(session, org_id)
    await session.flush()

    assert await registry_repo.get_agent(session, other_org_id, agent.id) is None
    assert await registry_repo.get_agent_by_urn(session, other_org_id, agent.urn) is None


async def test_two_tenants_may_register_the_same_urn(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    """Uniqueness is per tenant. Two of our clients can both run an agent called
    `urn:aap:acme:claims:eu`, and a global unique index would let one discover the
    other's fleet by collision."""
    urn = f"urn:aap:it:shared-{uuid.uuid4().hex[:8]}:eu"

    await make_agent(session, org_id, urn=urn)
    await make_agent(session, other_org_id, urn=urn)
    await session.flush()

    mine = await registry_repo.get_agent_by_urn(session, org_id, urn)
    theirs = await registry_repo.get_agent_by_urn(session, other_org_id, urn)
    assert mine is not None and theirs is not None
    assert mine.id != theirs.id


async def test_a_published_version_cannot_be_rewritten(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """The trigger from 0001, exercised through the ORM.

    "This is the version we accredited" is the product's central claim. A mocked session
    cannot tell you whether the database will actually refuse the update.
    """
    agent = await make_agent(session, org_id)
    await session.flush()

    version = await registry_repo.insert_version(
        session,
        org_id,
        agent.id,
        {
            "id": uuid.uuid4(),
            "semver": "1.0.0",
            "descriptor_json": {"aap_version": "0.1"},
            "descriptor_digest": "sha256:" + "a" * 64,
            "environment": "production",
            "published_by": "person:it@test.example",
        },
    )
    await session.flush()

    # DBAPIError rather than IntegrityError: the refusal comes from a trigger raising,
    # not from a constraint, so it arrives as a raw database error.
    with pytest.raises(DBAPIError, match="immutable"):
        await session.execute(
            text("UPDATE agent_versions SET semver = '9.9.9' WHERE id = :id"),
            {"id": version.id},
        )


async def test_semver_is_unique_within_an_agent(session: AsyncSession, org_id: uuid.UUID) -> None:
    agent = await make_agent(session, org_id)
    await session.flush()

    def payload() -> dict[str, Any]:
        return {
            "id": uuid.uuid4(),
            "semver": "1.0.0",
            "descriptor_json": {"aap_version": "0.1"},
            "descriptor_digest": "sha256:" + "b" * 64,
            "environment": "production",
            "published_by": "person:it@test.example",
        }

    await registry_repo.insert_version(session, org_id, agent.id, payload())
    await session.flush()
    assert await registry_repo.exists_semver(session, org_id, agent.id, "1.0.0")

    with pytest.raises(IntegrityError):
        await registry_repo.insert_version(session, org_id, agent.id, payload())
        await session.flush()


# ----------------------------------------------------------------------
# Evidence
# ----------------------------------------------------------------------


async def test_events_route_to_a_monthly_partition(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """Partition pruning is the reason evidence stays queryable at scale. If rows land
    in the parent or the default partition, every explorer query degrades to a full
    scan of the whole history."""
    agent = await make_agent(session, org_id)
    await session.flush()

    now = datetime.now(UTC)
    ids = await evidence_repo.insert_events(
        session, org_id, [event_row(org_id, agent.id, occurred_at=now, digest_seed="c1")]
    )
    await session.flush()

    partition = (
        await session.execute(
            text("SELECT tableoid::regclass::text FROM evidence_events WHERE id = :id"),
            {"id": ids[0]},
        )
    ).scalar_one()

    assert partition != "evidence_events", "row landed in the parent table"
    assert partition.startswith("evidence_events_"), partition
    assert not partition.endswith("_default"), "row fell into the catch-all partition"


async def test_evidence_cannot_be_updated_or_deleted(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    agent = await make_agent(session, org_id)
    await session.flush()

    ids = await evidence_repo.insert_events(
        session,
        org_id,
        [event_row(org_id, agent.id, occurred_at=datetime.now(UTC), digest_seed="c2")],
    )
    await session.flush()

    with pytest.raises(DBAPIError, match=r"append-only|immutable"):
        await session.execute(
            text("UPDATE evidence_events SET subject_ref = 'tampered' WHERE id = :id"),
            {"id": ids[0]},
        )


async def test_anchoring_stamps_the_batch_onto_every_event(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """The regression test for the sealing bug.

    `anchor_events` builds a VALUES list with bound parameters. Written as `:id_0::uuid`
    it produced a statement SQLAlchemy never bound, because text() leaves a parameter
    alone when a colon follows it — so sealing died with a syntax error the first time
    it ran against Postgres, while every unit test passed. See D-021.
    """
    agent = await make_agent(session, org_id)
    await session.flush()

    base = datetime.now(UTC) - timedelta(minutes=5)
    rows = [
        event_row(org_id, agent.id, occurred_at=base + timedelta(seconds=i), digest_seed=f"d{i}")
        for i in range(3)
    ]
    ids = await evidence_repo.insert_events(session, org_id, rows)
    await session.flush()

    unsealed = await evidence_repo.fetch_unsealed(
        session, org_id, until=datetime.now(UTC), limit=100
    )
    assert len(unsealed) == 3

    batch = await evidence_repo.insert_batch(
        session,
        org_id,
        {
            "id": uuid.uuid4(),
            "seq": 0,
            "window_start": base,
            "window_end": datetime.now(UTC),
            "leaf_count": 3,
            "tree_size": 3,
            "merkle_root": "sha256:" + "e" * 64,
            "prev_batch_digest": "sha256:" + "0" * 64,
            "batch_digest": "sha256:" + "f" * 64,
        },
    )
    await session.flush()

    anchored = await evidence_repo.anchor_events(
        session,
        org_id,
        batch.id,
        [(e.id, e.occurred_at, i) for i, e in enumerate(unsealed)],
    )
    assert anchored == 3, "anchor_events did not stamp every event"

    leaves = await evidence_repo.fetch_batch_leaves(session, org_id, batch.id)
    assert [index for index, _, _ in leaves] == [0, 1, 2]
    assert {event_id for _, event_id, _ in leaves} == set(ids)


async def test_anchoring_is_refused_a_second_time(session: AsyncSession, org_id: uuid.UUID) -> None:
    """The append-only trigger permits the anchor update exactly once. Without that, a
    second seal could move an event into a different batch and silently invalidate the
    proof a customer already holds."""
    agent = await make_agent(session, org_id)
    await session.flush()

    occurred = datetime.now(UTC) - timedelta(minutes=1)
    ids = await evidence_repo.insert_events(
        session, org_id, [event_row(org_id, agent.id, occurred_at=occurred, digest_seed="e1")]
    )
    await session.flush()

    async def seal(seq: int, marker: str) -> uuid.UUID:
        batch = await evidence_repo.insert_batch(
            session,
            org_id,
            {
                "id": uuid.uuid4(),
                "seq": seq,
                "window_start": occurred,
                "window_end": datetime.now(UTC),
                "leaf_count": 1,
                "tree_size": seq + 1,
                "merkle_root": "sha256:" + marker * 64,
                "prev_batch_digest": "sha256:" + "0" * 64,
                "batch_digest": "sha256:" + marker * 64,
            },
        )
        await session.flush()
        return batch.id

    first = await seal(0, "1")
    assert await evidence_repo.anchor_events(session, org_id, first, [(ids[0], occurred, 0)]) == 1

    # The second attempt matches nothing, because the predicate requires batch_id IS NULL.
    second = await seal(1, "2")
    assert await evidence_repo.anchor_events(session, org_id, second, [(ids[0], occurred, 0)]) == 0


async def test_unsealed_events_come_back_in_leaf_order(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """Leaf order is part of the frozen chain contract: a proof built against a
    different order recomputes a different root, so this ordering is load-bearing."""
    agent = await make_agent(session, org_id)
    await session.flush()

    base = datetime.now(UTC) - timedelta(minutes=10)
    offsets = [4, 0, 2, 1, 3]
    rows = [
        event_row(org_id, agent.id, occurred_at=base + timedelta(seconds=o), digest_seed=f"f{o}")
        for o in offsets
    ]
    await evidence_repo.insert_events(session, org_id, rows)
    await session.flush()

    unsealed = await evidence_repo.fetch_unsealed(
        session, org_id, until=datetime.now(UTC), limit=100
    )
    times = [e.occurred_at for e in unsealed]
    assert times == sorted(times)


async def test_evidence_does_not_leak_across_tenants(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    agent = await make_agent(session, org_id)
    await session.flush()

    await evidence_repo.insert_events(
        session,
        org_id,
        [event_row(org_id, agent.id, occurred_at=datetime.now(UTC), digest_seed="a9")],
    )
    await session.flush()

    assert await evidence_repo.count_events(session, org_id) >= 1
    assert await evidence_repo.count_events(session, other_org_id) == 0


# ----------------------------------------------------------------------
# Graph
# ----------------------------------------------------------------------


async def _node(session: AsyncSession, org_id: uuid.UUID, key: str) -> Any:
    node = await graph_repo.upsert_node(
        session,
        org_id,
        {
            "id": uuid.uuid4(),
            "kind": "agent",
            "node_key": key,
            "label": key,
            # graph_nodes_provenance_present: a node must have come from somewhere.
            # A node that is neither declared nor observed is an assertion with no
            # source, which is exactly what the graph must never contain.
            "is_declared": True,
        },
    )
    await session.flush()
    return node


def _edge_values(
    src: Any, dst: Any, *, agent_version_id: uuid.UUID | None = None
) -> dict[str, Any]:
    """An agent-to-agent delegation edge.

    `delegates_to` from the graph_edge_kind enum, because that is the relationship blast
    radius is asked about: if this agent changes, which agents that hand work to it are
    affected.
    """
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "src_id": src.id,
        "dst_id": dst.id,
        "kind": "delegates_to",
        "source": "declared",
    }
    if agent_version_id is not None:
        values["agent_version_id"] = agent_version_id
    return values


async def test_blast_radius_walks_the_graph_transitively(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """The recursive CTE. A -> B -> C must return both B and C with increasing depth.

    This query cannot be unit tested at all: there is no way to fake a Postgres
    WITH RECURSIVE, and "what else breaks if this agent changes" is the question the
    graph exists to answer.
    """
    a = await _node(session, org_id, f"a-{uuid.uuid4().hex[:6]}")
    b = await _node(session, org_id, f"b-{uuid.uuid4().hex[:6]}")
    c = await _node(session, org_id, f"c-{uuid.uuid4().hex[:6]}")

    for src, dst in ((a, b), (b, c)):
        await graph_repo.upsert_edge(session, org_id, _edge_values(src, dst))
    await session.flush()

    reached = await graph_repo.fetch_blast_radius(session, org_id, a.id, max_depth=5)
    by_id = {row.id: row.depth for row in reached}

    assert b.id in by_id, "direct neighbour missing"
    assert c.id in by_id, "transitive neighbour missing — the CTE is not recursing"
    assert by_id[b.id] == 1
    assert by_id[c.id] == 2


async def test_blast_radius_terminates_on_a_cycle(session: AsyncSession, org_id: uuid.UUID) -> None:
    """Agents delegating in a loop is a real topology, not a pathological one. An
    unguarded recursive CTE would spin until the statement timeout."""
    a = await _node(session, org_id, f"cy-a-{uuid.uuid4().hex[:6]}")
    b = await _node(session, org_id, f"cy-b-{uuid.uuid4().hex[:6]}")

    for src, dst in ((a, b), (b, a)):
        await graph_repo.upsert_edge(session, org_id, _edge_values(src, dst))
    await session.flush()

    reached = await graph_repo.fetch_blast_radius(session, org_id, a.id, max_depth=8)
    assert reached, "a cycle returned nothing at all"
    assert max(row.depth for row in reached) <= 8


async def test_upserting_an_edge_twice_keeps_one_row(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """The conflict target has to match the real unique constraint. If it does not,
    the second call raises instead of updating, and graph rebuilds fail intermittently
    depending on what the discovery pass saw."""
    a = await _node(session, org_id, f"up-a-{uuid.uuid4().hex[:6]}")
    b = await _node(session, org_id, f"up-b-{uuid.uuid4().hex[:6]}")

    first = await graph_repo.upsert_edge(session, org_id, _edge_values(a, b))
    await session.flush()
    second = await graph_repo.upsert_edge(session, org_id, _edge_values(a, b))
    await session.flush()

    assert first.id == second.id, "upsert created a duplicate edge"

    count = (
        await session.execute(
            text(
                "SELECT count(*) FROM graph_edges WHERE org_id = :org "
                "AND src_id = :src AND dst_id = :dst AND kind = 'delegates_to'"
            ),
            {"org": org_id, "src": a.id, "dst": b.id},
        )
    ).scalar_one()
    assert count == 1


async def test_retiring_declared_edges_keeps_the_ones_still_declared(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """Reconciliation builds a VALUES list from descriptor-supplied values, so it is
    both a SQL-injection surface and — as it turned out — a place where a `:param::type`
    cast stopped the parameters binding at all. See D-021."""
    a = await _node(session, org_id, f"rt-a-{uuid.uuid4().hex[:6]}")
    b = await _node(session, org_id, f"rt-b-{uuid.uuid4().hex[:6]}")
    c = await _node(session, org_id, f"rt-c-{uuid.uuid4().hex[:6]}")

    # A real version row: graph_edges.agent_version_id is a foreign key, which is what
    # makes "these edges were declared by that descriptor" a fact rather than a label.
    agent = await make_agent(session, org_id)
    await session.flush()
    version_id = (await make_version(session, org_id, agent.id)).id

    for dst in (b, c):
        await graph_repo.upsert_edge(
            session, org_id, _edge_values(a, dst, agent_version_id=version_id)
        )
    await session.flush()

    retired = await graph_repo.retire_declared_edges_not_in(
        session, org_id, version_id, [(a.id, b.id, "delegates_to")]
    )
    assert retired == 1, f"expected exactly the undeclared edge to retire, got {retired}"


async def test_graph_reads_are_tenant_scoped(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    a = await _node(session, org_id, f"ts-a-{uuid.uuid4().hex[:6]}")
    b = await _node(session, org_id, f"ts-b-{uuid.uuid4().hex[:6]}")
    await graph_repo.upsert_edge(session, org_id, _edge_values(a, b))
    await session.flush()

    assert await graph_repo.fetch_blast_radius(session, org_id, a.id, max_depth=3)
    assert not await graph_repo.fetch_blast_radius(session, other_org_id, a.id, max_depth=3)
