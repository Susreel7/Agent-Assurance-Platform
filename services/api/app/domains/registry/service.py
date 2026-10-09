"""Registry business logic — identity, immutable versions, ownership, drift."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.registry import repository as repo
from app.domains.registry.schemas import (
    AgentCreate,
    AgentDetail,
    AgentSummary,
    AgentUpdate,
    AgentVersionOut,
    DriftReport,
    DriftStatus,
    OwnershipOut,
    OwnershipUpsert,
    VersionPublish,
)

_URN_RE = re.compile(r"^urn:aap:[a-z0-9-]+:[a-z0-9-]+:[a-z0-9-]+$")


class RegistryError(Exception):
    """Base for everything this module raises."""


class AgentNotFoundError(RegistryError):
    def __init__(self, agent_id: UUID) -> None:
        super().__init__(f"agent {agent_id} not found")
        self.agent_id = agent_id


class AgentUrnTakenError(RegistryError):
    def __init__(self, urn: str) -> None:
        super().__init__(f"urn {urn!r} is already registered in this organisation")
        self.urn = urn


class VersionNotFoundError(RegistryError):
    def __init__(self, version_id: UUID) -> None:
        super().__init__(f"version {version_id} not found")
        self.version_id = version_id


class SemverAlreadyPublishedError(RegistryError):
    def __init__(self, semver: str) -> None:
        super().__init__(f"version {semver!r} is already published for this agent")
        self.semver = semver


class InvalidDescriptorError(RegistryError):
    def __init__(self, message: str) -> None:
        super().__init__(message)


def canonical_descriptor_digest(descriptor: dict[str, Any]) -> str:
    """Stable hash over the descriptor JSON so two uploads of the same document agree."""
    payload = json.dumps(descriptor, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def validate_aap_descriptor(descriptor: dict[str, Any]) -> None:
    """Minimum AAP 0.1 checks without rejecting forward-compatible sibling fields."""
    if descriptor.get("aap_version") != "0.1":
        raise InvalidDescriptorError("aap_version must be '0.1'")

    for key in ("agent", "accountability", "runtime"):
        if key not in descriptor:
            raise InvalidDescriptorError(f"missing required top-level field {key!r}")

    agent = descriptor["agent"]
    if not isinstance(agent, dict):
        raise InvalidDescriptorError("agent must be an object")

    urn = agent.get("urn")
    if not isinstance(urn, str) or not _URN_RE.fullmatch(urn):
        raise InvalidDescriptorError(
            "agent.urn must match ^urn:aap:[a-z0-9-]+:[a-z0-9-]+:[a-z0-9-]+$"
        )

    if not agent.get("version"):
        raise InvalidDescriptorError("agent.version is required")

    runtime = descriptor["runtime"]
    if not isinstance(runtime, dict) or not runtime.get("framework"):
        raise InvalidDescriptorError("runtime.framework is required")

    accountability = descriptor["accountability"]
    if not isinstance(accountability, dict):
        raise InvalidDescriptorError("accountability must be an object")
    for field in ("owning_team", "accountable_person"):
        if not accountability.get(field):
            raise InvalidDescriptorError(f"accountability.{field} is required")

    composition = descriptor.get("composition")
    if composition is not None:
        if not isinstance(composition, dict):
            raise InvalidDescriptorError("composition must be an object")
        for obl in composition.get("rule_obligations") or []:
            if not isinstance(obl, dict):
                raise InvalidDescriptorError("composition.rule_obligations entries must be objects")
            statement = obl.get("statement")
            if isinstance(statement, str) and len(statement.encode("utf-8")) > 512:
                raise InvalidDescriptorError(
                    "composition.rule_obligations[].statement exceeds 512 bytes"
                )
            oid = obl.get("id")
            if obl and (not isinstance(oid, str) or not oid.strip()):
                raise InvalidDescriptorError("composition.rule_obligations[].id is required")


def compute_drift_status(
    baseline_version_id: UUID | None, current_version_id: UUID | None
) -> DriftStatus:
    if baseline_version_id is None or current_version_id is None:
        return DriftStatus.UNKNOWN
    if baseline_version_id == current_version_id:
        return DriftStatus.ALIGNED
    return DriftStatus.DRIFTED


async def create_agent(session: AsyncSession, org_id: UUID, payload: AgentCreate) -> AgentDetail:
    if await repo.get_agent_by_urn(session, org_id, payload.urn):
        raise AgentUrnTakenError(payload.urn)

    values = payload.model_dump()
    agent = await repo.insert_agent(session, org_id, values)
    return await _build_detail(session, org_id, agent.id)


async def update_agent(
    session: AsyncSession, org_id: UUID, agent_id: UUID, payload: AgentUpdate
) -> AgentDetail:
    if not await repo.get_agent(session, org_id, agent_id):
        raise AgentNotFoundError(agent_id)

    values = payload.model_dump(exclude_unset=True)
    if values:
        values["updated_at"] = datetime.now(UTC)
        await repo.update_agent(session, org_id, agent_id, values)
    return await _build_detail(session, org_id, agent_id)


async def get_agent_detail(session: AsyncSession, org_id: UUID, agent_id: UUID) -> AgentDetail:
    if not await repo.get_agent(session, org_id, agent_id):
        raise AgentNotFoundError(agent_id)
    return await _build_detail(session, org_id, agent_id)


async def list_agents(
    session: AsyncSession,
    org_id: UUID,
    *,
    lifecycle_states: list[str] | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AgentSummary], int]:
    rows = await repo.list_agents(
        session,
        org_id,
        lifecycle_states=lifecycle_states,
        search=search,
        limit=limit,
        offset=offset,
    )
    total = await repo.count_agents(
        session, org_id, lifecycle_states=lifecycle_states, search=search
    )
    # Each row is (Agent, runtime_framework, current_semver): the agent's own columns
    # plus the two facts the outer join brought back from its current version.
    summaries = [
        AgentSummary.model_validate(
            {
                **{c.name: getattr(row[0], c.name) for c in row[0].__table__.columns},
                "runtime_framework": row.runtime_framework,
                "current_semver": row.current_semver,
            }
        )
        for row in rows
    ]
    return summaries, total


async def publish_version(
    session: AsyncSession,
    org_id: UUID,
    agent_id: UUID,
    payload: VersionPublish,
) -> AgentVersionOut:
    agent = await repo.get_agent(session, org_id, agent_id)
    if agent is None:
        raise AgentNotFoundError(agent_id)

    validate_aap_descriptor(payload.descriptor)

    descriptor_urn = payload.descriptor["agent"]["urn"]
    if descriptor_urn != agent.urn:
        raise InvalidDescriptorError(
            f"descriptor agent.urn {descriptor_urn!r} does not match agent {agent.urn!r}"
        )

    if await repo.exists_semver(session, org_id, agent_id, payload.semver):
        raise SemverAlreadyPublishedError(payload.semver)

    runtime = payload.descriptor.get("runtime") or {}
    digest = canonical_descriptor_digest(payload.descriptor)
    version = await repo.insert_version(
        session,
        org_id,
        agent_id,
        {
            "semver": payload.semver,
            "descriptor_json": payload.descriptor,
            "descriptor_digest": digest,
            "runtime_framework": runtime.get("framework"),
            "runtime_language": runtime.get("language"),
            "environment": payload.environment.value,
            "autonomy": runtime.get("autonomy"),
            "vcs_provider": payload.vcs_provider,
            "vcs_repo": payload.vcs_repo,
            "vcs_ref": payload.vcs_ref,
            "published_by": payload.published_by,
        },
    )

    update_values: dict[str, Any] = {
        "current_version_id": version.id,
        "updated_at": datetime.now(UTC),
    }
    if agent.baseline_version_id is None:
        update_values["baseline_version_id"] = version.id

    await repo.update_agent(session, org_id, agent_id, update_values)
    return AgentVersionOut.model_validate(version)


async def list_agent_versions(
    session: AsyncSession, org_id: UUID, agent_id: UUID
) -> list[AgentVersionOut]:
    if not await repo.get_agent(session, org_id, agent_id):
        raise AgentNotFoundError(agent_id)
    rows = await repo.list_versions(session, org_id, agent_id)
    return [AgentVersionOut.model_validate(r) for r in rows]


async def get_agent_version(
    session: AsyncSession, org_id: UUID, agent_id: UUID, version_id: UUID
) -> AgentVersionOut:
    version = await repo.get_version(session, org_id, agent_id, version_id)
    if version is None:
        raise VersionNotFoundError(version_id)
    return AgentVersionOut.model_validate(version)


async def get_version_descriptor(
    session: AsyncSession, org_id: UUID, version_id: UUID
) -> dict[str, Any]:
    """Used by neighbouring domains. Returns the stored descriptor or raises."""
    version = await repo.get_version_by_id(session, org_id, version_id)
    if version is None:
        raise VersionNotFoundError(version_id)
    return dict(version.descriptor_json)


async def set_owner(
    session: AsyncSession, org_id: UUID, agent_id: UUID, payload: OwnershipUpsert
) -> OwnershipOut:
    if not await repo.get_agent(session, org_id, agent_id):
        raise AgentNotFoundError(agent_id)

    now = datetime.now(UTC)
    await repo.close_owner(session, org_id, agent_id, payload.role.value, now)
    row = await repo.insert_owner(
        session,
        org_id,
        agent_id,
        {
            "role": payload.role.value,
            "principal_id": payload.principal_id,
            "source": payload.source,
            "valid_from": now,
        },
    )
    return OwnershipOut.model_validate(row)


async def end_owner(session: AsyncSession, org_id: UUID, agent_id: UUID, role: str) -> None:
    if not await repo.get_agent(session, org_id, agent_id):
        raise AgentNotFoundError(agent_id)
    await repo.close_owner(session, org_id, agent_id, role, datetime.now(UTC))


async def compute_drift(session: AsyncSession, org_id: UUID, agent_id: UUID) -> DriftReport:
    agent = await repo.get_agent(session, org_id, agent_id)
    if agent is None:
        raise AgentNotFoundError(agent_id)

    baseline_semver: str | None = None
    current_semver: str | None = None
    if agent.baseline_version_id:
        bv = await repo.get_version_by_id(session, org_id, agent.baseline_version_id)
        if bv:
            baseline_semver = bv.semver
    if agent.current_version_id:
        cv = await repo.get_version_by_id(session, org_id, agent.current_version_id)
        if cv:
            current_semver = cv.semver

    status = compute_drift_status(agent.baseline_version_id, agent.current_version_id)
    return DriftReport(
        agent_id=agent.id,
        urn=agent.urn,
        status=status,
        baseline_version_id=agent.baseline_version_id,
        current_version_id=agent.current_version_id,
        baseline_semver=baseline_semver,
        current_semver=current_semver,
    )


async def compute_estate_drift(session: AsyncSession, org_id: UUID) -> list[DriftReport]:
    rows = await repo.fetch_drift_rows(session, org_id)
    reports: list[DriftReport] = []
    for row in rows:
        status = compute_drift_status(row.baseline_version_id, row.current_version_id)
        reports.append(
            DriftReport(
                agent_id=row.agent_id,
                urn=row.urn,
                status=status,
                baseline_version_id=row.baseline_version_id,
                current_version_id=row.current_version_id,
                baseline_semver=row.baseline_semver,
                current_semver=row.current_semver,
            )
        )
    return reports


async def _build_detail(session: AsyncSession, org_id: UUID, agent_id: UUID) -> AgentDetail:
    agent = await repo.get_agent(session, org_id, agent_id)
    if agent is None:
        raise AgentNotFoundError(agent_id)

    owners = await repo.list_current_owners(session, org_id, agent_id)
    baseline_semver: str | None = None
    current_semver: str | None = None
    if agent.baseline_version_id:
        bv = await repo.get_version_by_id(session, org_id, agent.baseline_version_id)
        if bv:
            baseline_semver = bv.semver
    if agent.current_version_id:
        cv = await repo.get_version_by_id(session, org_id, agent.current_version_id)
        if cv:
            current_semver = cv.semver

    detail = AgentDetail.model_validate(agent)
    return detail.model_copy(
        update={
            "ownership": [OwnershipOut.model_validate(o) for o in owners],
            "baseline_semver": baseline_semver,
            "current_semver": current_semver,
        }
    )
