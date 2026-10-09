"""Workload credential lifecycle and verification."""

from __future__ import annotations

import base64
import binascii
import fnmatch
import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import NoReturn
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workload_identity import Project, WorkloadCredential
from app.domains.registry.schemas import LifecycleState
from app.domains.workload_identity import repository as repo
from app.domains.workload_identity.schemas import (
    ProjectCreate,
    ProjectOut,
    ProjectPage,
    ProjectUpdate,
    TraceCaptureMode,
    VerifiedWorkload,
    WorkloadCredentialCreate,
    WorkloadCredentialCreated,
    WorkloadCredentialOut,
    WorkloadCredentialPage,
    WorkloadIntrospectionOut,
)
from app.licensing import get_license, suite_module_access

log = logging.getLogger(__name__)

SECRET_PREFIX = "aap_wk_"
_SECRET_BYTE_LENGTH = 32
_PUBLIC_AUTH_MESSAGE = "invalid workload credential"


class WorkloadIdentityError(Exception):
    """Base for domain failures."""


class ProjectNotFoundError(WorkloadIdentityError):
    pass


class CredentialNotFoundError(WorkloadIdentityError):
    pass


class InvalidAgentScopeError(WorkloadIdentityError):
    pass


class InvalidMemberScopeError(WorkloadIdentityError):
    pass


class CapturePolicyError(WorkloadIdentityError):
    pass


class ModuleEntitlementError(WorkloadIdentityError):
    pass


class CredentialInvalidError(WorkloadIdentityError):
    """Bearer verification failed. Message is always generic for callers."""


class CredentialRevokedError(WorkloadIdentityError):
    pass


class CredentialExpiredError(WorkloadIdentityError):
    pass


class ScopeDeniedError(WorkloadIdentityError):
    pass


