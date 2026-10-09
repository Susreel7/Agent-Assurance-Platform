"""Unit tests for workload secret handling and scope checks."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from app.domains.registry.schemas import LifecycleState
from app.domains.workload_identity import service
from app.domains.workload_identity.schemas import (
    VerifiedWorkload,
    WorkloadCredentialCreate,
    WorkloadModule,
)


def test_format_and_parse_token_roundtrip() -> None:
    org_id = uuid.uuid4()
    generation_id = uuid.uuid4()
    raw = b"x" * 32
    token = service.format_credential_token(org_id, generation_id, raw)
    parsed = service.parse_credential_token(token)
    assert parsed is not None
    assert parsed.org_id == org_id
    assert parsed.generation_id == generation_id
    assert parsed.raw_secret == raw


def test_parse_rejects_malformed_embedded_ids() -> None:
    gen_id = uuid.uuid4()
    raw = b"y" * 32
    secret_b64 = service.format_credential_token(uuid.uuid4(), gen_id, raw).split(".")[-1]
    assert (
        service.parse_credential_token(f"{service.SECRET_PREFIX}not-a-uuid.{gen_id}.{secret_b64}")
        is None
    )
    assert (
        service.parse_credential_token(
            f"{service.SECRET_PREFIX}{uuid.uuid4()}.not-a-uuid.{secret_b64}"
        )
        is None
    )
    assert service.parse_credential_token(service.SECRET_PREFIX + "only-two.parts") is None
    assert service.parse_credential_token("Bearer-not-ours") is None


def test_expires_at_must_be_timezone_aware_and_future() -> None:
    with pytest.raises(ValidationError):
        WorkloadCredentialCreate(
            project_id=uuid.uuid4(),
            name="x",
            environment=LifecycleState.PRODUCTION,
            modules=[WorkloadModule.OBSERVE],
            scopes=["ingest:runs"],
            expires_at=datetime(2030, 1, 1),
        )
    with pytest.raises(ValidationError):
        WorkloadCredentialCreate(
            project_id=uuid.uuid4(),
            name="x",
            environment=LifecycleState.PRODUCTION,
            modules=[WorkloadModule.OBSERVE],
            scopes=["ingest:runs"],
            expires_at=datetime.now(tz=UTC) - timedelta(hours=1),
        )


def test_scopes_and_modules_deduped() -> None:
    payload = WorkloadCredentialCreate(
        project_id=uuid.uuid4(),
        name="x",
        environment=LifecycleState.PRODUCTION,
        modules=[WorkloadModule.OBSERVE, WorkloadModule.OBSERVE],
        scopes=["ingest:runs", "ingest:runs"],
    )
    assert payload.modules == [WorkloadModule.OBSERVE]
    assert payload.scopes == ["ingest:runs"]


def test_require_scope_and_module() -> None:
    workload = VerifiedWorkload(
        credential_id=uuid.uuid4(),
        generation_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        agent_id=None,
        environment=LifecycleState.PRODUCTION,
        modules=frozenset({"observe"}),
        scopes=frozenset({"ingest:runs"}),
        allowed_model_patterns=(),
        expires_at=None,
    )
    service.require_scope(workload, "ingest:runs")
    service.require_module(workload, "observe")
    with pytest.raises(service.ScopeDeniedError):
        service.require_scope(workload, "ingest:traces")


def test_agent_binding_enforced() -> None:
    bound = uuid.uuid4()
    other = uuid.uuid4()
    workload = VerifiedWorkload(
        credential_id=uuid.uuid4(),
        generation_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        agent_id=bound,
        environment=LifecycleState.PRODUCTION,
        modules=frozenset({"observe"}),
        scopes=frozenset({"ingest:runs"}),
        allowed_model_patterns=(),
        expires_at=None,
    )
    service.require_agent_binding(workload, bound)
    with pytest.raises(service.AgentBindingError):
        service.require_agent_binding(workload, other)


def test_model_allowed_patterns() -> None:
    workload = VerifiedWorkload(
        credential_id=uuid.uuid4(),
        generation_id=uuid.uuid4(),
        org_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        agent_id=None,
        environment=LifecycleState.PRODUCTION,
        modules=frozenset({"observe"}),
        scopes=frozenset({"ingest:runs"}),
        allowed_model_patterns=("anthropic/*",),
        expires_at=None,
    )
    assert service.model_allowed(workload, "anthropic", "claude-sonnet-4")
    assert not service.model_allowed(workload, "openai", "gpt-4o")


def test_expiry_helper() -> None:
    past = datetime.now(tz=UTC) - timedelta(hours=1)
    future = datetime.now(tz=UTC) + timedelta(hours=1)
    assert service._is_expired(past, datetime.now(tz=UTC))
    assert not service._is_expired(future, datetime.now(tz=UTC))
