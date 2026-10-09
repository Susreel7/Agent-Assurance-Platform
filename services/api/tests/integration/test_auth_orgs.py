"""Claims to organisation, against the real `identity_bindings` table.

This is the tenant boundary, and it is the one place where a bug is a cross-tenant data
leak rather than an error page. It runs against a server because the rules being tested
are largely in the schema: the partial unique index that lets a disabled binding coexist
with its replacement, and the scoping of a lookup that by design runs before any tenant
is known.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.auth import orgs
from app.config import get_settings

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]

ISSUER = "https://idp.customer.example"


@pytest_asyncio.fixture(autouse=True)
async def _admin_session_on_the_test_transaction(
    connection: AsyncConnection, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[None]:
    """Point `admin_session` at this test's transaction.

    `resolve_from_claims` opens its own admin session deliberately — it runs before a
    tenant is known, so there is nothing to scope to. That would not see rows this test
    has not committed, so the session it opens is redirected here instead of committing
    fixtures to a shared database.

    It sets `app.bypass_rls` because the real `admin_session` does, and
    `identity_bindings` is under a forced row-level security policy. Omitting it would
    pass anyway on a database where the application role is a superuser — which is how
    this stack currently connects — and then fail the first time it is not. The point of
    the flag is that the test does not depend on that.
    """
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def fake_admin_session() -> AsyncIterator[AsyncSession]:
        session = AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        try:
            await session.execute(text("SELECT set_config('app.bypass_rls', 'on', true)"))
            yield session
        finally:
            await session.close()

    monkeypatch.setattr(orgs, "admin_session", fake_admin_session)
    yield


@pytest.fixture(autouse=True)
def _configured(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("AAP_ENVIRONMENT", "test")
    monkeypatch.setenv("AAP_OIDC_ISSUER", ISSUER)
    monkeypatch.setenv("AAP_OIDC_AUDIENCE", "aap-api")
    monkeypatch.setenv("AAP_OIDC_ORG_CLAIMS", "org_id,tid,iss")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def bind(
    session: AsyncSession,
    org_id: uuid.UUID,
    *,
    claim_name: str,
    claim_value: str,
    issuer: str = ISSUER,
    disabled: bool = False,
) -> uuid.UUID:
    row = await session.execute(
        text("""
            INSERT INTO identity_bindings
                (org_id, issuer, claim_name, claim_value, created_by, disabled_at)
            VALUES
                (:org_id, :issuer, :claim_name, :claim_value, 'person:test@example',
                 CASE WHEN :disabled THEN now() ELSE NULL END)
            RETURNING id
        """),
        {
            "org_id": str(org_id),
            "issuer": issuer,
            "claim_name": claim_name,
            "claim_value": claim_value,
            "disabled": disabled,
        },
    )
    return uuid.UUID(str(row.scalar_one()))


def claims(**overrides: Any) -> dict[str, object]:
    base: dict[str, object] = {"iss": ISSUER, "sub": "user-1", "aud": "aap-api"}
    base.update(overrides)
    return base


async def test_a_bound_tenant_claim_resolves(session: AsyncSession, org_id: uuid.UUID) -> None:
    await bind(session, org_id, claim_name="tid", claim_value="entra-tenant-guid")

    resolved = await orgs.resolve_from_claims(claims(tid="entra-tenant-guid"))

    assert resolved == org_id


async def test_the_issuer_itself_can_be_the_binding(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """The per-customer-IdP case: a dedicated Keycloak realm identifies the tenant on its
    own, with no extra claim to configure on their side."""
    await bind(session, org_id, claim_name="iss", claim_value=ISSUER)

    resolved = await orgs.resolve_from_claims(claims())

    assert resolved == org_id


async def test_a_trailing_slash_on_the_issuer_still_matches(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """Providers are inconsistent about it and a customer copying the value out of a
    console will include whichever they see."""
    await bind(session, org_id, claim_name="iss", claim_value=ISSUER)

    resolved = await orgs.resolve_from_claims(claims(iss=f"{ISSUER}/"))

    assert resolved == org_id


async def test_an_unbound_claim_is_refused(session: AsyncSession, org_id: uuid.UUID) -> None:
    with pytest.raises(orgs.OrgResolutionError):
        await orgs.resolve_from_claims(claims(tid="never-registered"))


async def test_a_token_with_no_mappable_claim_is_refused(session: AsyncSession) -> None:
    with pytest.raises(orgs.OrgResolutionError, match="none of the claims"):
        await orgs.resolve_from_claims({"sub": "user-1", "aud": "aap-api"})


async def test_a_disabled_binding_does_not_resolve(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """Revocation has to take effect. The row stays as a record that the binding once
    existed, which is why the unique index is partial."""
    await bind(session, org_id, claim_name="tid", claim_value="revoked", disabled=True)

    with pytest.raises(orgs.OrgResolutionError):
        await orgs.resolve_from_claims(claims(tid="revoked"))


async def test_a_binding_can_be_recreated_after_being_disabled(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    await bind(session, org_id, claim_name="tid", claim_value="moved", disabled=True)
    await bind(session, org_id, claim_name="tid", claim_value="moved")

    assert await orgs.resolve_from_claims(claims(tid="moved")) == org_id


async def test_two_live_bindings_for_one_claim_are_impossible(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    """The ambiguity this prevents is the leak: one claim resolving to two organisations
    means whichever row the planner returned first decides whose data is served."""
    await bind(session, org_id, claim_name="tid", claim_value="contested")

    with pytest.raises(IntegrityError):
        await bind(session, other_org_id, claim_name="tid", claim_value="contested")


async def test_the_same_claim_value_from_another_issuer_does_not_match(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """Claim values are only meaningful alongside who asserted them. A binding matching
    on value alone would let any issuer claim any tenant."""
    await bind(session, org_id, claim_name="tid", claim_value="shared-value")

    with pytest.raises(orgs.OrgResolutionError):
        await orgs.resolve_from_claims(claims(iss="https://attacker.example", tid="shared-value"))


async def test_an_unbound_first_claim_does_not_fall_through_to_the_next(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    """`org_id` is checked before `tid`. A caller whose `org_id` is unbound must not then
    be resolved by their `tid` — that answers a question they did not ask, with another
    tenant's organisation."""
    await bind(session, other_org_id, claim_name="tid", claim_value="fallback-tenant")

    with pytest.raises(orgs.OrgResolutionError, match="org_id"):
        await orgs.resolve_from_claims(claims(org_id="unbound-org", tid="fallback-tenant"))


async def test_a_numeric_tenant_claim_is_matched_as_a_string(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """Legal JSON, and some providers send it. Skipping it would make the token look as
    though it carried no tenant at all."""
    await bind(session, org_id, claim_name="tid", claim_value="8891")

    assert await orgs.resolve_from_claims(claims(tid=8891)) == org_id


async def test_a_boolean_claim_is_not_treated_as_a_value(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """`True` would stringify to something a binding could be written for, so booleans
    are excluded rather than coerced."""
    await bind(session, org_id, claim_name="tid", claim_value="True")

    with pytest.raises(orgs.OrgResolutionError):
        await orgs.resolve_from_claims(claims(tid=True))
