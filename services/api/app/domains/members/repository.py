"""SQL for members, member identities and teams.

The list queries aggregate team names and role keys in the same statement as the member
row. A per-row follow-up query is the difference between one round trip and one thousand
on an account of any size, and this table is read on every console page load.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Select, and_, delete, func, or_, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.access import (
    AccessGrant,
    Member,
    MemberIdentity,
    Team,
    TeamMember,
)
from app.db.models.registry import Organization


async def insert_member(session: AsyncSession, org_id: UUID, row: dict[str, Any]) -> Member:
    member = Member(org_id=org_id, **row)
    session.add(member)
    await session.flush()
    return member


async def get_member(session: AsyncSession, org_id: UUID, member_id: UUID) -> Member | None:
    result = await session.execute(
        select(Member).where(Member.org_id == org_id, Member.id == member_id)
    )
    return result.scalar_one_or_none()


async def get_member_by_email(session: AsyncSession, org_id: UUID, email: str) -> Member | None:
    result = await session.execute(
        select(Member).where(Member.org_id == org_id, func.lower(Member.email) == email.lower())
    )
    return result.scalar_one_or_none()


async def get_account_name(session: AsyncSession, org_id: UUID) -> str | None:
    return await session.scalar(select(Organization.name).where(Organization.id == org_id))


async def update_member(
    session: AsyncSession,
    org_id: UUID,
    member_id: UUID,
    values: dict[str, Any],
) -> Member | None:
    """Update a member, keeping ``disabled_at`` consistent with ``status``.

    A check constraint requires the two to agree, so the timestamp is derived here from
    ``now()`` rather than accepted from the caller. Using the database clock means two
    API processes cannot record different times for the moment somebody lost access.
    """
    assignments = dict(values)
    if "status" in assignments:
        assignments["disabled_at"] = func.now() if assignments["status"] == "disabled" else None

    result = await session.execute(
        update(Member)
        .where(Member.org_id == org_id, Member.id == member_id)
        .values(**assignments, updated_at=func.now())
        .returning(Member)
    )
    return result.scalar_one_or_none()


def _member_filter(
    base: Select[Any],
    *,
    query: str | None,
    status: str | None,
    team_id: UUID | None,
) -> Select[Any]:
    if status is not None:
        base = base.where(Member.status == status)
    if query:
        pattern = f"%{query.lower()}%"
        base = base.where(
            or_(
                func.lower(Member.email).like(pattern),
                func.lower(Member.display_name).like(pattern),
            )
        )
    if team_id is not None:
        base = base.where(
            Member.id.in_(
                select(TeamMember.member_id).where(
                    TeamMember.org_id == Member.org_id,
                    TeamMember.team_id == team_id,
                )
            )
        )
    return base


async def list_members(
    session: AsyncSession,
    org_id: UUID,
    *,
    limit: int,
    offset: int,
    query: str | None = None,
    status: str | None = None,
    team_id: UUID | None = None,
) -> tuple[list[tuple[Member, list[str], list[str], int, bool]], int]:
    """Members with their team names, live role keys, identity count and MFA state.

    Each aggregate is a correlated scalar subquery rather than a join with GROUP BY. With
    four aggregates over three tables, grouping would multiply rows before collapsing
    them; this way each aggregate is an index lookup per member row.

    ``array_agg`` over no rows yields NULL rather than an empty array, and ``bool_or``
    likewise. The comprehension at the end of this function normalises both, which is
    cheaper than wrapping each aggregate in a coalesce that has to name an array type.
    """
    team_names = (
        select(func.array_agg(Team.name))
        .select_from(TeamMember)
        .join(Team, and_(Team.org_id == TeamMember.org_id, Team.id == TeamMember.team_id))
        .where(TeamMember.org_id == Member.org_id, TeamMember.member_id == Member.id)
        .scalar_subquery()
    )

    # Role keys reach a member two ways: granted directly, or granted to a team they are
    # in. Resolving both here keeps the "effective access" answer in one place.
    role_keys = (
        select(func.array_agg(AccessGrant.role_key.distinct()))
        .where(
            AccessGrant.org_id == Member.org_id,
            AccessGrant.revoked_at.is_(None),
            or_(
                AccessGrant.expires_at.is_(None),
                AccessGrant.expires_at > datetime.now(UTC),
            ),
            or_(
                and_(AccessGrant.subject_kind == "member", AccessGrant.subject_id == Member.id),
                and_(
                    AccessGrant.subject_kind == "team",
                    AccessGrant.subject_id.in_(
                        select(TeamMember.team_id).where(
                            TeamMember.org_id == Member.org_id,
                            TeamMember.member_id == Member.id,
                        )
                    ),
                ),
            ),
        )
        .scalar_subquery()
    )

    identity_count = (
        select(func.count())
        .select_from(MemberIdentity)
        .where(
            MemberIdentity.org_id == Member.org_id,
            MemberIdentity.member_id == Member.id,
            MemberIdentity.revoked_at.is_(None),
        )
        .scalar_subquery()
    )

    mfa_verified = (
        select(func.bool_or(MemberIdentity.mfa_verified))
        .where(
            MemberIdentity.org_id == Member.org_id,
            MemberIdentity.member_id == Member.id,
            MemberIdentity.revoked_at.is_(None),
        )
        .scalar_subquery()
    )

    base = select(Member).where(Member.org_id == org_id)
    base = _member_filter(base, query=query, status=status, team_id=team_id)

    total = await session.scalar(select(func.count()).select_from(base.subquery()))

    rows = await session.execute(
        _member_filter(
            select(Member, team_names, role_keys, identity_count, mfa_verified).where(
                Member.org_id == org_id
            ),
            query=query,
            status=status,
            team_id=team_id,
        )
        .order_by(Member.display_name, Member.id)
        .limit(limit)
        .offset(offset)
    )

    return [
        (member, list(teams or []), sorted(set(roles or [])), int(count or 0), bool(mfa))
        for member, teams, roles, count, mfa in rows.all()
    ], int(total or 0)


async def touch_last_seen(session: AsyncSession, org_id: UUID, member_id: UUID) -> None:
    await session.execute(
        update(Member)
        .where(Member.org_id == org_id, Member.id == member_id)
        .values(last_seen_at=func.now())
    )


async def insert_identity(
    session: AsyncSession,
    org_id: UUID,
    row: dict[str, Any],
) -> MemberIdentity:
    identity = MemberIdentity(org_id=org_id, **row)
    session.add(identity)
    await session.flush()
    return identity


async def find_identity(
    session: AsyncSession,
    issuer: str,
    subject: str,
) -> MemberIdentity | None:
    """Resolve an IdP subject to its binding across every tenant.

    Not org-scoped, and it cannot be: this is what *determines* the org for a caller.
    Callers must pass an admin session, and the uniqueness index guarantees one row.
    """
    result = await session.execute(
        select(MemberIdentity).where(
            MemberIdentity.issuer == issuer,
            MemberIdentity.subject == subject,
            MemberIdentity.revoked_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def has_live_identity(session: AsyncSession, org_id: UUID) -> bool:
    """Whether this account already has somebody who can sign in."""
    identity_id = await session.scalar(
        select(MemberIdentity.id)
        .where(
            MemberIdentity.org_id == org_id,
            MemberIdentity.revoked_at.is_(None),
        )
        .limit(1)
    )
    return identity_id is not None


async def list_identities(
    session: AsyncSession,
    org_id: UUID,
    member_id: UUID,
) -> list[MemberIdentity]:
    rows = await session.execute(
        select(MemberIdentity)
        .where(
            MemberIdentity.org_id == org_id,
            MemberIdentity.member_id == member_id,
        )
        .order_by(MemberIdentity.created_at.desc())
    )
    return list(rows.scalars())


async def record_login(session: AsyncSession, org_id: UUID, identity_id: UUID) -> None:
    await session.execute(
        update(MemberIdentity)
        .where(MemberIdentity.org_id == org_id, MemberIdentity.id == identity_id)
        .values(last_login_at=func.now())
    )


async def revoke_identity(session: AsyncSession, org_id: UUID, identity_id: UUID) -> bool:
    result = await session.execute(
        update(MemberIdentity)
        .where(
            MemberIdentity.org_id == org_id,
            MemberIdentity.id == identity_id,
            MemberIdentity.revoked_at.is_(None),
        )
        .values(revoked_at=func.now())
        .returning(MemberIdentity.id)
    )
    return result.scalar_one_or_none() is not None


async def insert_team(session: AsyncSession, org_id: UUID, row: dict[str, Any]) -> Team:
    team = Team(org_id=org_id, **row)
    session.add(team)
    await session.flush()
    return team


async def get_team(session: AsyncSession, org_id: UUID, team_id: UUID) -> Team | None:
    result = await session.execute(select(Team).where(Team.org_id == org_id, Team.id == team_id))
    return result.scalar_one_or_none()


async def update_team(
    session: AsyncSession,
    org_id: UUID,
    team_id: UUID,
    values: dict[str, Any],
) -> Team | None:
    result = await session.execute(
        update(Team)
        .where(Team.org_id == org_id, Team.id == team_id)
        .values(**values, updated_at=func.now())
        .returning(Team)
    )
    return result.scalar_one_or_none()


async def list_teams(
    session: AsyncSession,
    org_id: UUID,
    *,
    limit: int,
    offset: int,
) -> tuple[list[tuple[Team, int, list[str]]], int]:
    member_count = (
        select(func.count())
        .select_from(TeamMember)
        .where(TeamMember.org_id == Team.org_id, TeamMember.team_id == Team.id)
        .scalar_subquery()
    )

    lead_names = (
        select(func.array_agg(Member.display_name))
        .select_from(TeamMember)
        .join(Member, and_(Member.org_id == TeamMember.org_id, Member.id == TeamMember.member_id))
        .where(
            TeamMember.org_id == Team.org_id,
            TeamMember.team_id == Team.id,
            TeamMember.is_lead.is_(True),
        )
        .scalar_subquery()
    )

    base = select(Team).where(Team.org_id == org_id)
    total = await session.scalar(select(func.count()).select_from(base.subquery()))

    rows = await session.execute(
        select(Team, member_count, lead_names)
        .where(Team.org_id == org_id)
        .order_by(Team.name, Team.id)
        .limit(limit)
        .offset(offset)
    )

    return [(team, int(count or 0), list(leads or [])) for team, count, leads in rows.all()], int(
        total or 0
    )


async def teams_for_member(session: AsyncSession, org_id: UUID, member_id: UUID) -> list[Team]:
    rows = await session.execute(
        select(Team)
        .join(TeamMember, and_(TeamMember.org_id == Team.org_id, TeamMember.team_id == Team.id))
        .where(TeamMember.org_id == org_id, TeamMember.member_id == member_id)
        .order_by(Team.name)
    )
    return list(rows.scalars())


async def team_ids_for_member(session: AsyncSession, org_id: UUID, member_id: UUID) -> list[UUID]:
    """Just the ids. The authorization path needs these and nothing else."""
    rows = await session.execute(
        select(TeamMember.team_id).where(
            TeamMember.org_id == org_id,
            TeamMember.member_id == member_id,
        )
    )
    return list(rows.scalars())


async def add_team_members(
    session: AsyncSession,
    org_id: UUID,
    team_id: UUID,
    member_ids: list[UUID],
    *,
    is_lead: bool,
    added_by: str,
) -> int:
    """Bulk upsert. Adding 500 people to a team is one statement, not 500."""
    if not member_ids:
        return 0

    statement = (
        pg_insert(TeamMember)
        .values(
            [
                {
                    "org_id": org_id,
                    "team_id": team_id,
                    "member_id": member_id,
                    "is_lead": is_lead,
                    "added_by": added_by,
                }
                for member_id in member_ids
            ]
        )
        .on_conflict_do_update(
            index_elements=[TeamMember.org_id, TeamMember.team_id, TeamMember.member_id],
            set_={"is_lead": is_lead},
        )
        .returning(TeamMember.member_id)
    )
    # D-017: row counts come from RETURNING, never from `rowcount`.
    return len((await session.execute(statement)).all())


async def remove_team_members(
    session: AsyncSession,
    org_id: UUID,
    team_id: UUID,
    member_ids: list[UUID],
) -> int:
    if not member_ids:
        return 0
    removed = await session.execute(
        delete(TeamMember)
        .where(
            TeamMember.org_id == org_id,
            TeamMember.team_id == team_id,
            TeamMember.member_id.in_(member_ids),
        )
        .returning(TeamMember.member_id)
    )
    # D-017: row counts come from RETURNING, never from `rowcount`.
    return len(removed.all())


async def members_exist(session: AsyncSession, org_id: UUID, member_ids: list[UUID]) -> bool:
    if not member_ids:
        return True
    found = await session.scalar(
        select(func.count()).where(Member.org_id == org_id, Member.id.in_(member_ids))
    )
    return int(found or 0) == len(set(member_ids))
