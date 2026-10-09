"""Idempotent ClickHouse schema initialization."""

from __future__ import annotations

import logging
from pathlib import Path

from observe.clickhouse.client import ClickHouseClient
from observe.config import Settings

log = logging.getLogger(__name__)

INIT_PATH = Path(__file__).resolve().parent / "init.sql"


def apply_schema(settings: Settings, client: ClickHouseClient | None = None) -> None:
    ch = client or ClickHouseClient(settings)
    sql = INIT_PATH.read_text(encoding="utf-8")
    sql = sql.replace("INTERVAL 90 DAY", f"INTERVAL {settings.clickhouse_spans_ttl_days} DAY")
    for statement in _split_statements(sql):
        if statement.strip():
            ch.execute(statement)
    log.info("clickhouse schema applied (ttl=%s days)", settings.clickhouse_spans_ttl_days)


def _split_statements(sql: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    for line in sql.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        buf.append(line)
        if stripped.endswith(";"):
            parts.append("\n".join(buf))
            buf = []
    if buf:
        parts.append("\n".join(buf))
    return parts
