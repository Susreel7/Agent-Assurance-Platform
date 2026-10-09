from __future__ import annotations

from observe.clickhouse.migrations_runner import _split_statements


def test_migration_sql_splits_idempotent_statements() -> None:
    sql = """
    -- comment
    CREATE TABLE IF NOT EXISTS observe.events (id UUID);
    ALTER TABLE observe.spans ADD COLUMN IF NOT EXISTS execution_id String DEFAULT '';
    """
    parts = _split_statements(sql)
    assert len(parts) == 2
    assert "CREATE TABLE" in parts[0]
    assert "ALTER TABLE" in parts[1]
