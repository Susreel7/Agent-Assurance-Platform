"""ORM declarations must match the migrated PostgreSQL schema.

Hand-written migrations are the source of truth; models mirror them. This test compares
every ORM-mapped table and column against ``information_schema`` on a real database.

What it covers:
- Each ``Base.metadata`` table exists in ``public``.
- Each mapped column exists on that table.
- Nullability matches.
- Types are compatible, including PostgreSQL enums by ``udt_name``, ``bytea`` and
  ``inet``.
- Primary keys match, which is how a partitioned table's composite key is checked.
- Every migrated table has a model, apart from a short documented list.
- A NOT NULL column with no default that the model does not declare.

What it does not cover:
- Nullable or defaulted columns present in the database and absent from the model. That
  direction is real drift but it does not break a write, and narrowing the check to the
  columns that do keeps it from becoming a wall of noise nobody reads.
- Partition child tables, indexes, constraints, triggers and RLS policies. Those are
  asserted in ``tests/sql/invariants.sql`` against the same database.
- Column order and server default values.

The reverse-direction checks were added with `0023`/`0024`, after ``auth.py`` from `0022`
turned out never to have been exported from ``app/db/models/__init__.py``. It was
therefore absent from ``Base.metadata``, so the forward check above had nothing to say
about it. A model that is not registered is not checked, and the failure mode is silence.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Integer,
    LargeBinary,
    Text,
    inspect,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, ENUM, INET, JSONB, UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.sqltypes import String

import app.db.models  # noqa: F401 — register every mapped table on Base.metadata
from app.db.base import Base

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

_TYPE_EXPECTATIONS: dict[type[Any], set[str]] = {
    UUID: {"uuid"},
    Text: {"text"},
    String: {"character varying"},
    Integer: {"integer"},
    BigInteger: {"bigint"},
    Boolean: {"boolean"},
    DateTime: {"timestamp with time zone", "timestamp without time zone"},
    JSONB: {"jsonb"},
    # Every digest column in the product. Unmapped until `0024` made the ledger's six
    # digest columns the largest group of `bytea` in the schema, at which point "the
    # drift test silently skips this type" stopped being acceptable.
    LargeBinary: {"bytea"},
    INET: {"inet"},
}

# Tables that exist in the migrations and deliberately have no ORM model.
#
# `identity_bindings` is read by `app/auth/orgs.py` through raw SQL before a tenant is
# known, which is the one place a model would be actively misleading: there is no session
# to attach it to yet. `alembic_version` belongs to Alembic.
_TABLES_WITHOUT_A_MODEL = frozenset({"identity_bindings", "alembic_version"})


def _expected_types(col_type: Any) -> tuple[set[str], str | None]:
    if isinstance(col_type, ARRAY):
        inner = col_type.item_type
        if isinstance(inner, Text) or inner.__class__ is Text:
            return {"ARRAY"}, "_text"
        if isinstance(inner, String):
            return {"ARRAY"}, None
    if isinstance(col_type, ENUM):
        return {"USER-DEFINED"}, col_type.name
    # BigInteger subclasses Integer; check the wider type first.
    if isinstance(col_type, BigInteger):
        return _TYPE_EXPECTATIONS[BigInteger], None
    for sa_type, names in _TYPE_EXPECTATIONS.items():
        if sa_type is BigInteger:
            continue
        if isinstance(col_type, sa_type):
            return names, None
    return set(), None


async def _fetch_columns(session: AsyncSession) -> dict[str, dict[str, dict[str, str | None]]]:
    rows = await session.execute(
        text("""
            SELECT table_name, column_name, data_type, udt_name, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = 'public'
            ORDER BY table_name, ordinal_position
        """)
    )
    out: dict[str, dict[str, dict[str, str | None]]] = {}
    for table, column, data_type, udt_name, is_nullable, default in rows:
        out.setdefault(table, {})[column] = {
            "data_type": data_type,
            "udt_name": udt_name,
            "is_nullable": is_nullable,
            "column_default": default,
        }
    return out


async def _fetch_base_tables(session: AsyncSession) -> set[str]:
    """Ordinary and partitioned tables, excluding partition children.

    A partition has no model of its own and never will: ``agent_actions_202609`` is
    storage, not an entity. ``relispartition`` is the only reliable way to tell, since
    the naming convention is a convention.
    """
    rows = await session.execute(
        text("""
            SELECT c.relname
              FROM pg_class c
              JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = 'public'
               AND c.relkind IN ('r', 'p')
               AND NOT c.relispartition
        """)
    )
    return set(rows.scalars())


async def _fetch_primary_keys(session: AsyncSession) -> dict[str, list[str]]:
    rows = await session.execute(
        text("""
            SELECT c.relname, a.attname
              FROM pg_index i
              JOIN pg_class c ON c.oid = i.indrelid
              JOIN pg_namespace n ON n.oid = c.relnamespace
              JOIN pg_attribute a
                ON a.attrelid = c.oid AND a.attnum = ANY (i.indkey)
             WHERE i.indisprimary
               AND n.nspname = 'public'
               AND NOT c.relispartition
             ORDER BY c.relname, a.attnum
        """)
    )
    out: dict[str, list[str]] = {}
    for table, column in rows:
        out.setdefault(table, []).append(column)
    return out


async def test_orm_tables_and_columns_match_database(session: AsyncSession) -> None:
    db_columns = await _fetch_columns(session)
    missing_tables: list[str] = []
    problems: list[str] = []

    for table_name, table in sorted(Base.metadata.tables.items()):
        if table_name not in db_columns:
            missing_tables.append(table_name)
            continue
        db_cols = db_columns[table_name]
        mapper = inspect(table)
        for col in mapper.columns:
            name = col.name
            if name not in db_cols:
                problems.append(f"{table_name}.{name}: missing in database")
                continue
            db_col = db_cols[name]
            expected_nullable = "YES" if col.nullable else "NO"
            if db_col["is_nullable"] != expected_nullable:
                problems.append(
                    f"{table_name}.{name}: nullable ORM={col.nullable} db={db_col['is_nullable']}"
                )
            data_types, udt = _expected_types(col.type)
            actual_type = db_col["data_type"] or ""
            if isinstance(col.type, String) and actual_type == "text":
                pass  # migrations often use text where the ORM declares String
            elif data_types and actual_type not in data_types:
                problems.append(
                    f"{table_name}.{name}: type ORM={col.type!r} db_data_type={actual_type!r}"
                )
            if udt is not None and db_col["udt_name"] != udt:
                problems.append(
                    f"{table_name}.{name}: udt ORM expects {udt!r} db={db_col['udt_name']!r}"
                )
            if isinstance(col.type, ENUM) and db_col["udt_name"] != col.type.name:
                problems.append(
                    f"{table_name}.{name}: enum ORM={col.type.name!r} db={db_col['udt_name']!r}"
                )

    if missing_tables or problems:
        lines: list[str] = []
        if missing_tables:
            lines.append("tables in ORM but not in database: " + ", ".join(missing_tables))
        lines.extend(problems)
        pytest.fail("\n".join(lines))


async def test_every_migrated_table_has_a_model(session: AsyncSession) -> None:
    """The check that ``auth`` from `0022` needed and did not have.

    Writing a migration and forgetting the model is silent: nothing imports what does not
    exist, and the forward drift check above only walks tables the ORM already knows
    about. This walks the other way, so the omission is a failure the same day.
    """
    in_database = await _fetch_base_tables(session)
    in_orm = set(Base.metadata.tables)
    unmodelled = sorted(in_database - in_orm - _TABLES_WITHOUT_A_MODEL)
    assert not unmodelled, (
        "tables in the database with no ORM model: "
        + ", ".join(unmodelled)
        + " — add the model under app/db/models/ and export it from its __init__"
    )


async def test_primary_keys_match(session: AsyncSession) -> None:
    """Including composite keys, which is how the partitioned ledger is checked.

    ``agent_actions`` is partitioned by ``occurred_at``, and Postgres requires the
    partition key to be part of the primary key. A model declaring ``id`` alone would
    load and query fine, then return the wrong row the first time two partitions held
    the same generated id.
    """
    db_keys = await _fetch_primary_keys(session)
    problems: list[str] = []
    for table_name, table in sorted(Base.metadata.tables.items()):
        if table_name not in db_keys:
            continue
        in_orm = sorted(col.name for col in table.primary_key.columns)
        in_db = sorted(db_keys[table_name])
        if in_orm != in_db:
            problems.append(f"{table_name}: primary key ORM={in_orm} db={in_db}")
    assert not problems, "\n".join(problems)


async def test_no_mandatory_column_is_missing_from_a_model(session: AsyncSession) -> None:
    """A NOT NULL column with no default that the model does not declare.

    Narrowed to this case deliberately. A nullable or defaulted column absent from the
    model is drift, but it is drift the database papers over; this is the kind that makes
    an ORM insert fail at runtime with a message pointing at the wrong layer.
    """
    db_columns = await _fetch_columns(session)
    problems: list[str] = []
    for table_name, table in sorted(Base.metadata.tables.items()):
        if table_name not in db_columns:
            continue
        declared = {col.name for col in table.columns}
        for name, db_col in db_columns[table_name].items():
            if name in declared:
                continue
            if db_col["is_nullable"] == "NO" and db_col["column_default"] is None:
                problems.append(f"{table_name}.{name}: NOT NULL, no default, not in the model")
    assert not problems, "\n".join(problems)
