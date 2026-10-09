"""The trust portal, against a real Postgres.

The portal is the only surface a customer's own staff reach, and two clients of the same
consultancy live in the same `org_id` — so row-level security and the `org_id` filter,
which carry tenant isolation everywhere else in the product, do nothing here. The
boundary is `engagement_id`, enforced query by query, and these tests exist to prove it
holds rather than to cover lines.

The fixtures go through the service layer for the reason in D-027: raw inserts can build
states no code path produces, and an isolation test against an impossible estate proves
nothing about the real one.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domains.accreditation import schemas as acc_schemas
from app.domains.accreditation import service as accreditation_svc
from app.domains.customers import schemas as customer_schemas
from app.domains.customers import service as customers_svc
from app.domains.engagements import schemas as engagement_schemas
from app.domains.engagements import service as engagements_svc
from app.domains.portal import service as portal_svc
from app.domains.registry import schemas as registry_schemas
from app.domains.registry import service as registry_svc

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@dataclass
class Client:
    """One customer with one engagement, one agent and one accredited pack."""

    customer_id: uuid.UUID
    customer_slug: str
    engagement_id: uuid.UUID
    engagement_slug: str
    agent_id: uuid.UUID
    version_id: uuid.UUID
    accreditation_id: uuid.UUID
    pack_id: uuid.UUID


def _descriptor(urn: str) -> dict[str, Any]:
    """The minimum `validate_aap_descriptor` accepts. Kept small on purpose: the portal
    does not read the descriptor, and a fuller one here would drift against the schema
    without anything noticing."""
    return {
        "aap_version": "0.1",
        "agent": {
            "urn": urn,
            "display_name": "Portal Agent",
            "version": "1.0.0",
            "lifecycle_state": "production",
        },
        "accountability": {
            "owning_team": "team:assurance",
            "accountable_person": "person:owner@consultancy.example",
        },
        "runtime": {
            "framework": "langgraph",
            "deployment": "kubernetes",
            "autonomy": "suggest",
        },
    }


async def make_client(
    session: AsyncSession,
    org_id: uuid.UUID,
    label: str,
    framework_id: uuid.UUID,
    *,
    engagement_slug: str = "managed-ai-delivery",
) -> Client:
    """One client, end to end.

    `engagement_slug` defaults to a shared value on purpose. Engagement slugs are unique
    per customer, so two clients naming their engagement the same thing is ordinary — and
    generating a unique one per client here was what let the portal ship a 500 against
    real seeded data while these tests passed.
    """
    customer_slug = f"{label}-{uuid.uuid4().hex[:6]}"
    customer = await customers_svc.create_customer(
        session,
        org_id,
        customer_schemas.CustomerCreate(
            slug=customer_slug,
            legal_name=f"{label.title()} Bank plc",
            sector=customer_schemas.Sector.FINANCIAL_SERVICES,
            home_jurisdiction="GB",
        ),
    )

    engagement = await engagements_svc.create_engagement(
        session,
        org_id,
        engagement_schemas.EngagementCreate(
            customer_id=customer.id,
            slug=engagement_slug,
            name=f"{label.title()} managed AI delivery",
            state=engagement_schemas.EngagementState.ACTIVE,
            permitted_regions=["eu-west-1"],
            prohibited_regions=["us-east-1"],
            cross_border_transfer=engagement_schemas.CrossBorderTransfer.PROHIBITED,
            permitted_data_classes=["internal"],
            starts_on=date(2026, 1, 1),
            ends_on=date(2028, 12, 31),
            delivery_lead="person:lead@consultancy.example",
            customer_approver=f"person:approver@{label}.example",
        ),
    )

    urn = f"urn:aap:{label}:agent-{uuid.uuid4().hex[:6]}:eu-west-1"
    agent = await registry_svc.create_agent(
        session,
        org_id,
        registry_schemas.AgentCreate(
            urn=urn,
            display_name=f"{label.title()} Agent",
            lifecycle_state=registry_schemas.LifecycleState.PRODUCTION,
        ),
    )
    version = await registry_svc.publish_version(
        session,
        org_id,
        agent.id,
        registry_schemas.VersionPublish(
            semver="1.0.0",
            descriptor=_descriptor(urn),
            published_by="person:eng@consultancy.example",
        ),
    )

    await engagements_svc.scope_agent(
        session,
        org_id,
        engagement.id,
        engagement_schemas.ScopeAgentRequest(
            agent_id=agent.id,
            uptake=engagement_schemas.VersionUptake.PINNED,
            accredited_version_id=version.id,
            deployed_version_id=version.id,
        ),
    )

    accreditation = await accreditation_svc.create_accreditation(
        session,
        org_id,
        acc_schemas.AccreditationCreate(
            agent_version_id=version.id,
            framework_id=framework_id,
            engagement_id=engagement.id,
        ),
    )
    await accreditation_svc.assemble_controls(session, org_id, accreditation.id)
    pack = await accreditation_svc.render_pack(
        session,
        org_id,
        accreditation.id,
        acc_schemas.PackRenderRequest(format="json"),
    )

    return Client(
        customer_id=customer.id,
        customer_slug=customer_slug,
        engagement_id=engagement.id,
        engagement_slug=engagement.slug,
        agent_id=agent.id,
        version_id=version.id,
        accreditation_id=accreditation.id,
        pack_id=pack.id,
    )


@pytest.fixture(scope="session")
def signing_key_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A throwaway signing key, generated once for the module.

    Rendering a pack signs it, and the default key path is the container's
    `/run/secrets/signing.pem`, which does not exist on a developer machine. Generating
    one is better than pointing at the repository's dev key: the test then has no
    dependency on `bootstrap` having been run.
    """
    key = ec.generate_private_key(ec.SECP256R1())
    path = tmp_path_factory.mktemp("signing") / "signing.pem"
    path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return path


