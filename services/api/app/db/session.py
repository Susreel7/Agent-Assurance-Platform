"""Database engine and session management.

The tenant-scoping mechanism is the important part of this file. ``app.org_id`` is set
with ``SET LOCAL``, which is transaction-scoped. Using ``SET`` (session-scoped) would
leak the previous request's tenant through a pooled connection — a silent, intermittent
cross-tenant read that would be extremely hard to detect and catastrophic to discover.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        s = get_settings()
        _engine = create_async_engine(
            s.database_url,
            pool_size=s.db_pool_size,
            max_overflow=s.db_max_overflow,
            pool_pre_ping=True,
            echo=False,
            connect_args={
                # A runaway recursive CTE must not hold a connection indefinitely.
                "options": f"-c statement_timeout={s.db_statement_timeout_ms}",
                # Neither must an unreachable server. Without this, libpq waits on the
                # operating system's TCP timeout, which is minutes — and the request
                # waiting on it is `GET /v1/auth/config`, the one call the login screen
                # makes before anybody is signed in. A database outage rendered as a
                # spinner that never resolves is indistinguishable from a broken
                # console, which is the confusion this phase exists to remove. Failing
                # in seconds lets the endpoint say "the database is unavailable".
                "connect_timeout": s.db_connect_timeout_seconds,
            },
        )
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False, autoflush=False)
    return _sessionmaker


@asynccontextmanager
async def tenant_session(org_id: UUID) -> AsyncIterator[AsyncSession]:
    """A session bound to one organisation for the life of one transaction.

    Every request handler uses this. Row-level security then acts as a backstop against
    a query that forgets its ``org_id`` filter, rather than as the primary control.

    The commit is conditional on the transaction still being open, which is what lets
    ``TransactionalRoute`` commit earlier and leave this as a safety net. It used to be
    ``async with ... session.begin()``, whose exit always commits — and for an HTTP
    request that exit runs after the response has been sent, so the write landed after
    the client had already been told about it (Q-016). Committing twice is not an option
    either: the second raises, because the first closed the transaction.
    """
    async with get_sessionmaker()() as session:
        # Autobegin: this statement opens the transaction the request runs in, and
        # `set_config(..., true)` is SET LOCAL, so the scoping dies with it.
        await session.execute(
            text("SELECT set_config('app.org_id', :org_id, true)"),
            {"org_id": str(org_id)},
        )
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise
        if session.in_transaction():
            await session.commit()


@asynccontextmanager
async def admin_session() -> AsyncIterator[AsyncSession]:
    """Bypasses tenant scoping. For migrations, partition maintenance, the worker's
    cross-tenant scheduling sweep, and the handful of lookups that *establish* a tenant
    and therefore cannot be scoped to one: resolving a session cookie, a workload key or
    an auth provider. Never for anything a handler does once the tenant is known."""
    async with get_sessionmaker()() as session:
        await session.execute(text("SELECT set_config('app.bypass_rls', 'on', true)"))
        try:
            yield session
        except BaseException:
            await session.rollback()
            raise
        if session.in_transaction():
            await session.commit()


async def dispose_engine() -> None:
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None
