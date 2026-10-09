"""Optional integration tests against real Postgres/ClickHouse/Redis."""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.getenv("OBSERVE_INTEGRATION") != "1",
    reason="Set OBSERVE_INTEGRATION=1 with live services configured",
)
def test_postgres_migrations_apply() -> None:
    from observe.config import Settings
    from observe.migrations.runner import apply_migrations

    url = os.environ["OBSERVE_DATABASE_URL"]
    applied = apply_migrations(url)
    settings = Settings(database_url=url, run_migrations_on_startup=False)
    assert settings.database_url == url
    assert isinstance(applied, list)
