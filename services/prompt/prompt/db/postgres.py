"""PostgreSQL connection helpers."""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

import psycopg

PgConn = psycopg.Connection[dict[str, Any]]


def ping(database_url: str) -> None:
    with psycopg.connect(database_url, connect_timeout=3) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")


@contextmanager
def connect(database_url: str) -> Generator[PgConn, None, None]:
    conn = psycopg.connect(database_url, row_factory=psycopg.rows.dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
