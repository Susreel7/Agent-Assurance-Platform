"""The seed generator, run for real against a migrated database.

This is the demo path, so it gets a test rather than a manual check. It is also the
broadest write-path exercise in the suite: the seed goes through `service.py` for every
domain, so a run that completes means customers, engagements, service levels, agents,
ownership, versions, BOM, graph, releases through the materiality engine, accreditation
state transitions with separation of duties, evidence ingest, Merkle sealing, findings,
posture and SLO measurement all accept the same estate in one pass.

It runs on its own engine rather than the shared `session` fixture, because the seed
opens its own sessions through `app.db.session` — which is the point. Anything narrower
would test a different program.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.config import get_settings
from app.db import session as db_session
from seed import generate

pytestmark = pytest.mark.integration


@pytest_asyncio.fixture
async def seeded_org(
    database_url: str, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[AsyncEngine, uuid.UUID]]:
    """Point the app's own engine at the test database, seed a small estate, tear down.

    The seed resolves its organisation from `default_org_slug`, and migration 0001 seeds
    `default`, so nothing has to be provisioned here. The engine is disposed and the
    settings cache cleared on the way out so no other test inherits this wiring.
    """
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("AAP_ENVIRONMENT", "test")
    get_settings.cache_clear()
    await db_session.dispose_engine()

    # The seed refuses to run against a database that already holds an estate, and
    # returns 0 when it declines — so `run() == 0` does not mean "it seeded". Pointing
    # this suite at the Compose dev database therefore used to produce two failures
    # reading `assert 40 == 6`: the assertions were measuring the demo estate somebody
    # had seeded by hand. Skipping says that out loud instead of looking like a
    # regression in the generator.
    probe = create_async_engine(database_url)
    try:
        async with probe.connect() as conn:
            await conn.execute(text("SELECT set_config('app.bypass_rls', 'on', true)"))
            existing = int((await conn.execute(text("SELECT count(*) FROM agents"))).scalar_one())
    finally:
        await probe.dispose()
    if existing:
        pytest.skip(
            f"database already holds {existing} agents; the seed declines to add to an "
            "existing estate. Run against a throwaway database, or reset this one."
        )

    args = generate.parse_args(
        ["--agents", "6", "--teams", "2", "--days", "7", "--seed", "1234", "--quiet"]
    )
    assert await generate.run(args) == 0

    org_id = await generate.resolve_org_id()
    engine = create_async_engine(database_url)
    try:
        yield engine, org_id
    finally:
        await engine.dispose()
        await db_session.dispose_engine()
        get_settings.cache_clear()


async def _count(engine: AsyncEngine, sql: str) -> int:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT set_config('app.bypass_rls', 'on', true)"))
        return int((await conn.execute(text(sql))).scalar_one())


async def test_the_seed_builds_a_coherent_estate(
    seeded_org: tuple[AsyncEngine, uuid.UUID],
) -> None:
    engine, _org_id = seeded_org

    assert await _count(engine, "SELECT count(*) FROM customers") == len(generate.CUSTOMERS)
    assert await _count(engine, "SELECT count(*) FROM engagements") == len(generate.CUSTOMERS)
    assert await _count(engine, "SELECT count(*) FROM agents") == 6

    # Every agent must have a current version and at least one owner, or the console
    # renders rows with empty columns and the drift calculation has nothing to compare.
    assert await _count(engine, "SELECT count(*) FROM agents WHERE current_version_id IS NULL") == 0
    assert (
        await _count(
            engine,
            "SELECT count(*) FROM agents a WHERE NOT EXISTS "
            "(SELECT 1 FROM agent_ownership o WHERE o.agent_id = a.id)",
        )
        == 0
    )


async def test_the_seeded_evidence_chain_is_sealed_and_verifies(
    seeded_org: tuple[AsyncEngine, uuid.UUID],
) -> None:
    """A seeded estate with an unsealed or broken chain would demo the opposite claim.

    `generate.run` already refuses to finish on an invalid chain. This checks the shape
    that makes the claim meaningful: more than one batch, so batch N commits to N-1, and
    nothing left dangling behind the seal lag.

    The lag qualifier is the real invariant, not a concession to the seed. Events inside
    the lag are *supposed* to be unanchored — that window is held open for a collector
    replaying a buffered outage. Asserting a globally empty backlog would fail against a
    live collector and teach whoever hit it to weaken the test.
    """
    engine, _org_id = seeded_org

    assert await _count(engine, "SELECT count(*) FROM evidence_batches") >= 2
    assert await _count(engine, "SELECT count(*) FROM evidence_events") > 0
    assert (
        await _count(
            engine,
            "SELECT count(*) FROM evidence_events "
            "WHERE occurred_at < now() - interval '5 minutes' "
            "  AND (batch_id IS NULL OR leaf_index IS NULL)",
        )
        == 0
    )


async def test_the_seed_leaves_something_to_look_at(
    seeded_org: tuple[AsyncEngine, uuid.UUID],
) -> None:
    """An estate with no releases, findings or measurements demos nothing.

    Thresholds are deliberately loose. The point is that each screen has rows, not that
    the generator produces an exact count — pinning counts would make every tweak to the
    distribution a test failure.
    """
    engine, _org_id = seeded_org

    assert await _count(engine, "SELECT count(*) FROM releases") > 0
    assert await _count(engine, "SELECT count(*) FROM release_changes") > 0
    assert await _count(engine, "SELECT count(*) FROM accreditations") > 0
    assert await _count(engine, "SELECT count(*) FROM slo_definitions") > 0
    assert await _count(engine, "SELECT count(*) FROM slo_measurements") > 0
    assert await _count(engine, "SELECT count(*) FROM bom_components") > 0
    assert await _count(engine, "SELECT count(*) FROM graph_nodes") > 0
    assert await _count(engine, "SELECT count(*) FROM graph_edges") > 0


async def test_the_seed_refuses_to_run_twice(
    seeded_org: tuple[AsyncEngine, uuid.UUID],
) -> None:
    """`make up` must be safe to repeat.

    A second run exits 0 without adding a duplicate estate, so bringing the stack up
    again does not double every count on the dashboard.
    """
    engine, _org_id = seeded_org
    before = await _count(engine, "SELECT count(*) FROM agents")

    args = generate.parse_args(["--agents", "6", "--quiet"])
    assert await generate.run(args) == 0

    assert await _count(engine, "SELECT count(*) FROM agents") == before


def test_the_estate_is_deterministic() -> None:
    """Same seed, same plan. A demo you cannot rehearse is worth much less."""
    import random

    first = generate.plan_agents(random.Random(99), 8, 3, 14)
    second = generate.plan_agents(random.Random(99), 8, 3, 14)

    assert [p.urn for p in first] == [p.urn for p in second]
    assert [d for _, d, _ in first[0].descriptors] == [d for _, d, _ in second[0].descriptors]
