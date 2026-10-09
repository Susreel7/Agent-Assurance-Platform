"""SQL for roles, grants and access requests.

``resolve_grants`` is the hottest query in the application: every authorized request runs
it. It is written as one statement over the partial ``access_grants_live_subject_idx``,
joined to ``roles`` for the permission array, and it never touches a revoked or expired
row because those are excluded from the index itself.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.access import (
    AccessGrant,
    AccessRequest,
    Member,
    MemberIdentity,
    Role,
    Team,
    TeamMember,
)


async def list_roles(session: AsyncSession, org_id: UUID) -> list[Role]:
    """Built-in roles plus this account's own, built-in first."""
    rows = await session.execute(
        select(Role)
        .where(or_(Role.org_id.is_(None), Role.org_id == org_id))
        .order_by(Role.builtin.desc(), Role.key)
    )
    return list(rows.scalars())


async def get_role(session: AsyncSession, org_id: UUID, role_key: str) -> Role | None:
    """A tenant role shadows a built-in of the same key.

    ``ORDER BY org_id NULLS LAST`` with a limit is what implements that precedence: if an
    account defines its own ``approver``, theirs is the one that resolves.
    """
    rows = await session.execute(
        select(Role)
        .where(
            Role.key == role_key,
            or_(Role.org_id.is_(None), Role.org_id == org_id),
        )
        .order_by(Role.org_id.is_(None))
        .limit(1)
    )
    return rows.scalar_one_or_none()


async def insert_role(session: AsyncSession, org_id: UUID, row: dict[str, Any]) -> Role:
    role = Role(org_id=org_id, builtin=False, **row)
    session.add(role)
    await session.flush()
    return role


async def resolve_grants(
    session: AsyncSession,
    org_id: UUID,
    member_id: UUID,
    *,
    now: datetime,
) -> list[tuple[str, str, UUID | None, list[str]]]:
    """Live ``(role_key, scope_kind, scope_id, permissions)`` for one member.

    Covers both routes a role reaches a person: granted to them directly, or granted to a
    team they belong to. One statement, because splitting it into "my grants" and "my
    teams' grants" doubles the round trips on the path every request takes.
    """
    member_teams = select(TeamMember.team_id).where(
        TeamMember.org_id == org_id,
        TeamMember.member_id == member_id,
    )

    rows = await session.execute(
        select(
            AccessGrant.role_key,
            AccessGrant.scope_kind,
            AccessGrant.scope_id,
            Role.permissions,
        )
        .join(
            Role,
            and_(
                Role.key == AccessGrant.role_key,
                or_(Role.org_id.is_(None), Role.org_id == AccessGrant.org_id),
            ),
        )
        .where(
            AccessGrant.org_id == org_id,
            AccessGrant.revoked_at.is_(None),
            or_(AccessGrant.expires_at.is_(None), AccessGrant.expires_at > now),
            or_(
                and_(AccessGrant.subject_kind == "member", AccessGrant.subject_id == member_id),
                and_(
                    AccessGrant.subject_kind == "team",
                    AccessGrant.subject_id.in_(member_teams),
                ),
            ),
        )
        # A tenant role of the same key wins over the built-in, matching `get_role`.
        .order_by(Role.org_id.is_(None))
    )

    return [
        (role_key, scope_kind, scope_id, list(permissions or []))
        for role_key, scope_kind, scope_id, permissions in rows.all()
    ]


