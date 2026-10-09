"""Integration fixtures: a real Postgres, migrated, one per test session.

These tests exist because the unit suite cannot see the half of this system that lives
in the database. Partitioning, the append-only triggers, RLS, recursive CTEs, upsert
conflict targets and every CHECK constraint are invisible to a mocked session, and each
one of them broke the first time it met a real server.

The database comes from `AAP_TEST_DATABASE_URL` when set — which is how it runs against
the Compose stack — and otherwise from a throwaway container via testcontainers. Tests
skip rather than fail when neither is available, so the unit suite stays runnable on a
machine without Docker.

Isolation is per test, by transaction rollback rather than by truncation: it is faster,
and it means a test cannot leave a row behind that changes the next one's result.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Iterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, create_async_engine

pytestmark = pytest.mark.integration

_ENV_URL = "AAP_TEST_DATABASE_URL"


def _migrate(sync_url: str) -> None:
    """Bring the database to head with the real migrations.

    Deliberately the same code path as production: an integration suite built on
    `metadata.create_all` proves the models agree with themselves and nothing about the
    migrations anyone will actually run.

    The ambient AAP_* environment is cleared for the duration. This fixture is
    session-scoped, so the function-scoped isolation fixture in the parent conftest has
    not run yet, and a shell configured to talk to a local BYOC stack would otherwise
    fail the migration on a deployment-mode invariant that has nothing to do with the
    schema.

    The URL goes into `DATABASE_URL`, not `AAP_DATABASE_URL`. That field carries an
    explicit `validation_alias`, and pydantic-settings does not apply `env_prefix` to a
    field that has one, so the prefixed name is read by nothing. `Settings.database_url`
    also has a default, so getting the name wrong does not fail — it quietly migrates
    whatever is listening on localhost:5432 instead. That is how this helper spent a
    session appearing to work: the tests were pointed at an already-migrated database, so
    a no-op upgrade was indistinguishable from a successful one. Hence the assertion at
    the end: a migration that did not reach head on the URL it was handed is a failure,
    not a pass.
    """
    from alembic.config import Config
    from sqlalchemy import create_engine, text

    from alembic import command
    from app.config import get_settings

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    config = Config(os.path.join(root, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(root, "alembic"))

    managed = ("DATABASE_URL", *(k for k in os.environ if k.startswith("AAP_")))
    saved = {k: os.environ[k] for k in managed if k in os.environ}
    for key in saved:
        del os.environ[key]
    os.environ["DATABASE_URL"] = sync_url
    os.environ["AAP_ENVIRONMENT"] = "test"
    get_settings.cache_clear()
    try:
        command.upgrade(config, "head")
    finally:
        for key in [k for k in os.environ if k.startswith("AAP_") or k == "DATABASE_URL"]:
            del os.environ[key]
        os.environ.update(saved)
        get_settings.cache_clear()

    from alembic.script import ScriptDirectory

    expected = set(ScriptDirectory.from_config(config).get_heads())
    engine = create_engine(sync_url, poolclass=None)
    try:
        with engine.connect() as conn:
            applied = set(conn.execute(text("SELECT version_num FROM alembic_version")).scalars())
    finally:
        engine.dispose()
    if applied != expected:
        raise AssertionError(
            f"migrations did not reach head on the target database: "
            f"applied {sorted(applied) or 'nothing'}, expected {sorted(expected)}"
        )


@pytest.fixture(scope="session")
def database_url() -> Iterator[str]:
    """An async SQLAlchemy URL for a migrated, disposable database."""
    provided = os.environ.get(_ENV_URL)
    if provided:
        _migrate(provided)
        yield provided
        return

    # testcontainers 4.15 moved the Postgres module under `community` and made the old
    # path warn. This suite runs with warnings as errors, so importing the old path
    # first would fail rather than deprecate. Try the new location, then the old.
    try:
        try:
            from testcontainers.community.postgres import PostgresContainer
        except ImportError:
            from testcontainers.postgres import PostgresContainer
    except ImportError:  # pragma: no cover - depends on the install
        pytest.skip(f"set {_ENV_URL} or install testcontainers to run integration tests")

    try:
        with PostgresContainer("postgres:16-alpine", driver="psycopg") as container:
            url = container.get_connection_url()
            _migrate(url)
            yield url
    except Exception as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"no Postgres available for integration tests: {exc}")


@pytest_asyncio.fixture(scope="session")
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    eng = create_async_engine(database_url, pool_pre_ping=True)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def connection(engine: AsyncEngine) -> AsyncIterator[AsyncConnection]:
    """An outer transaction that is always rolled back.

    Every test runs inside it, so the database is identical before and after, and tests
    can be reordered or run repeatedly without a cleanup step to forget.
    """
    async with engine.connect() as conn:
        transaction = await conn.begin()
        try:
            yield conn
        finally:
            await transaction.rollback()


@pytest_asyncio.fixture
async def session(connection: AsyncConnection) -> AsyncIterator[AsyncSession]:
    """A session joined to the test's transaction via a savepoint.

    `create_savepoint` lets code under test call commit() — which the service layer
    does — without ending the outer transaction that provides isolation. The commit
    releases a savepoint instead, and the outer rollback still undoes everything.
    """
    async with AsyncSession(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    ) as s:
        yield s


@pytest_asyncio.fixture
async def org_id(session: AsyncSession) -> uuid.UUID:
    """A tenant, created inside the test's transaction.

    Tenant-scoped, because a test that shares a tenant with another test cannot detect a
    missing org_id filter — the very bug RLS and these fixtures exist to catch.
    """
    from sqlalchemy import text

    new_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO organizations (id, slug, name) VALUES (:id, :slug, :name)"),
        {"id": new_id, "slug": f"it-{new_id.hex[:10]}", "name": "Integration Tenant"},
    )
    await session.flush()
    return new_id


@pytest_asyncio.fixture
async def other_org_id(session: AsyncSession) -> uuid.UUID:
    """A second tenant, to prove reads do not cross the boundary."""
    from sqlalchemy import text

    new_id = uuid.uuid4()
    await session.execute(
        text("INSERT INTO organizations (id, slug, name) VALUES (:id, :slug, :name)"),
        {"id": new_id, "slug": f"it-{new_id.hex[:10]}", "name": "Other Tenant"},
    )
    await session.flush()
    return new_id
