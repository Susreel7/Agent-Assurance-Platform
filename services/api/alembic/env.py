"""Alembic environment.

Migrations run synchronously against a plain psycopg connection, even though the
application uses the async engine. Mixing async into migrations buys nothing and makes
failures harder to read.

The database URL comes from Settings so that a BYOC install pointing at managed Postgres
needs no change to alembic.ini.
"""

from __future__ import annotations

from logging.config import fileConfig

from sqlalchemy import create_engine, pool

from alembic import context
from app.config import get_settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No autogenerate: migrations are hand-written per AGENTS.md rule 7, so there is no
# metadata to compare against.
target_metadata = None


def _sync_url() -> str:
    """The configured URL, on a driver ``create_engine`` can use.

    SQLAlchemy's ``psycopg`` dialect *is* psycopg 3, and it drives both sync and async
    engines, so ``postgresql+psycopg://`` needs no adjustment here.

    This used to strip the driver to a bare ``postgresql://``, which does adjust it —
    to psycopg2, a library this project does not depend on. It went unnoticed because
    psycopg2 is commonly already present on a developer machine, so migrations ran
    locally and failed in the container with ``No module named 'psycopg2'``.

    An ``asyncpg`` URL genuinely cannot drive a sync engine, so that one is swapped.
    """
    url = get_settings().database_url
    if url.startswith("postgresql+asyncpg://"):
        return url.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_sync_url(), poolclass=pool.NullPool)

    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # DDL in one transaction, so a failed migration leaves no partial schema.
            transaction_per_migration=True,
        )
        with context.begin_transaction():
            context.run_migrations()

    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
