from __future__ import annotations

from importlib import resources


def test_clickhouse_migrations_shipped_in_wheel() -> None:
    root = resources.files("observe.clickhouse")
    migration_dir = root.joinpath("migrations")
    names = {p.name for p in migration_dir.iterdir() if p.name.endswith(".sql")}
    assert "001_execution_observability.sql" in names
    assert "002_sdk_operation.sql" in names
    assert "006_framework.sql" in names
