"""Workload credentials against real Postgres."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.access import Member
from app.db.models.workload_identity import WorkloadCredential, WorkloadCredentialGeneration
from app.domains.registry.schemas import LifecycleState
from app.domains.workload_identity import service
from app.domains.workload_identity.schemas import (
    ProjectCreate,
    WorkloadCredentialCreate,
    WorkloadModule,
)
from tests.integration.test_operations import make_agent

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


async def _project(session: AsyncSession, org_id: uuid.UUID) -> uuid.UUID:
    out = await service.create_project(
        session, org_id, ProjectCreate(slug="default", name="Default")
    )
    return out.id


async def _credential(
    session: AsyncSession,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    *,
    agent_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, str]:
    created = await service.create_credential(
        session,
        org_id,
        WorkloadCredentialCreate(
            project_id=project_id,
            name="collector",
            environment=LifecycleState.PRODUCTION,
            agent_id=agent_id,
            modules=[WorkloadModule.OBSERVE],
            scopes=["ingest:runs"],
        ),
        created_by="person:it@test.example",
    )
    return created.id, created.secret


async def test_create_lists_without_secret(session: AsyncSession, org_id: uuid.UUID) -> None:
    project_id = await _project(session, org_id)
    cred_id, secret = await _credential(session, org_id, project_id)

    page = await service.list_credentials(session, org_id)
    assert page.total == 1
    assert "secret" not in page.items[0].model_dump()

    detail = await service.get_credential(session, org_id, cred_id)
    assert detail.id == cred_id
    assert secret.startswith(service.SECRET_PREFIX)
    parsed = service.parse_credential_token(secret)
    assert parsed is not None
    assert parsed.org_id == org_id

    verified = await service.verify_presented_secret(session, secret)
    assert verified.org_id == org_id
    assert verified.project_id == project_id


async def test_cross_tenant_list_is_empty(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    project_id = await _project(session, org_id)
    await _credential(session, org_id, project_id)

    other_page = await service.list_credentials(session, other_org_id)
    assert other_page.total == 0


async def test_expired_secret_rejected(session: AsyncSession, org_id: uuid.UUID) -> None:
    project_id = await _project(session, org_id)
    cred_id, secret = await _credential(session, org_id, project_id)
    await session.execute(
        text("UPDATE workload_credentials SET expires_at = :exp WHERE org_id = :org AND id = :id"),
        {
            "exp": datetime.now(tz=UTC) - timedelta(minutes=5),
            "org": org_id,
            "id": cred_id,
        },
    )
    with pytest.raises(service.CredentialInvalidError):
        await service.verify_presented_secret(session, secret)


async def test_revoked_secret_rejected(session: AsyncSession, org_id: uuid.UUID) -> None:
    project_id = await _project(session, org_id)
    cred_id, secret = await _credential(session, org_id, project_id)
    await service.revoke_credential(session, org_id, cred_id)
    with pytest.raises(service.CredentialInvalidError):
        await service.verify_presented_secret(session, secret)


async def test_rotated_secret_invalidates_previous(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    project_id = await _project(session, org_id)
    cred_id, secret_v1 = await _credential(session, org_id, project_id)
    rotated = await service.rotate_credential(session, org_id, cred_id)
    with pytest.raises(service.CredentialInvalidError):
        await service.verify_presented_secret(session, secret_v1)
    await service.verify_presented_secret(session, rotated.secret)


async def test_malformed_embedded_org_rejected(session: AsyncSession, org_id: uuid.UUID) -> None:
    project_id = await _project(session, org_id)
    _, secret = await _credential(session, org_id, project_id)
    parsed = service.parse_credential_token(secret)
    assert parsed is not None
    tampered = secret.replace(str(parsed.org_id), str(uuid.uuid4()), 1)
    with pytest.raises(service.CredentialInvalidError):
        await service.verify_presented_secret(session, tampered)


async def test_no_plaintext_secret_stored(session: AsyncSession, org_id: uuid.UUID) -> None:
    project_id = await _project(session, org_id)
    _, secret = await _credential(session, org_id, project_id)
    parsed = service.parse_credential_token(secret)
    assert parsed is not None

    rows = await session.execute(
        select(WorkloadCredentialGeneration.secret_digest).where(
            WorkloadCredentialGeneration.org_id == org_id
        )
    )
    for (digest,) in rows:
        assert isinstance(digest, (bytes, memoryview))
        assert len(bytes(digest)) == 32
        assert parsed.raw_secret not in bytes(digest)


async def test_agent_scope_binding(session: AsyncSession, org_id: uuid.UUID) -> None:
    agent = await make_agent(session, org_id)
    other = await make_agent(session, org_id)
    project_id = await _project(session, org_id)
    _, secret = await _credential(session, org_id, project_id, agent_id=agent.id)

    workload = await service.verify_presented_secret(session, secret)
    service.require_agent_binding(workload, agent.id)
    with pytest.raises(service.AgentBindingError):
        service.require_agent_binding(workload, other.id)


async def test_personal_key_keeps_verified_member_attribution(
    session: AsyncSession,
    org_id: uuid.UUID,
) -> None:
    member = Member(
        id=uuid.uuid4(),
        org_id=org_id,
        email="person@test.example",
        display_name="Test Person",
        status="active",
        timezone="UTC",
        avatar_tone="default",
    )
    session.add(member)
    await session.flush()
    project_id = await _project(session, org_id)
    created = await service.create_credential(
        session,
        org_id,
        WorkloadCredentialCreate(
            project_id=project_id,
            member_id=member.id,
            name="personal-cursor-mcp",
            environment=LifecycleState.PRODUCTION,
            modules=[WorkloadModule.ROUTER],
            scopes=["mcp:invoke"],
        ),
        created_by="member:admin",
    )

    verified = await service.verify_presented_secret(session, created.secret)

    assert created.member_id == member.id
    assert verified.member_id == member.id


async def test_last_used_updated(session: AsyncSession, org_id: uuid.UUID) -> None:
    project_id = await _project(session, org_id)
    cred_id, secret = await _credential(session, org_id, project_id)

    await service.verify_presented_secret(session, secret)

    row = await session.execute(
        select(WorkloadCredential.last_used_at).where(
            WorkloadCredential.org_id == org_id,
            WorkloadCredential.id == cred_id,
        )
    )
    assert row.scalar_one() is not None


async def test_rls_hides_other_tenant_credentials(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    project_id = await _project(session, org_id)
    cred_id, _ = await _credential(session, org_id, project_id)

    await session.execute(
        text("SELECT set_config('app.org_id', :oid, true)"),
        {"oid": str(other_org_id)},
    )
    found = await session.execute(
        text("SELECT id FROM workload_credentials WHERE id = :id AND org_id = :org"),
        {"id": str(cred_id), "org": str(other_org_id)},
    )
    assert found.scalar_one_or_none() is None