async def account_is_administered(
    session: AsyncSession,
    org_id: UUID,
    *,
    now: datetime,
) -> bool:
    """True when somebody who can actually sign in holds ``access:write`` here.

    Two deliberate narrowings. ``access:write`` rather than a named role, because an
    account may define its own administrator role and would otherwise look unowned
    forever. And the holder must have a live directory binding, because a grant to a
    member no IdP subject resolves to administers nothing — that is a row, not a person,
    and treating it as an owner is what leaves a real employee locked out of an account
    that looks owned.
    """
    member_grant = and_(
        AccessGrant.subject_kind == "member",
        AccessGrant.subject_id == MemberIdentity.member_id,
    )
    team_grant = and_(
        AccessGrant.subject_kind == "team",
        AccessGrant.subject_id.in_(
            select(TeamMember.team_id).where(
                TeamMember.org_id == org_id,
                TeamMember.member_id == MemberIdentity.member_id,
            )
        ),
    )

    row = await session.execute(
        select(AccessGrant.id)
        .join(
            Role,
            and_(
                Role.key == AccessGrant.role_key,
                or_(Role.org_id.is_(None), Role.org_id == AccessGrant.org_id),
            ),
        )
        .join(
            MemberIdentity,
            and_(
                MemberIdentity.org_id == AccessGrant.org_id,
                MemberIdentity.revoked_at.is_(None),
                or_(member_grant, team_grant),
            ),
        )
        .where(
            AccessGrant.org_id == org_id,
            AccessGrant.revoked_at.is_(None),
            or_(AccessGrant.expires_at.is_(None), AccessGrant.expires_at > now),
            Role.permissions.any("access:write"),
        )
        .limit(1)
    )
    return row.scalar_one_or_none() is not None


async def insert_grant(session: AsyncSession, org_id: UUID, row: dict[str, Any]) -> AccessGrant:
    grant = AccessGrant(org_id=org_id, **row)
    session.add(grant)
    await session.flush()
    return grant


async def get_grant(session: AsyncSession, org_id: UUID, grant_id: UUID) -> AccessGrant | None:
    result = await session.execute(
        select(AccessGrant).where(AccessGrant.org_id == org_id, AccessGrant.id == grant_id)
    )
    return result.scalar_one_or_none()


async def revoke_grant(
    session: AsyncSession,
    org_id: UUID,
    grant_id: UUID,
    *,
    revoked_by: str,
) -> AccessGrant | None:
    """Revoke, and only if it is still live.

    The ``revoked_at IS NULL`` predicate is what makes this idempotent-safe: a second
        revoke returns nothing rather than overwriting who revoked it first.
    """
    result = await session.execute(
        update(AccessGrant)
        .where(
            AccessGrant.org_id == org_id,
            AccessGrant.id == grant_id,
            AccessGrant.revoked_at.is_(None),
        )
        .values(revoked_at=func.now(), revoked_by=revoked_by)
        .returning(AccessGrant)
    )
    return result.scalar_one_or_none()


async def list_grants(
    session: AsyncSession,
    org_id: UUID,
    *,
    limit: int,
    offset: int,
    subject_kind: str | None = None,
    subject_id: UUID | None = None,
    include_revoked: bool = False,
) -> tuple[list[tuple[AccessGrant, str, str, list[str], str]], int]:
    """Grants with subject label, role name, permissions and scope label.

    The subject label comes from a CASE over two LEFT JOINs rather than a second query
    per row: a grant's subject is a member or a team, and which one is a column value.
    """
    # NULL when the subject row is gone; the comprehension below falls back to the id.
    subject_label = func.coalesce(Member.display_name, Team.name)

    base = select(AccessGrant).where(AccessGrant.org_id == org_id)
    if not include_revoked:
        base = base.where(AccessGrant.revoked_at.is_(None))
    if subject_kind is not None:
        base = base.where(AccessGrant.subject_kind == subject_kind)
    if subject_id is not None:
        base = base.where(AccessGrant.subject_id == subject_id)

    total = await session.scalar(select(func.count()).select_from(base.subquery()))

    query = (
        select(AccessGrant, subject_label, Role.name, Role.permissions, AccessGrant.scope_kind)
        .outerjoin(
            Member,
            and_(
                AccessGrant.subject_kind == "member",
                Member.org_id == AccessGrant.org_id,
                Member.id == AccessGrant.subject_id,
            ),
        )
        .outerjoin(
            Team,
            and_(
                AccessGrant.subject_kind == "team",
                Team.org_id == AccessGrant.org_id,
                Team.id == AccessGrant.subject_id,
            ),
        )
        .outerjoin(
            Role,
            and_(
                Role.key == AccessGrant.role_key,
                or_(Role.org_id.is_(None), Role.org_id == AccessGrant.org_id),
            ),
        )
        .where(AccessGrant.org_id == org_id)
    )
    if not include_revoked:
        query = query.where(AccessGrant.revoked_at.is_(None))
    if subject_kind is not None:
        query = query.where(AccessGrant.subject_kind == subject_kind)
    if subject_id is not None:
        query = query.where(AccessGrant.subject_id == subject_id)

    rows = await session.execute(
        query.order_by(AccessGrant.created_at.desc(), AccessGrant.id.desc())
        .limit(limit)
        .offset(offset)
    )

    return [
        (grant, label or str(grant.subject_id), name or grant.role_key, list(perms or []), scope)
        for grant, label, name, perms, scope in rows.all()
    ], int(total or 0)


