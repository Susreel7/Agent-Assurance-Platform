"""PostgreSQL connection helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import psycopg
from psycopg.rows import dict_row


@contextmanager
def connect(
    database_url: str,
    *,
    organization_id: UUID | None = None,
    project_id: UUID | None = None,
    worker: bool = False,
) -> Iterator[psycopg.Connection[dict[str, Any]]]:
    conn = psycopg.connect(database_url, row_factory=dict_row)
    try:
        with conn.cursor() as cur:
            if worker:
                cur.execute("SELECT set_config('app.observe_worker', 'on', true)")
            elif organization_id is not None and project_id is not None:
                cur.execute(
                    """
                    SELECT set_config('app.organization_id', %s, true),
                           set_config('app.project_id', %s, true)
                    """,
                    (str(organization_id), str(project_id)),
                )
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ping(database_url: str) -> None:
    with connect(database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
