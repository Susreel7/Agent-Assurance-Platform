"""Versioned ClickHouse migrations with ledger (idempotent statements)."""

from __future__ import annotations

import logging
import re
from pathlib import Path

from observe.clickhouse.client import ClickHouseClient
from observe.clickhouse.schema import apply_schema
from observe.config import Settings

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def _migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def _split_statements(sql: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            stmt = "\n".join(buf).strip()
            if stmt:
                parts.append(stmt)
            buf = []
    if buf:
        stmt = "\n".join(buf).strip()
        if stmt:
            parts.append(stmt)
    return parts


def _ensure_ledger(ch: ClickHouseClient, database: str) -> None:
    ch.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {database}.schema_migrations
        (
            version String,
            applied_at DateTime64(3, 'UTC') DEFAULT now64(3)
        )
        ENGINE = ReplacingMergeTree(applied_at)
        ORDER BY version
        """
    )


def _applied_versions(ch: ClickHouseClient, database: str) -> set[str]:
    _ensure_ledger(ch, database)
    rows = ch.query_json(f"SELECT version FROM {database}.schema_migrations FINAL")
    return {str(r["version"]) for r in rows}


def apply_clickhouse_migrations(
    settings: Settings, client: ClickHouseClient | None = None
) -> list[str]:
    """Apply init.sql then numbered migrations; returns versions applied this run."""
    ch = client or ClickHouseClient(settings)
    database = settings.clickhouse_database
    applied_now: list[str] = []

    apply_schema(settings, ch)

    done = _applied_versions(ch, database)
    ttl = settings.clickhouse_spans_ttl_days
    for path in _migration_files():
        version = path.stem
        if version in done:
            continue
        sql = path.read_text(encoding="utf-8")
        sql = sql.replace("observe.", f"{database}.")
        sql = re.sub(r"INTERVAL 90 DAY", f"INTERVAL {ttl} DAY", sql)
        log.info("Applying ClickHouse migration %s", version)
        for statement in _split_statements(sql):
            if statement.strip():
                ch.execute(statement)
        ch.execute(f"INSERT INTO {database}.schema_migrations (version) VALUES ('{version}')")
        applied_now.append(version)
    return applied_now
