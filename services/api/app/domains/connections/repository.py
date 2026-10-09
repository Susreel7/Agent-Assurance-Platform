"""SQL for provider connections, their secret versions and their grants."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.access import Team
from app.db.models.connections import (
    ConnectionGrant,
    ConnectionSecretVersion,
    ProviderConnection,
)


async def insert_connection(
    session: AsyncSession,
    org_id: UUID,
    row: dict[str, Any],
) -> ProviderConnection:
    connection = ProviderConnection(org_id=org_id, **row)
    session.add(connection)
    await session.flush()
    return connection


async def get_connection(
    session: AsyncSession,
    org_id: UUID,
    connection_id: UUID,
) -> ProviderConnection | None:
    result = await session.execute(
        select(ProviderConnection).where(
            ProviderConnection.org_id == org_id,
            ProviderConnection.id == connection_id,
        )
    )
    return result.scalar_one_or_none()


async def update_connection(
    session: AsyncSession,
    org_id: UUID,
    connection_id: UUID,
    values: dict[str, Any],
) -> ProviderConnection | None:
    assignments = dict(values)
    if "status" in assignments:
        assignments["disabled_at"] = func.now() if assignments["status"] == "disabled" else None

    result = await session.execute(
        update(ProviderConnection)
        .where(ProviderConnection.org_id == org_id, ProviderConnection.id == connection_id)
        .values(**assignments, updated_at=func.now())
        .returning(ProviderConnection)
    )
    return result.scalar_one_or_none()


async def list_connections(
    session: AsyncSession,
    org_id: UUID,
    *,
    limit: int,
    offset: int,
    provider_kind: str | None = None,
    include_disabled: bool = False,
) -> tuple[list[tuple[ProviderConnection, str | None, int, int | None]], int]:
    grant_count = (
        select(func.count())
        .select_from(ConnectionGrant)
        .where(
            ConnectionGrant.org_id == ProviderConnection.org_id,
            ConnectionGrant.connection_id == ProviderConnection.id,
            ConnectionGrant.revoked_at.is_(None),
        )
        .scalar_subquery()
    )

    active_version = (
        select(ConnectionSecretVersion.version_number)
        .where(
            ConnectionSecretVersion.org_id == ProviderConnection.org_id,
            ConnectionSecretVersion.id == ProviderConnection.active_secret_version_id,
        )
        .scalar_subquery()
    )

    filters = [ProviderConnection.org_id == org_id]
    if provider_kind is not None:
        filters.append(ProviderConnection.provider_kind == provider_kind)
    if not include_disabled:
        filters.append(ProviderConnection.disabled_at.is_(None))

    total = await session.scalar(
        select(func.count()).select_from(select(ProviderConnection).where(*filters).subquery())
    )

    rows = await session.execute(
        select(ProviderConnection, Team.name, grant_count, active_version)
        .outerjoin(
            Team,
            and_(
                Team.org_id == ProviderConnection.org_id,
                Team.id == ProviderConnection.owner_team_id,
            ),
        )
        .where(*filters)
        .order_by(ProviderConnection.name, ProviderConnection.id)
        .limit(limit)
        .offset(offset)
    )

    return [
        (connection, team_name, int(count or 0), version)
        for connection, team_name, count, version in rows.all()
    ], int(total or 0)


async def next_version_number(
    session: AsyncSession,
    org_id: UUID,
    connection_id: UUID,
) -> int:
    """One more than the highest version, or 1.

    Read under the row lock taken by `lock_connection`, so two concurrent rotations
    cannot both compute the same number and collide on the uniqueness index.
    """
    current = await session.scalar(
        select(func.max(ConnectionSecretVersion.version_number)).where(
            ConnectionSecretVersion.org_id == org_id,
            ConnectionSecretVersion.connection_id == connection_id,
        )
    )
    return int(current or 0) + 1


async def lock_connection(
    session: AsyncSession,
    org_id: UUID,
    connection_id: UUID,
) -> ProviderConnection | None:
    """Row-lock a connection for the duration of a rotation.

    Rotation reads the highest version number and then inserts the next one. Without the
        lock, two operators rotating at the same moment both read N and both try to write
        N+1; one gets a constraint violation and the other silently wins. Neither is a good
        outcome for a key change somebody is depending on.
    """
    result = await session.execute(
        select(ProviderConnection)
        .where(ProviderConnection.org_id == org_id, ProviderConnection.id == connection_id)
        .with_for_update()
    )
    return result.scalar_one_or_none()


async def insert_secret_version(
    session: AsyncSession,
    org_id: UUID,
    row: dict[str, Any],
) -> ConnectionSecretVersion:
    version = ConnectionSecretVersion(org_id=org_id, **row)
    session.add(version)
    await session.flush()
    return version


async def activate_version(
    session: AsyncSession,
    org_id: UUID,
    connection_id: UUID,
    version_id: UUID,
    *,
    rotation_due_at: datetime | None,
) -> None:
    await session.execute(
        update(ProviderConnection)
        .where(ProviderConnection.org_id == org_id, ProviderConnection.id == connection_id)
        .values(
            active_secret_version_id=version_id,
            rotation_due_at=rotation_due_at,
            status="healthy",
            updated_at=func.now(),
        )
    )
    await session.execute(
        update(ConnectionSecretVersion)
        .where(
            ConnectionSecretVersion.org_id == org_id,
            ConnectionSecretVersion.id == version_id,
        )
        .values(activated_at=func.now())
    )


async def retire_other_versions(
    session: AsyncSession,
    org_id: UUID,
    connection_id: UUID,
    keep_version_id: UUID,
) -> int:
    retired = await session.execute(
        update(ConnectionSecretVersion)
        .where(
            ConnectionSecretVersion.org_id == org_id,
            ConnectionSecretVersion.connection_id == connection_id,
            ConnectionSecretVersion.id != keep_version_id,
            ConnectionSecretVersion.retired_at.is_(None),
        )
        .values(retired_at=func.now())
        .returning(ConnectionSecretVersion.id)
    )
    # D-017: row counts come from RETURNING, never from `rowcount`.
    return len(retired.all())


async def list_versions(
    session: AsyncSession,
    org_id: UUID,
    connection_id: UUID,
) -> list[ConnectionSecretVersion]:
    rows = await session.execute(
        select(ConnectionSecretVersion)
        .where(
            ConnectionSecretVersion.org_id == org_id,
            ConnectionSecretVersion.connection_id == connection_id,
        )
        .order_by(ConnectionSecretVersion.version_number.desc())
    )
    return list(rows.scalars())


async def insert_grant(
    session: AsyncSession,
    org_id: UUID,
    row: dict[str, Any],
) -> ConnectionGrant:
    grant = ConnectionGrant(org_id=org_id, **row)
    session.add(grant)
    await session.flush()
    return grant


async def list_grants(
    session: AsyncSession,
    org_id: UUID,
    connection_id: UUID,
) -> list[ConnectionGrant]:
    rows = await session.execute(
        select(ConnectionGrant)
        .where(
            ConnectionGrant.org_id == org_id,
            ConnectionGrant.connection_id == connection_id,
            ConnectionGrant.revoked_at.is_(None),
        )
        .order_by(ConnectionGrant.created_at.desc())
    )
    return list(rows.scalars())


async def revoke_grant(session: AsyncSession, org_id: UUID, grant_id: UUID) -> bool:
    result = await session.execute(
        update(ConnectionGrant)
        .where(
            ConnectionGrant.org_id == org_id,
            ConnectionGrant.id == grant_id,
            ConnectionGrant.revoked_at.is_(None),
        )
        .values(revoked_at=func.now())
        .returning(ConnectionGrant.id)
    )
    return result.scalar_one_or_none() is not None


async def resolve_for_subject(
    session: AsyncSession,
    org_id: UUID,
    *,
    subject_kinds: list[tuple[str, UUID]],
    environment: str,
    provider_kind: str | None,
    now: datetime,
) -> list[tuple[ProviderConnection, int, str]]:
    """Connections a subject may use in an environment, with the active version number.

    ``subject_kinds`` is the set of identities the caller acts as — the agent itself, its
        project, and the owning team — because a grant may be attached to any of them.
        Resolving all three in one statement is what keeps this on the gateway's hot path.

        An empty list means no grant, which the caller turns into a denial rather than
        falling back to an ungranted connection.
    """
    if not subject_kinds:
        return []

    subject_predicate = or_(
        *[
            and_(ConnectionGrant.subject_kind == kind, ConnectionGrant.subject_id == subject_id)
            for kind, subject_id in subject_kinds
        ]
    )

    filters = [
        ProviderConnection.org_id == org_id,
        ProviderConnection.disabled_at.is_(None),
        ProviderConnection.active_secret_version_id.is_not(None),
        # `@> ARRAY[env]`, the codebase's form for array membership. A connection estate is
        # tens of rows per tenant, so this is a filter after the org predicate rather than
        # something worth a GIN index and its write cost.
        ProviderConnection.environments.contains([environment]),
    ]
    if provider_kind is not None:
        filters.append(ProviderConnection.provider_kind == provider_kind)

    rows = await session.execute(
        select(
            ProviderConnection,
            ConnectionSecretVersion.version_number,
            ConnectionSecretVersion.credential_ref,
        )
        .join(
            ConnectionGrant,
            and_(
                ConnectionGrant.org_id == ProviderConnection.org_id,
                ConnectionGrant.connection_id == ProviderConnection.id,
            ),
        )
        .join(
            ConnectionSecretVersion,
            and_(
                ConnectionSecretVersion.org_id == ProviderConnection.org_id,
                ConnectionSecretVersion.id == ProviderConnection.active_secret_version_id,
            ),
        )
        .where(
            *filters,
            ConnectionGrant.revoked_at.is_(None),
            or_(ConnectionGrant.expires_at.is_(None), ConnectionGrant.expires_at > now),
            ConnectionGrant.environments.contains([environment]),
            subject_predicate,
        )
        .order_by(ProviderConnection.name)
    )

    return [
        (connection, int(version), credential_ref)
        for connection, version, credential_ref in rows.all()
    ]


async def mark_used(session: AsyncSession, org_id: UUID, connection_id: UUID) -> None:
    await session.execute(
        update(ProviderConnection)
        .where(ProviderConnection.org_id == org_id, ProviderConnection.id == connection_id)
        .values(last_used_at=func.now())
    )


async def due_for_rotation(
    session: AsyncSession,
    *,
    now: datetime,
    limit: int,
) -> list[ProviderConnection]:
    """Connections past their rotation date. Cross-tenant; worker use only."""
    rows = await session.execute(
        select(ProviderConnection)
        .where(
            ProviderConnection.disabled_at.is_(None),
            ProviderConnection.rotation_due_at.is_not(None),
            ProviderConnection.rotation_due_at <= now,
        )
        .order_by(ProviderConnection.rotation_due_at)
        .limit(limit)
    )
    return list(rows.scalars())