async def expire_lapsed_grants(session: AsyncSession, *, now: datetime, limit: int) -> int:
    """Mark lapsed grants revoked, in bounded batches.

    Cross-tenant on purpose: this runs in the worker under an admin session, and an
    expiry sweep that had to iterate tenants would not keep up at scale. The
    ``access_grants_expiring_idx`` partial index means the scan touches only rows that
    have actually lapsed.
    """
    lapsed = (
        select(AccessGrant.id)
        .where(
            AccessGrant.revoked_at.is_(None),
            AccessGrant.expires_at.is_not(None),
            AccessGrant.expires_at <= now,
        )
        .order_by(AccessGrant.expires_at)
        .limit(limit)
        .scalar_subquery()
    )

    expired = await session.execute(
        update(AccessGrant)
        .where(AccessGrant.id.in_(lapsed))
        .values(revoked_at=func.now(), revoked_by="system:expiry")
        .returning(AccessGrant.id)
    )
    # D-017: row counts come from RETURNING, never from `rowcount`.
    return len(expired.all())


async def insert_request(
    session: AsyncSession,
    org_id: UUID,
    row: dict[str, Any],
) -> AccessRequest:
    request = AccessRequest(org_id=org_id, **row)
    session.add(request)
    await session.flush()
    return request


async def get_request(
    session: AsyncSession,
    org_id: UUID,
    request_id: UUID,
) -> AccessRequest | None:
    result = await session.execute(
        select(AccessRequest).where(
            AccessRequest.org_id == org_id,
            AccessRequest.id == request_id,
        )
    )
    return result.scalar_one_or_none()


async def decide_request(
    session: AsyncSession,
    org_id: UUID,
    request_id: UUID,
    values: dict[str, Any],
) -> AccessRequest | None:
    """Decide a request, and only while it is still pending.

    The ``state = 'pending'`` predicate is the concurrency control. Two approvers clicking
        at once means the second sees nothing changed rather than overwriting the first
        decision, and the caller turns that into a 409.
    """
    result = await session.execute(
        update(AccessRequest)
        .where(
            AccessRequest.org_id == org_id,
            AccessRequest.id == request_id,
            AccessRequest.state == "pending",
        )
        .values(**values, decided_at=func.now())
        .returning(AccessRequest)
    )
    return result.scalar_one_or_none()


async def list_requests(
    session: AsyncSession,
    org_id: UUID,
    *,
    limit: int,
    offset: int,
    state: str | None = None,
    requester_member_id: UUID | None = None,
) -> tuple[list[AccessRequest], int]:
    base = select(AccessRequest).where(AccessRequest.org_id == org_id)
    if state is not None:
        base = base.where(AccessRequest.state == state)
    if requester_member_id is not None:
        base = base.where(AccessRequest.requester_member_id == requester_member_id)

    total = await session.scalar(select(func.count()).select_from(base.subquery()))
    rows = await session.execute(
        base.order_by(AccessRequest.created_at.desc(), AccessRequest.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(rows.scalars()), int(total or 0)


async def expire_stale_requests(session: AsyncSession, *, now: datetime, limit: int) -> int:
    """Close pending requests nobody decided within their own requested window."""
    stale = (
        select(AccessRequest.id)
        .where(
            AccessRequest.state == "pending",
            AccessRequest.created_at
            + func.make_interval(0, 0, 0, 0, 0, AccessRequest.duration_minutes)
            <= now,
        )
        .order_by(AccessRequest.created_at)
        .limit(limit)
        .scalar_subquery()
    )
    closed = await session.execute(
        update(AccessRequest)
        .where(AccessRequest.id.in_(stale))
        .values(state="expired", decided_by="system:expiry", decision_note="not decided in time")
        .returning(AccessRequest.id)
    )
    # D-017: row counts come from RETURNING, never from `rowcount`.
    return len(closed.all())
