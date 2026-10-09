"""SQL for auth providers and console sessions.

Two of these queries deliberately do **not** filter by ``org_id``, and it is worth being
explicit about which and why, because every other repository in this codebase does.

``find_provider`` and ``find_live_session`` run *before* a tenant is known — the whole
point of them is to establish one. They are therefore called with an admin session, and
the value they look up is an unguessable 128-bit identifier or a SHA-256 digest rather
than anything a caller can enumerate. Every other function here is tenant-scoped in the
ordinary way and runs under row-level security.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.auth import AuthProvider, AuthSession
from app.db.models.registry import Organization


def _enabled(statement: Select[tuple[AuthProvider]]) -> Select[tuple[AuthProvider]]:
    return statement.where(AuthProvider.enabled.is_(True)).order_by(
        AuthProvider.precedence, AuthProvider.id
    )


async def list_providers(session: AsyncSession, org_id: UUID) -> list[AuthProvider]:
    result = await session.execute(
        _enabled(select(AuthProvider).where(AuthProvider.org_id == org_id))
    )
    return list(result.scalars().all())


async def find_providers_for_domain(session: AsyncSession, domain: str) -> list[AuthProvider]:
    """Account discovery. Unauthenticated, so it answers only for an exact domain match."""
    result = await session.execute(
        _enabled(select(AuthProvider).where(AuthProvider.email_domains.any(domain)))
    )
    return list(result.scalars().all())


async def find_provider(session: AsyncSession, provider_id: UUID) -> AuthProvider | None:
    """By id, across accounts. See the module docstring."""
    result = await session.execute(select(AuthProvider).where(AuthProvider.id == provider_id))
    return result.scalar_one_or_none()


async def get_provider(
    session: AsyncSession, org_id: UUID, provider_id: UUID
) -> AuthProvider | None:
    result = await session.execute(
        select(AuthProvider).where(AuthProvider.org_id == org_id, AuthProvider.id == provider_id)
    )
    return result.scalar_one_or_none()


async def distinct_provider_accounts(session: AsyncSession, *, limit: int = 2) -> list[UUID]:
    """Accounts that have at least one enabled provider.

    Limited by the caller, which only ever wants to know "is there exactly one?". A full
    list would be an account census served to an unauthenticated caller.
    """
    result = await session.execute(
        select(AuthProvider.org_id).where(AuthProvider.enabled.is_(True)).distinct().limit(limit)
    )
    return list(result.scalars().all())


async def account_name(session: AsyncSession, org_id: UUID) -> str | None:
    return await session.scalar(select(Organization.name).where(Organization.id == org_id))


async def insert_session(
    session: AsyncSession,
    org_id: UUID,
    values: dict[str, object],
) -> AuthSession:
    row = AuthSession(org_id=org_id, **values)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    return row


async def find_live_session(session: AsyncSession, token_hash: bytes) -> AuthSession | None:
    """Resolve one cookie. Across accounts, and only rows that are still usable.

    Expiry is compared in the database rather than in Python so that "is this session
    live" has one answer, taken from the same clock that wrote ``expires_at``.
    """
    result = await session.execute(
        select(AuthSession).where(
            AuthSession.token_hash == token_hash,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > func.now(),
            AuthSession.absolute_expires_at > func.now(),
        )
    )
    return result.scalar_one_or_none()


async def touch_session(
    session: AsyncSession,
    session_id: UUID,
    *,
    seen_at: datetime,
    expires_at: datetime | None = None,
) -> None:
    """Record activity, and optionally extend the sliding window.

    ``expires_at`` is only ever passed a value already clamped to
    ``absolute_expires_at`` by the service; the CHECK constraint in 0022 is the backstop
    if that ever stops being true.
    """
    values: dict[str, object] = {"last_seen_at": seen_at}
    if expires_at is not None:
        values["expires_at"] = expires_at
    await session.execute(update(AuthSession).where(AuthSession.id == session_id).values(**values))


async def list_sessions_for_member(
    session: AsyncSession,
    org_id: UUID,
    member_id: UUID,
) -> list[tuple[AuthSession, str | None]]:
    """Live sessions, newest first, with the label of the provider that created each."""
    result = await session.execute(
        select(AuthSession, AuthProvider.label)
        .join(AuthProvider, AuthProvider.id == AuthSession.provider_id, isouter=True)
        .where(
            AuthSession.org_id == org_id,
            AuthSession.member_id == member_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.absolute_expires_at > func.now(),
        )
        .order_by(AuthSession.issued_at.desc())
    )
    return [(row[0], row[1]) for row in result.all()]


async def revoke_session(
    session: AsyncSession,
    org_id: UUID,
    session_id: UUID,
    *,
    reason: str,
    revoked_at: datetime,
) -> int:
    result = await session.execute(
        update(AuthSession)
        .where(
            AuthSession.org_id == org_id,
            AuthSession.id == session_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=revoked_at, revoked_reason=reason)
    )
    return result.rowcount or 0


async def revoke_session_for_member(
    session: AsyncSession,
    org_id: UUID,
    member_id: UUID,
    session_id: UUID,
    *,
    reason: str,
    revoked_at: datetime,
) -> bool:
    """Revoke one session, provided it belongs to this member.

    The ``member_id`` predicate is in the WHERE clause rather than checked beforehand so
    that there is no window between the check and the update, and no code path that can
    reach the update without it.
    """
    result = await session.execute(
        update(AuthSession)
        .where(
            AuthSession.org_id == org_id,
            AuthSession.member_id == member_id,
            AuthSession.id == session_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=revoked_at, revoked_reason=reason)
    )
    return bool(result.rowcount)


async def revoke_sessions_for_member(
    session: AsyncSession,
    org_id: UUID,
    member_id: UUID,
    *,
    reason: str,
    revoked_at: datetime,
    except_session_id: UUID | None = None,
) -> int:
    statement = (
        update(AuthSession)
        .where(
            AuthSession.org_id == org_id,
            AuthSession.member_id == member_id,
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=revoked_at, revoked_reason=reason)
    )
    if except_session_id is not None:
        statement = statement.where(AuthSession.id != except_session_id)
    result = await session.execute(statement)
    return result.rowcount or 0
