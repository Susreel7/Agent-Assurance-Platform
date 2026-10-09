"""Migration 0022 against a real Postgres, and the database half of the session invariant.

Three things here cannot be seen without a server:

* **RLS on both auth tables.** A policy that was never enabled looks identical to one
  that was, until a query from the wrong tenant returns rows.
* **Model and migration agree.** The ORM in `app/db/models/auth.py` was written next to
  the migration rather than generated from it, so a column present in one and absent
  from the other is exactly the kind of drift that surfaces as an `UndefinedColumn` on
  the first login rather than in review.
* **`inv_no_session_without_member`.** Proving a row does not exist needs a table.

The HTTP half of that invariant — a refused sign-in sets no cookie — is a unit test in
`tests/unit/test_console_contract.py`, because it needs no database at all.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.auth import AuthProvider, AuthSession
from app.domains.members import service as members_service

pytestmark = pytest.mark.integration

AUTH_TABLES = ("auth_providers", "auth_sessions")


async def _seed_provider(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    onboarding_mode: str = "invite",
) -> uuid.UUID:
    provider_id = uuid.uuid4()
    await session.execute(
        text("""
            INSERT INTO auth_providers
                (id, org_id, kind, label, email_domains, onboarding_mode)
            VALUES
                (:id, :org_id, 'development', 'Development sign-in',
                 ARRAY['localhost']::text[], :mode)
        """),
        {"id": provider_id, "org_id": org_id, "mode": onboarding_mode},
    )
    await session.flush()
    return provider_id


# --------------------------------------------------------------------------------------
# The migration is what it claims to be
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("table", AUTH_TABLES)
async def test_row_level_security_is_enabled_and_forced(session: AsyncSession, table: str) -> None:
    """Enabled is not enough: the owner role bypasses RLS unless it is also forced.

    The application connects as the owner in most installs, so an unforced policy is a
    policy that never runs in production and always passes in a test written as the
    superuser.
    """
    row = (
        await session.execute(
            text("""
                SELECT relrowsecurity, relforcerowsecurity
                FROM pg_class WHERE relname = :table
            """),
            {"table": table},
        )
    ).one()

    assert row.relrowsecurity, f"{table} does not have row level security enabled"
    assert row.relforcerowsecurity, f"{table} does not force row level security"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "table"),
    [(AuthProvider, "auth_providers"), (AuthSession, "auth_sessions")],
)
async def test_the_model_and_the_migration_agree(
    session: AsyncSession, model: type, table: str
) -> None:
    """Zero drift, in both directions.

    A column in the migration and not the model is invisible to the application; a
    column in the model and not the migration fails on first use. Both have happened in
    this repository, which is why this asserts set equality rather than a subset.
    """
    in_database = {
        name
        for (name,) in await session.execute(
            text("""
                SELECT column_name FROM information_schema.columns
                WHERE table_name = :table AND table_schema = current_schema()
            """),
            {"table": table},
        )
    }
    in_model = {column.name for column in model.__table__.columns}

    assert in_model == in_database, (
        f"{table} drift — only in model: {sorted(in_model - in_database)}; "
        f"only in database: {sorted(in_database - in_model)}"
    )


@pytest.mark.asyncio
async def test_a_session_cannot_outlive_its_absolute_ceiling(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """The ceiling is the only upper bound on how long a deprovisioned person keeps
    working, so it is a CHECK rather than a convention in the service layer."""
    member_id = await _seed_member(session, org_id)
    provider_id = await _seed_provider(session, org_id)

    with pytest.raises(Exception, match="auth_sessions_expiry_ordering"):
        await session.execute(
            text("""
                INSERT INTO auth_sessions
                    (org_id, member_id, provider_id, token_hash, identity_issuer,
                     identity_subject, expires_at, absolute_expires_at)
                VALUES
                    (:org_id, :member_id, :provider_id, '\\x00'::bytea, 'urn:aap:dev',
                     'dev:someone@localhost', now() + interval '2 days', now() + interval '1 day')
            """),
            {"org_id": org_id, "member_id": member_id, "provider_id": provider_id},
        )
        await session.flush()


async def _seed_member(session: AsyncSession, org_id: uuid.UUID) -> uuid.UUID:
    member_id = uuid.uuid4()
    await session.execute(
        text("""
            INSERT INTO members (id, org_id, email, display_name, status)
            VALUES (:id, :org_id, 'someone@localhost', 'Someone', 'active')
        """),
        {"id": member_id, "org_id": org_id},
    )
    await session.flush()
    return member_id


# --------------------------------------------------------------------------------------
# inv_no_session_without_member
# --------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inv_no_session_without_member(session: AsyncSession, org_id: uuid.UUID) -> None:
    """A sign-in nobody invited leaves the table exactly as it found it.

    Asserted at the resolver rather than through HTTP because `service.start` opens its
    own connections, which would escape this test's transaction and leave rows behind.
    What makes the assertion cover the endpoint is the ordering in `start`: the session
    insert is unreachable unless `_resolve_member` has already returned, so a resolver
    that raises is a session that was never written.
    """
    await _seed_provider(session, org_id, onboarding_mode="invite")

    with pytest.raises(members_service.NotProvisionedError):
        await members_service.resolve_directory_login(
            session,
            org_id,
            issuer="urn:aap:dev",
            subject="dev:stranger@localhost",
            email="stranger@localhost",
            email_verified=True,
            mfa_verified=False,
            directory_groups=[],
            onboarding_mode="invite",
            allow_first_owner_bootstrap=False,
        )

    remaining = await session.scalar(
        text("SELECT count(*) FROM auth_sessions WHERE org_id = :org_id"), {"org_id": org_id}
    )
    assert remaining == 0

    # And no half-made member either. An identity row without a member is what the
    # resolver's idempotency depends on never existing.
    members = await session.scalar(
        text("SELECT count(*) FROM members WHERE org_id = :org_id"), {"org_id": org_id}
    )
    assert members == 0
