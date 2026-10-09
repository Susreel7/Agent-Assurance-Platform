"""Provider connection behaviour: creation, rotation, grants and resolution.

The rule this domain exists to hold: **the platform records which agreement to use and
who may use it; it never holds the agreement's secret.** Every write here takes a
reference, every read returns a reference, and the material itself is fetched by the
gateway from the customer's own provider through ``app/providers``.

That is what makes the bridge honest when a customer already has a direct contract with
Anthropic or OpenAI. We are not reselling their tokens — we are deciding, per agent and
per environment, which of their own agreements a call is allowed to use, and recording
that it happened.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.connections import ConnectionSecretVersion
from app.domains.connections import repository as repo
from app.domains.connections.schemas import (
    ConnectionCreate,
    ConnectionGrantCreate,
    ConnectionGrantOut,
    ConnectionOut,
    ConnectionPage,
    ConnectionRotate,
    ConnectionSummary,
    ConnectionUpdate,
    ProviderKind,
    ResolvedConnection,
    SecretVersionOut,
)

FINGERPRINT_PREFIX_CHARS = 16


class ConnectionsError(Exception):
    """Base class so the router can map one exception family."""


class ConnectionNotFoundError(ConnectionsError):
    pass


class DuplicateConnectionError(ConnectionsError):
    pass


class GrantNotFoundError(ConnectionsError):
    pass


class DuplicateGrantError(ConnectionsError):
    pass


class EnvironmentNotEnabledError(ConnectionsError):
    """A grant reaches further than the connection itself allows."""


class NoGrantedConnectionError(ConnectionsError):
    """The subject has no live grant for a connection in this environment."""


def _version_out(row: ConnectionSecretVersion) -> SecretVersionOut:
    """Project a version row, truncating the fingerprint on the way out.

    Sixteen hex characters distinguishes two versions at a glance, which is all the
    console needs beside a rotation entry. The full digest stays in the database.
    """
    return SecretVersionOut(
        id=row.id,
        version_number=row.version_number,
        credential_ref=row.credential_ref,
        fingerprint_prefix=row.fingerprint.hex()[:FINGERPRINT_PREFIX_CHARS],
        created_at=row.created_at,
        activated_at=row.activated_at,
        retired_at=row.retired_at,
        created_by=row.created_by,
    )


async def create_connection(
    session: AsyncSession,
    org_id: UUID,
    payload: ConnectionCreate,
    *,
    created_by: str,
    created_by_member_id: UUID,
) -> ConnectionOut:
    """Register a connection and its first secret version in one transaction.

    A connection without an active version cannot be used, so creating them separately
    would leave a window in which the console shows a connection that fails every call.
    """
    try:
        connection = await repo.insert_connection(
            session,
            org_id,
            {
                "slug": payload.slug,
                "name": payload.name,
                "provider_kind": payload.provider_kind.value,
                "auth_kind": payload.auth_kind.value,
                "status": "pending",
                "owner_team_id": payload.owner_team_id,
                "personal_member_id": created_by_member_id if payload.personal else None,
                "endpoint_url": payload.endpoint_url,
                "region": payload.region,
                "residency_zone": payload.residency_zone,
                "environments": [env.value for env in payload.environments],
                "rotation_due_at": payload.rotation_due_at,
                "created_by": created_by,
            },
        )
    except IntegrityError as exc:
        raise DuplicateConnectionError(
            f"connection slug {payload.slug!r} is already used in this account"
        ) from exc

    # The first version's fingerprint is a digest of the *reference*, not of material we
    # do not have. It still serves its purpose: a later rotation to a different reference
    # produces a different fingerprint, which is what proves the change.
    version = await repo.insert_secret_version(
        session,
        org_id,
        {
            "connection_id": connection.id,
            "version_number": 1,
            "credential_ref": payload.credential_ref,
            "fingerprint": _digest(payload.credential_ref),
            "created_by": created_by,
        },
    )
    await repo.activate_version(
        session,
        org_id,
        connection.id,
        version.id,
        rotation_due_at=payload.rotation_due_at,
    )

    refreshed = await repo.get_connection(session, org_id, connection.id)
    assert refreshed is not None
    return ConnectionOut.model_validate(refreshed)


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode()).digest()


async def get_connection(
    session: AsyncSession,
    org_id: UUID,
    connection_id: UUID,
) -> ConnectionOut:
    connection = await repo.get_connection(session, org_id, connection_id)
    if connection is None:
        raise ConnectionNotFoundError(f"connection {connection_id} does not exist")
    return ConnectionOut.model_validate(connection)


async def update_connection(
    session: AsyncSession,
    org_id: UUID,
    connection_id: UUID,
    payload: ConnectionUpdate,
) -> ConnectionOut:
    values = payload.model_dump(exclude_unset=True)
    if not values:
        return await get_connection(session, org_id, connection_id)

    if values.get("environments") is not None:
        values["environments"] = [env.value for env in values["environments"]]
    if values.get("status") is not None:
        values["status"] = values["status"].value

    updated = await repo.update_connection(session, org_id, connection_id, values)
    if updated is None:
        raise ConnectionNotFoundError(f"connection {connection_id} does not exist")
    return ConnectionOut.model_validate(updated)


async def list_connections(
    session: AsyncSession,
    org_id: UUID,
    *,
    limit: int,
    offset: int,
    provider_kind: ProviderKind | None = None,
    include_disabled: bool = False,
) -> ConnectionPage:
    rows, total = await repo.list_connections(
        session,
        org_id,
        limit=limit,
        offset=offset,
        provider_kind=provider_kind.value if provider_kind else None,
        include_disabled=include_disabled,
    )
    now = datetime.now(UTC)
    return ConnectionPage(
        items=[
            ConnectionSummary(
                connection=ConnectionOut.model_validate(connection),
                owner_team_name=team_name,
                grant_count=grant_count,
                active_version=version,
                rotation_overdue=(
                    connection.rotation_due_at is not None and connection.rotation_due_at <= now
                ),
            )
            for connection, team_name, grant_count, version in rows
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


async def rotate(
    session: AsyncSession,
    org_id: UUID,
    connection_id: UUID,
    payload: ConnectionRotate,
    *,
    rotated_by: str,
) -> SecretVersionOut:
    """Add a new secret version and make it active.

    Takes the row lock first. Two operators rotating at once would otherwise both read
    the same highest version number, and one of them would get a constraint violation on
    a key change they believed had succeeded.
    """
    connection = await repo.lock_connection(session, org_id, connection_id)
    if connection is None:
        raise ConnectionNotFoundError(f"connection {connection_id} does not exist")

    number = await repo.next_version_number(session, org_id, connection_id)
    version = await repo.insert_secret_version(
        session,
        org_id,
        {
            "connection_id": connection_id,
            "version_number": number,
            "credential_ref": payload.credential_ref,
            "fingerprint": bytes.fromhex(payload.fingerprint_hex),
            "created_by": rotated_by,
        },
    )

    await repo.activate_version(
        session,
        org_id,
        connection_id,
        version.id,
        rotation_due_at=payload.rotation_due_at,
    )

    # Retiring the previous version is the default but not forced. A provider that needs
    # both keys live during a cutover is common enough that refusing it would push
    # operators into disabling the connection instead.
    if payload.retire_previous:
        await repo.retire_other_versions(session, org_id, connection_id, version.id)

    return _version_out(version)


async def list_versions(
    session: AsyncSession,
    org_id: UUID,
    connection_id: UUID,
) -> list[SecretVersionOut]:
    if await repo.get_connection(session, org_id, connection_id) is None:
        raise ConnectionNotFoundError(f"connection {connection_id} does not exist")
    return [_version_out(row) for row in await repo.list_versions(session, org_id, connection_id)]


async def grant_connection(
    session: AsyncSession,
    org_id: UUID,
    connection_id: UUID,
    payload: ConnectionGrantCreate,
    *,
    granted_by: str,
) -> ConnectionGrantOut:
    connection = await repo.get_connection(session, org_id, connection_id)
    if connection is None:
        raise ConnectionNotFoundError(f"connection {connection_id} does not exist")

    # A grant cannot reach further than the connection itself. Without this, granting an
    # agent 'production' on a dev-only connection would silently create a grant that can
    # never resolve, and the failure would surface as an unexplained denial at runtime.
    outside = sorted({env.value for env in payload.environments} - set(connection.environments))
    if outside:
        raise EnvironmentNotEnabledError(
            f"connection {connection.slug!r} is not enabled for: {', '.join(outside)}"
        )

    try:
        grant = await repo.insert_grant(
            session,
            org_id,
            {
                "connection_id": connection_id,
                "subject_kind": payload.subject_kind,
                "subject_id": payload.subject_id,
                "environments": [env.value for env in payload.environments],
                "granted_by": granted_by,
                "reason": payload.reason,
                "expires_at": payload.expires_at,
            },
        )
    except IntegrityError as exc:
        raise DuplicateGrantError(
            f"{payload.subject_kind} {payload.subject_id} already has this connection"
        ) from exc

    return ConnectionGrantOut.model_validate(grant)


async def list_grants(
    session: AsyncSession,
    org_id: UUID,
    connection_id: UUID,
) -> list[ConnectionGrantOut]:
    if await repo.get_connection(session, org_id, connection_id) is None:
        raise ConnectionNotFoundError(f"connection {connection_id} does not exist")
    rows = await repo.list_grants(session, org_id, connection_id)
    return [ConnectionGrantOut.model_validate(row) for row in rows]


async def revoke_grant(session: AsyncSession, org_id: UUID, grant_id: UUID) -> None:
    if not await repo.revoke_grant(session, org_id, grant_id):
        raise GrantNotFoundError(f"connection grant {grant_id} is not live")


async def resolve(
    session: AsyncSession,
    org_id: UUID,
    *,
    agent_id: UUID | None,
    project_id: UUID | None,
    team_id: UUID | None,
    environment: str,
    provider_kind: ProviderKind | None = None,
) -> list[ResolvedConnection]:
    """Which of the customer's own agreements this caller may use, right now.

    Called by the gateway before a provider call. Returns references in preference order;
    an empty result is a denial, never a fallback — falling back to an ungranted
    connection would bill the wrong agreement and break the residency guarantee at the
    same time.
    """
    subjects: list[tuple[str, UUID]] = []
    if agent_id is not None:
        subjects.append(("agent", agent_id))
    if project_id is not None:
        subjects.append(("project", project_id))
    if team_id is not None:
        subjects.append(("team", team_id))

    rows = await repo.resolve_for_subject(
        session,
        org_id,
        subject_kinds=subjects,
        environment=environment,
        provider_kind=provider_kind.value if provider_kind else None,
        now=datetime.now(UTC),
    )

    if not rows:
        raise NoGrantedConnectionError(f"no granted connection for this caller in {environment}")

    return [
        ResolvedConnection(
            connection_id=connection.id,
            provider_kind=ProviderKind(connection.provider_kind),
            auth_kind=connection.auth_kind,
            credential_ref=credential_ref,
            endpoint_url=connection.endpoint_url,
            region=connection.region,
            residency_zone=connection.residency_zone,
            version_number=version,
        )
        for connection, version, credential_ref in rows
    ]