class AgentBindingError(WorkloadIdentityError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedCredentialToken:
    """Untrusted identifiers from the bearer string plus raw secret bytes."""

    org_id: UUID
    generation_id: UUID
    raw_secret: bytes


def _digest_secret(raw_secret: bytes) -> bytes:
    return hashlib.sha256(raw_secret).digest()


def _generate_raw_secret() -> tuple[bytes, bytes]:
    raw = secrets.token_bytes(_SECRET_BYTE_LENGTH)
    return raw, _digest_secret(raw)


def format_credential_token(org_id: UUID, generation_id: UUID, raw_secret: bytes) -> str:
    encoded = base64.urlsafe_b64encode(raw_secret).decode("ascii").rstrip("=")
    return f"{SECRET_PREFIX}{org_id}.{generation_id}.{encoded}"


def parse_credential_token(token: str) -> ParsedCredentialToken | None:
    if not token.startswith(SECRET_PREFIX):
        return None
    body = token[len(SECRET_PREFIX) :]
    parts = body.split(".", 2)
    if len(parts) != 3:
        return None
    org_raw, generation_raw, secret_b64 = parts
    try:
        org_id = UUID(org_raw)
        generation_id = UUID(generation_raw)
    except ValueError:
        return None
    padding = "=" * (-len(secret_b64) % 4)
    try:
        raw = base64.urlsafe_b64decode(secret_b64 + padding)
    except (ValueError, binascii.Error):
        return None
    if len(raw) != _SECRET_BYTE_LENGTH:
        return None
    return ParsedCredentialToken(org_id=org_id, generation_id=generation_id, raw_secret=raw)


def _auth_fail(reason: str) -> NoReturn:
    log.warning("workload credential rejected: %s", reason)
    raise CredentialInvalidError(_PUBLIC_AUTH_MESSAGE)


def _credential_out(
    cred: WorkloadCredential, *, generation_number: int | None
) -> WorkloadCredentialOut:
    return WorkloadCredentialOut(
        id=cred.id,
        org_id=cred.org_id,
        project_id=cred.project_id,
        agent_id=cred.agent_id,
        member_id=cred.member_id,
        name=cred.name,
        environment=LifecycleState(cred.environment),
        modules=list(cred.modules),
        scopes=list(cred.scopes),
        allowed_model_patterns=list(cred.allowed_model_patterns),
        rpm=cred.rpm,
        tpm=cred.tpm,
        max_concurrency=cred.max_concurrency,
        daily_budget_micros=cred.daily_budget_micros,
        expires_at=cred.expires_at,
        revoked_at=cred.revoked_at,
        active_generation_number=generation_number,
        last_used_at=cred.last_used_at,
        created_at=cred.created_at,
        created_by=cred.created_by,
    )


def _ensure_modules_configurable(module_ids: list[str]) -> None:
    license_ = get_license()
    denied = [
        module_id
        for module_id in module_ids
        if not suite_module_access(license_, module_id).configure
    ]
    if denied:
        raise ModuleEntitlementError(f"module_not_entitled: {', '.join(sorted(denied))}")


def _project_out(project: Project) -> ProjectOut:
    return ProjectOut.model_validate(project, from_attributes=True)


async def create_project(session: AsyncSession, org_id: UUID, payload: ProjectCreate) -> ProjectOut:
    project = await repo.insert_project(
        session,
        org_id,
        {
            "id": uuid4(),
            "slug": payload.slug.strip(),
            "name": payload.name.strip(),
            "trace_capture_mode": payload.trace_capture_mode.value,
            "payload_retention_days": payload.payload_retention_days,
            "payload_encryption_key_ref": payload.payload_encryption_key_ref,
        },
    )
    return _project_out(project)


async def list_projects(
    session: AsyncSession, org_id: UUID, *, limit: int = 50, offset: int = 0
) -> ProjectPage:
    items, total = await repo.list_projects(session, org_id, limit=limit, offset=offset)
    return ProjectPage(
        items=[_project_out(project) for project in items],
        total=total,
        limit=limit,
        offset=offset,
    )


async def get_project(session: AsyncSession, org_id: UUID, project_id: UUID) -> ProjectOut:
    project = await repo.get_project(session, org_id, project_id)
    if project is None:
        raise ProjectNotFoundError(f"project {project_id} not found")
    return _project_out(project)


async def update_project(
    session: AsyncSession,
    org_id: UUID,
    project_id: UUID,
    payload: ProjectUpdate,
) -> ProjectOut:
    existing = await repo.get_project(session, org_id, project_id)
    if existing is None:
        raise ProjectNotFoundError(f"project {project_id} not found")
    values = payload.model_dump(exclude_unset=True)
    capture_mode = values.get("trace_capture_mode")
    if capture_mode is not None:
        values["trace_capture_mode"] = TraceCaptureMode(capture_mode).value
    effective_mode = values.get("trace_capture_mode", existing.trace_capture_mode)
    effective_key = values.get("payload_encryption_key_ref", existing.payload_encryption_key_ref)
    if effective_mode == TraceCaptureMode.FULL.value and not effective_key:
        raise CapturePolicyError("full capture requires payload_encryption_key_ref")
    values["updated_at"] = datetime.now(tz=UTC)
    project = await repo.update_project(session, org_id, project_id, values)
    if project is None:
        raise ProjectNotFoundError(f"project {project_id} not found")
    return _project_out(project)


async def introspection_for_workload(
    session: AsyncSession, workload: VerifiedWorkload
) -> WorkloadIntrospectionOut:
    project = await repo.get_project(session, workload.org_id, workload.project_id)
    if project is None:
        raise ProjectNotFoundError(f"project {workload.project_id} not found")
    return WorkloadIntrospectionOut(
        credential_id=workload.credential_id,
        generation_id=workload.generation_id,
        organization_id=workload.org_id,
        project_id=workload.project_id,
        agent_id=workload.agent_id,
        member_id=workload.member_id,
        environment=workload.environment,
        modules=sorted(workload.modules),
        scopes=sorted(workload.scopes),
        allowed_model_patterns=list(workload.allowed_model_patterns),
        expires_at=workload.expires_at,
        capture_mode=TraceCaptureMode(project.trace_capture_mode),
        payload_retention_days=project.payload_retention_days,
        payload_encryption_key_ref=project.payload_encryption_key_ref,
        rpm=workload.rpm,
        tpm=workload.tpm,
        max_concurrency=workload.max_concurrency,
        daily_budget_micros=workload.daily_budget_micros,
    )


async def _generation_number_for_active(
    session: AsyncSession, org_id: UUID, cred: WorkloadCredential
) -> int | None:
    if cred.active_generation_id is None:
        return None
    gen = await repo.get_generation(session, org_id, cred.active_generation_id)
    return gen.generation_number if gen is not None else None


async def create_credential(
    session: AsyncSession,
    org_id: UUID,
    payload: WorkloadCredentialCreate,
    *,
    created_by: str,
) -> WorkloadCredentialCreated:
    _ensure_modules_configurable([module.value for module in payload.modules])
    project = await repo.get_project(session, org_id, payload.project_id)
    if project is None:
        raise ProjectNotFoundError(f"project {payload.project_id} not found")

    if payload.agent_id is not None and not await repo.agent_belongs_to_org(
        session, org_id, payload.agent_id
    ):
        raise InvalidAgentScopeError(f"agent {payload.agent_id} is not in organisation {org_id}")
    if payload.member_id is not None and not await repo.member_belongs_to_org(
        session, org_id, payload.member_id
    ):
        raise InvalidMemberScopeError(f"member {payload.member_id} is not in organisation {org_id}")

    cred_id = uuid4()
    generation_id = uuid4()
    raw_secret, digest = _generate_raw_secret()
    cred = await repo.insert_credential(
        session,
        org_id,
        {
            "id": cred_id,
            "project_id": payload.project_id,
            "agent_id": payload.agent_id,
            "member_id": payload.member_id,
            "name": payload.name.strip(),
            "environment": payload.environment.value,
            "modules": [m.value for m in payload.modules],
            "scopes": payload.scopes,
            "allowed_model_patterns": payload.allowed_model_patterns,
            "rpm": payload.rpm,
            "tpm": payload.tpm,
            "max_concurrency": payload.max_concurrency,
            "daily_budget_micros": payload.daily_budget_micros,
            "expires_at": payload.expires_at,
            "created_by": created_by,
        },
    )
    generation = await repo.insert_generation(
        session,
        org_id,
        {
            "id": generation_id,
            "credential_id": cred_id,
            "generation_number": 1,
            "secret_digest": digest,
        },
    )
    await repo.set_active_generation(session, org_id, cred_id, generation.id)
    await session.refresh(cred)

    token = format_credential_token(org_id, generation_id, raw_secret)
    base = _credential_out(cred, generation_number=1)
    return WorkloadCredentialCreated(**base.model_dump(), secret=token)


async def list_credentials(
    session: AsyncSession,
    org_id: UUID,
    *,
    project_id: UUID | None = None,
    limit: int = 50,
    offset: int = 0,
) -> WorkloadCredentialPage:
    rows, total = await repo.list_credentials(
        session, org_id, project_id=project_id, limit=limit, offset=offset
    )
    items: list[WorkloadCredentialOut] = []
    for cred in rows:
        gen_no = await _generation_number_for_active(session, org_id, cred)
        items.append(_credential_out(cred, generation_number=gen_no))
    return WorkloadCredentialPage(items=items, total=total, limit=limit, offset=offset)


async def get_credential(
    session: AsyncSession, org_id: UUID, credential_id: UUID
) -> WorkloadCredentialOut:
    cred = await repo.get_credential(session, org_id, credential_id)
    if cred is None:
        raise CredentialNotFoundError(f"credential {credential_id} not found")
    gen_no = await _generation_number_for_active(session, org_id, cred)
    return _credential_out(cred, generation_number=gen_no)


async def rotate_credential(
    session: AsyncSession,
    org_id: UUID,
    credential_id: UUID,
) -> WorkloadCredentialCreated:
    cred = await repo.get_credential_for_update(session, org_id, credential_id)
    if cred is None:
        raise CredentialNotFoundError(f"credential {credential_id} not found")
    if cred.revoked_at is not None:
        raise CredentialRevokedError("credential is revoked")
    _ensure_modules_configurable(list(cred.modules))

    now = datetime.now(tz=UTC)
    if cred.active_generation_id is not None:
        await repo.revoke_generation(session, org_id, cred.active_generation_id, now)

    next_number = await repo.max_generation_number(session, org_id, credential_id) + 1
    generation_id = uuid4()
    raw_secret, digest = _generate_raw_secret()
    generation = await repo.insert_generation(
        session,
        org_id,
        {
            "id": generation_id,
            "credential_id": credential_id,
            "generation_number": next_number,
            "secret_digest": digest,
        },
    )
    await repo.set_active_generation(session, org_id, credential_id, generation.id)
    await session.refresh(cred)
    token = format_credential_token(org_id, generation_id, raw_secret)
    base = _credential_out(cred, generation_number=next_number)
    return WorkloadCredentialCreated(**base.model_dump(), secret=token)


async def revoke_credential(
    session: AsyncSession, org_id: UUID, credential_id: UUID
) -> WorkloadCredentialOut:
    cred = await repo.get_credential(session, org_id, credential_id)
    if cred is None:
        raise CredentialNotFoundError(f"credential {credential_id} not found")
    now = datetime.now(tz=UTC)
    await repo.revoke_credential(session, org_id, credential_id, now)
    if cred.active_generation_id is not None:
        await repo.revoke_generation(session, org_id, cred.active_generation_id, now)
    await session.refresh(cred)
    gen_no = await _generation_number_for_active(session, org_id, cred)
    return _credential_out(cred, generation_number=gen_no)


def _is_expired(expires_at: datetime | None, now: datetime) -> bool:
    if expires_at is None:
        return False
    return expires_at.astimezone(UTC) <= now


async def verify_presented_secret(
    session: AsyncSession,
    token: str,
    *,
    touch_last_used: bool = True,
) -> VerifiedWorkload:
    """Verify bearer token: lookup by org and generation, then compare digest."""
    parsed = parse_credential_token(token)
    if parsed is None:
        _auth_fail("malformed token")

    row = await repo.get_generation_with_credential(session, parsed.org_id, parsed.generation_id)
    if row is None:
        _auth_fail("unknown org/generation pair")

    credential, generation = row
    if generation.credential_id != credential.id:
        _auth_fail("generation does not belong to credential")

    if credential.org_id != parsed.org_id:
        _auth_fail("org mismatch")

    now = datetime.now(tz=UTC)

    if credential.revoked_at is not None:
        _auth_fail("credential revoked")

    if generation.revoked_at is not None:
        _auth_fail("generation revoked")

    if credential.active_generation_id != generation.id:
        _auth_fail("not the active generation")

    digest = _digest_secret(parsed.raw_secret)
    if not secrets.compare_digest(generation.secret_digest, digest):
        _auth_fail("digest mismatch")

    if _is_expired(credential.expires_at, now):
        _auth_fail("credential expired")

    if touch_last_used:
        await repo.touch_last_used(session, credential.org_id, credential.id, now)

    return VerifiedWorkload(
        credential_id=credential.id,
        generation_id=generation.id,
        org_id=credential.org_id,
        project_id=credential.project_id,
        agent_id=credential.agent_id,
        member_id=credential.member_id,
        environment=LifecycleState(credential.environment),
        modules=frozenset(credential.modules),
        scopes=frozenset(credential.scopes),
        allowed_model_patterns=tuple(credential.allowed_model_patterns),
        rpm=credential.rpm,
        tpm=credential.tpm,
        max_concurrency=credential.max_concurrency,
        daily_budget_micros=credential.daily_budget_micros,
        expires_at=credential.expires_at,
    )


def require_scope(workload: VerifiedWorkload, scope: str) -> None:
    if scope not in workload.scopes:
        raise ScopeDeniedError(f"scope {scope!r} not granted")


def require_module(workload: VerifiedWorkload, module: str) -> None:
    if module not in workload.modules:
        raise ScopeDeniedError(f"module {module!r} not entitled")


def require_agent_binding(workload: VerifiedWorkload, agent_id: UUID) -> None:
    if workload.agent_id is not None and workload.agent_id != agent_id:
        raise AgentBindingError("credential is bound to a different agent")


def model_allowed(workload: VerifiedWorkload, provider: str, model_id: str) -> bool:
    if not workload.allowed_model_patterns:
        return True
    candidate = f"{provider}/{model_id}"
    for pattern in workload.allowed_model_patterns:
        if fnmatch.fnmatch(candidate, pattern) or fnmatch.fnmatch(model_id, pattern):
            return True
    return False
