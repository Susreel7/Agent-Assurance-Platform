"""Hand-written SQL migration runner for the evaluate schema."""

from __future__ import annotations

import logging
from pathlib import Path

import psycopg

log = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent


def _migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def applied_versions(conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables
                WHERE table_schema = 'evaluate' AND table_name = 'schema_migrations'
            )
            """
        )
        row = cur.fetchone()
        if row is None or not row[0]:
            return set()
        cur.execute("SELECT version FROM evaluate.schema_migrations")
        return {r[0] for r in cur.fetchall()}


def apply_migrations(database_url: str) -> list[str]:
    applied: list[str] = []
    with psycopg.connect(database_url, autocommit=True) as conn:
        done = applied_versions(conn)
        for path in _migration_files():
            version = path.stem
            if version in done:
                continue
            sql = path.read_text(encoding="utf-8")
            log.info("Applying evaluate migration %s", version)
            with conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    """
                    INSERT INTO evaluate.schema_migrations (version)
                    VALUES (%s) ON CONFLICT DO NOTHING
                    """,
                    (version,),
                )
            applied.append(version)
    return applied
