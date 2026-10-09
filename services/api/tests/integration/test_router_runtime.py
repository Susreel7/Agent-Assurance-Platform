"""Router control-plane against real Postgres."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models.model_routing import ModelRouteTarget, RouterConfigSnapshot
from app.domains.model_routing import service as routing_svc
from app.domains.model_routing.schemas import (
    DeploymentCreate,
    RouteCreate,
    RouteEnvironment,
    RouterCapability,
    RouterProvider,
    RouteSimulateRequest,
    RouteTargetIn,
    SnapshotCompileRequest,
)
from app.domains.registry.schemas import LifecycleState
from app.domains.workload_identity import service as workload_svc
from app.domains.workload_identity.schemas import (
    ProjectCreate,
    WorkloadCredentialCreate,
    WorkloadModule,
)
from app.providers.signing import build_signer
from tests.integration.test_operations import make_agent

pytestmark = [pytest.mark.integration, pytest.mark.asyncio]


@pytest.fixture(scope="session")
def signing_key_path(tmp_path_factory: pytest.TempPathFactory) -> Path:
    key = ec.generate_private_key(ec.SECP256R1())
    path = tmp_path_factory.mktemp("router-signing") / "signing.pem"
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
    monkeypatch.setenv("AAP_SIGNING_PROVIDER", "local")
    monkeypatch.setenv("AAP_SIGNING_KEY_PATH", str(signing_key_path))
    get_settings.cache_clear()


async def _project(session: AsyncSession, org_id: uuid.UUID) -> uuid.UUID:
    out = await workload_svc.create_project(
        session, org_id, ProjectCreate(slug="router", name="Router")
    )
    return out.id


async def _deployment(session: AsyncSession, org_id: uuid.UUID, project_id: uuid.UUID) -> uuid.UUID:
    dep = await routing_svc.create_deployment(
        session,
        org_id,
        project_id,
        DeploymentCreate(
            name="primary",
            provider=RouterProvider.OPENAI_COMPATIBLE,
            model="gpt-test",
            endpoint="https://example.com/v1",
            credential_ref="vault:openai",
            region="us-east-1",
            jurisdiction="US",
            capabilities=[RouterCapability.CHAT, RouterCapability.STREAMING],
        ),
        created_by="person:test@example.com",
    )
    return dep.id


async def _route(
    session: AsyncSession,
    org_id: uuid.UUID,
    project_id: uuid.UUID,
    agent_id: uuid.UUID,
    deployment_id: uuid.UUID,
) -> uuid.UUID:
    route = await routing_svc.create_route(
        session,
        org_id,
        project_id,
        RouteCreate(
            agent_id=agent_id,
            environment=RouteEnvironment.DEV,
            alias="gpt-test",
            targets=[RouteTargetIn(deployment_id=deployment_id, position=0)],
        ),
        created_by="person:test@example.com",
    )
    return route.id


async def _router_credential(
    session: AsyncSession, org_id: uuid.UUID, project_id: uuid.UUID
) -> tuple[uuid.UUID, bytes]:
    created = await workload_svc.create_credential(
        session,
        org_id,
        WorkloadCredentialCreate(
            project_id=project_id,
            name="gateway",
            environment=LifecycleState.DEV,
            modules=[WorkloadModule.ROUTER],
            scopes=["infer:chat"],
            allowed_model_patterns=["*"],
        ),
        created_by="person:test@example.com",
    )
    parsed = workload_svc.parse_credential_token(created.secret)
    assert parsed is not None
    return created.id, parsed.raw_secret


async def test_compile_snapshot_verify_and_immutable(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    project_id = await _project(session, org_id)
    dep_id = await _deployment(session, org_id, project_id)
    agent = await make_agent(session, org_id)
    await _route(session, org_id, project_id, agent.id, dep_id)
    await _router_credential(session, org_id, project_id)

    snap = await routing_svc.compile_project_snapshot(
        session,
        org_id,
        project_id,
        SnapshotCompileRequest(),
        compiled_by="person:test@example.com",
    )

    config_bytes, meta = await routing_svc.get_gateway_config_snapshot(
        session, org_id, project_id, snapshot_id=snap.id
    )
    assert meta.rules_digest == snap.rules_digest
    assert meta.config_digest == snap.config_digest
    signer = build_signer()
    assert signer.verify(config_bytes, meta.signature)
    assert meta.public_key_pem == signer.public_key_pem()

    with pytest.raises(DBAPIError):
        await session.execute(
            text(
                "UPDATE router_config_snapshots SET config_bytes = '\\x00' "
                "WHERE org_id = :org AND id = :id"
            ),
            {"org": org_id, "id": snap.id},
        )
        await session.flush()


async def test_no_plaintext_secrets_in_snapshot_or_rows(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    project_id = await _project(session, org_id)
    dep_id = await _deployment(session, org_id, project_id)
    agent = await make_agent(session, org_id)
    await _route(session, org_id, project_id, agent.id, dep_id)
    _, raw_secret = await _router_credential(session, org_id, project_id)

    snap = await routing_svc.compile_project_snapshot(
        session,
        org_id,
        project_id,
        SnapshotCompileRequest(),
        compiled_by="person:test@example.com",
    )
    row = await session.scalar(
        select(RouterConfigSnapshot).where(
            RouterConfigSnapshot.org_id == org_id, RouterConfigSnapshot.id == snap.id
        )
    )
    assert row is not None
    assert raw_secret not in row.config_bytes
    assert raw_secret.decode("latin-1", errors="ignore") not in row.config_bytes.decode()


async def test_disabled_deployment_excluded_from_simulation(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    project_id = await _project(session, org_id)
    dep_id = await _deployment(session, org_id, project_id)
    agent = await make_agent(session, org_id)
    route_id = await _route(session, org_id, project_id, agent.id, dep_id)

    await routing_svc.disable_deployment(session, org_id, project_id, dep_id)
    result = await routing_svc.simulate_route(
        session,
        org_id,
        project_id,
        route_id,
        RouteSimulateRequest(operation="chat"),
    )
    assert len(result.targets) == 1
    assert result.targets[0].eligible is False
    assert result.targets[0].reason == "deployment_disabled"


async def test_cross_tenant_isolation(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    project_id = await _project(session, org_id)
    dep_id = await _deployment(session, org_id, project_id)

    other_project = await _project(session, other_org_id)
    other_agent = await make_agent(session, other_org_id)

    with pytest.raises(routing_svc.InvalidReferenceError):
        await routing_svc.create_route(
            session,
            other_org_id,
            other_project,
            RouteCreate(
                agent_id=other_agent.id,
                environment=RouteEnvironment.DEV,
                alias="bad",
                targets=[RouteTargetIn(deployment_id=dep_id, position=0)],
            ),
            created_by="person:other@example.com",
        )


async def test_cross_tenant_fk_refused_at_database(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    project_id = await _project(session, org_id)
    other_project = await _project(session, other_org_id)
    dep_id = await _deployment(session, org_id, project_id)
    other_agent = await make_agent(session, other_org_id)

    other_dep = await _deployment(session, other_org_id, other_project)
    other_route = await routing_svc.create_route(
        session,
        other_org_id,
        other_project,
        RouteCreate(
            agent_id=other_agent.id,
            environment=RouteEnvironment.DEV,
            alias="ok",
            targets=[RouteTargetIn(deployment_id=other_dep, position=0)],
        ),
        created_by="person:other@example.com",
    )

    with pytest.raises(IntegrityError):
        session.add(
            ModelRouteTarget(
                id=uuid.uuid4(),
                org_id=other_org_id,
                project_id=other_project,
                route_id=other_route.id,
                deployment_id=dep_id,
                position=99,
            )
        )
        await session.flush()


async def test_tenant_cannot_read_other_snapshot(
    session: AsyncSession, org_id: uuid.UUID, other_org_id: uuid.UUID
) -> None:
    project_id = await _project(session, org_id)
    dep_id = await _deployment(session, org_id, project_id)
    agent = await make_agent(session, org_id)
    await _route(session, org_id, project_id, agent.id, dep_id)
    await _router_credential(session, org_id, project_id)
    snap = await routing_svc.compile_project_snapshot(
        session,
        org_id,
        project_id,
        SnapshotCompileRequest(),
        compiled_by="person:test@example.com",
    )

    other_project = await _project(session, other_org_id)
    with pytest.raises(routing_svc.SnapshotNotFoundError):
        await routing_svc.get_snapshot(session, other_org_id, other_project, snap.id)


async def test_deterministic_rules_digest_for_same_inputs(
    session: AsyncSession, org_id: uuid.UUID
) -> None:
    project_id = await _project(session, org_id)
    dep_id = await _deployment(session, org_id, project_id)
    agent = await make_agent(session, org_id)
    await _route(session, org_id, project_id, agent.id, dep_id)
    await _router_credential(session, org_id, project_id)

    first = await routing_svc.compile_project_snapshot(
        session,
        org_id,
        project_id,
        SnapshotCompileRequest(
            expires_at=datetime.now(tz=UTC) + timedelta(hours=2),
        ),
        compiled_by="person:test@example.com",
    )
    second = await routing_svc.compile_project_snapshot(
        session,
        org_id,
        project_id,
        SnapshotCompileRequest(
            expires_at=datetime.now(tz=UTC) + timedelta(hours=2),
        ),
        compiled_by="person:test@example.com",
    )
    assert first.id != second.id
    assert first.rules_digest == second.rules_digest
    assert first.config_digest != second.config_digest