@pytest.fixture(autouse=True)
def local_signing(signing_key_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the signer at that key. Autouse because the fixture chain that builds a
    client renders a pack, so every test here needs it."""
    monkeypatch.setenv("AAP_SIGNING_PROVIDER", "local")
    monkeypatch.setenv("AAP_SIGNING_KEY_PATH", str(signing_key_path))
    get_settings.cache_clear()


@pytest.fixture
async def framework_id(session: AsyncSession) -> uuid.UUID:
    """A shipped framework. Reference data, so `org_id IS NULL`."""
    row = await session.execute(
        text("SELECT id FROM frameworks WHERE org_id IS NULL ORDER BY slug LIMIT 1")
    )
    found = row.scalar_one_or_none()
    if found is None:  # pragma: no cover - 0002 seeds four of these
        pytest.skip("no reference frameworks seeded")
    return uuid.UUID(str(found))


@pytest.fixture
async def two_clients(
    session: AsyncSession, org_id: uuid.UUID, framework_id: uuid.UUID
) -> tuple[Client, Client]:
    """Two customers of the same consultancy. Same `org_id`, different engagements."""
    a = await make_client(session, org_id, "northwind", framework_id)
    b = await make_client(session, org_id, "contoso", framework_id)
    return a, b


# ----------------------------------------------------------------------
# Isolation — the reason this module exists
# ----------------------------------------------------------------------


async def test_two_clients_may_name_their_engagement_the_same_thing(
    session: AsyncSession, org_id: uuid.UUID, two_clients: tuple[Client, Client]
) -> None:
    """The regression. Uniqueness is per customer, so this is a legitimate estate — and
    the lookup used to match on the engagement slug alone, find both, and raise. Every
    portal link in the seeded demo returned a 500."""
    a, b = two_clients
    assert a.engagement_slug == b.engagement_slug

    view_a = await portal_svc.build_portal_view_by_slug(
        session, org_id, a.customer_slug, a.engagement_slug
    )
    view_b = await portal_svc.build_portal_view_by_slug(
        session, org_id, b.customer_slug, b.engagement_slug
    )

    assert view_a.engagement_id == a.engagement_id
    assert view_b.engagement_id == b.engagement_id


async def test_the_portal_view_shows_only_this_engagements_agents(
    session: AsyncSession, org_id: uuid.UUID, two_clients: tuple[Client, Client]
) -> None:
    a, b = two_clients

    view = await portal_svc.build_portal_view_by_slug(
        session, org_id, a.customer_slug, a.engagement_slug
    )

    shown = {summary.agent_id for summary in view.agents}
    assert shown == {a.agent_id}
    assert b.agent_id not in shown


async def test_another_customers_slug_does_not_reach_this_engagement(
    session: AsyncSession, org_id: uuid.UUID, two_clients: tuple[Client, Client]
) -> None:
    """Both halves of the link have to agree. Pairing one client's name with another's
    engagement must find nothing rather than fall back to either."""
    a, b = two_clients

    with pytest.raises(portal_svc.EngagementNotFoundError):
        await portal_svc.build_portal_view_by_slug(
            session, org_id, a.customer_slug, "no-such-engagement"
        )

    with pytest.raises(portal_svc.EngagementNotFoundError):
        await portal_svc.build_portal_view_by_slug(
            session, org_id, "no-such-customer", b.engagement_slug
        )


async def test_a_pack_from_another_engagement_cannot_be_downloaded(
    session: AsyncSession, org_id: uuid.UUID, two_clients: tuple[Client, Client]
) -> None:
    """The direct-object reference. Both clients share an `org_id`, so the only thing
    stopping one from fetching the other's accreditation pack by id is the join through
    `accreditations.engagement_id`."""
    a, b = two_clients

    assert await portal_svc.get_pack_download(
        session, org_id, a.customer_slug, a.engagement_slug, a.pack_id
    )

    with pytest.raises(portal_svc.PortalError):
        await portal_svc.get_pack_download(
            session, org_id, a.customer_slug, a.engagement_slug, b.pack_id
        )


async def test_another_tenants_engagement_slug_is_not_found(
    session: AsyncSession,
    org_id: uuid.UUID,
    other_org_id: uuid.UUID,
    framework_id: uuid.UUID,
) -> None:
    """Slugs are unique per organisation, not globally, so the same slug can exist in
    two tenants. Resolving one from the wrong tenant must find nothing rather than the
    other tenant's engagement."""
    theirs = await make_client(session, other_org_id, "rival", framework_id)

    with pytest.raises(portal_svc.EngagementNotFoundError):
        await portal_svc.build_portal_view_by_slug(
            session, org_id, theirs.customer_slug, theirs.engagement_slug
        )


async def test_an_unknown_slug_raises_not_found_rather_than_an_empty_view(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    """An empty portal reads as "you have no agents" to a customer, which is a support
    call. A missing engagement is a different fact and gets a different answer."""
    with pytest.raises(portal_svc.EngagementNotFoundError) as caught:
        await portal_svc.build_portal_view_by_slug(
            session, org_id, "no-such-customer", "no-such-engagement"
        )

    assert caught.value.engagement_slug == "no-such-engagement"


async def test_a_removed_agent_drops_out_of_the_view(
    session: AsyncSession, org_id: uuid.UUID, two_clients: tuple[Client, Client]
) -> None:
    """Scope is withdrawn by stamping `removed_at`, not by deleting the row, so the
    filter has to honour it — otherwise an agent taken out of scope keeps appearing on
    the customer's portal."""
    a, _ = two_clients

    await engagements_svc.unscope_agent(session, org_id, a.engagement_id, a.agent_id)

    view = await portal_svc.build_portal_view_by_slug(
        session, org_id, a.customer_slug, a.engagement_slug
    )

    assert view.agents == []


# ----------------------------------------------------------------------
# The view itself
# ----------------------------------------------------------------------


async def test_the_view_reports_accreditation_state_and_pack_references(
    session: AsyncSession, org_id: uuid.UUID, two_clients: tuple[Client, Client]
) -> None:
    a, _ = two_clients

    view = await portal_svc.build_portal_view_by_slug(
        session, org_id, a.customer_slug, a.engagement_slug
    )

    assert view.engagement_id == a.engagement_id
    assert view.engagement_slug == a.engagement_slug
    (summary,) = view.agents
    assert summary.accreditation_state == acc_schemas.AccreditationState.DRAFT
    assert len(summary.pack_download_refs) == 1


async def test_the_view_reports_the_evidence_chain_state(
    session: AsyncSession, org_id: uuid.UUID, two_clients: tuple[Client, Client]
) -> None:
    """An empty chain is a valid chain. The portal's whole claim is that the evidence
    behind an accreditation has not been altered, so `chain_valid` must not be false
    merely because nothing has been recorded yet."""
    a, _ = two_clients

    view = await portal_svc.build_portal_view_by_slug(
        session, org_id, a.customer_slug, a.engagement_slug
    )

    assert view.chain_valid is True
    assert view.chain_checked_at is not None


async def test_service_level_attainment_appears_for_this_engagement(
    session: AsyncSession, org_id: uuid.UUID, two_clients: tuple[Client, Client]
) -> None:
    a, _ = two_clients
    await engagements_svc.set_service_level(
        session,
        org_id,
        a.engagement_id,
        engagement_schemas.ServiceLevelUpsert(
            kind=engagement_schemas.ServiceLevelKind.AVAILABILITY,
            target=Decimal("99.90"),
            unit="percent",
            measurement_window=engagement_schemas.ServiceLevelWindow.MONTHLY,
            penalty_basis=engagement_schemas.PenaltyBasis.SERVICE_CREDIT,
            penalty_detail="5% of monthly fee per 0.1% below target.",
        ),
    )

    view = await portal_svc.build_portal_view_by_slug(
        session, org_id, a.customer_slug, a.engagement_slug
    )

    assert isinstance(view.slo_attainment, dict)
