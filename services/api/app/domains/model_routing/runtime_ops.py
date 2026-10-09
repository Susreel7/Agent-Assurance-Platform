"""Router control-plane CRUD and snapshot orchestration (model_routing service layer)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.models.model_routing import ModelDeployment, ModelRoute, ModelRouteTarget
from app.domains.model_routing import repository as repo
from app.domains.model_routing import snapshot_compile as compile_mod
from app.domains.model_routing.schemas import (
    DeploymentCreate,
    DeploymentOut,
    DeploymentPage,
    DeploymentUpdate,
    EnforcementLevel,
    RouteCreate,
    RouteEnvironment,
    RouteOut,
    RoutePage,
    RouterCapability,
    RouterProvider,
    RouteSimulateRequest,
    RouteSimulateResult,
    RouteStrategy,
    RouteTargetIn,
    RouteTargetSimulation,
    RouteUpdate,
    SnapshotCompileRequest,
    SnapshotConfigMeta,
    SnapshotOut,
    SnapshotStatus,
)
from app.domains.registry import service as registry_svc
from app.providers.signing import build_signer


class ProjectNotFoundError(Exception):
    pass


class DeploymentNotFoundError(Exception):
    pass


class RouteNotFoundError(Exception):
    pass


class SnapshotNotFoundError(Exception):
    pass


class RouterCompileError(Exception):
    pass


class InvalidReferenceError(Exception):
    pass


def _deployment_values(payload: DeploymentCreate, *, created_by: str) -> dict[str, Any]:
    cooldown = payload.cooldown
    return {
        "name": payload.name,
        "provider": payload.provider.value,
        "model": payload.model,
        "endpoint": payload.endpoint,
        "credential_ref": payload.credential_ref,
        "region": payload.region,
        "jurisdiction": payload.jurisdiction,
        "capabilities": [c.value for c in payload.capabilities],
        "priority": payload.priority,
        "weight": payload.weight,
        "rpm": payload.rpm,
        "tpm": payload.tpm,
        "timeout_ms": payload.timeout_ms,
        "max_retries": payload.max_retries,
        "input_price_micros_per_m": payload.input_price_micros_per_m,
        "output_price_micros_per_m": payload.output_price_micros_per_m,
        "max_concurrency": payload.max_concurrency,
        "daily_budget_micros": payload.daily_budget_micros,
        "cooldown_failure_threshold": cooldown.failure_threshold if cooldown else None,
        "cooldown_initial_ms": cooldown.initial_cooldown_ms if cooldown else None,
        "cooldown_max_ms": cooldown.max_cooldown_ms if cooldown else None,
        "data_classes": payload.data_classes or None,
        "created_by": created_by,
    }


def _deployment_out(row: ModelDeployment) -> DeploymentOut:
    return DeploymentOut(
        id=row.id,
        org_id=row.org_id,
        project_id=row.project_id,
        name=row.name,
        provider=RouterProvider(row.provider),
        model=row.model,
        endpoint=row.endpoint,
        credential_ref=row.credential_ref,
        region=row.region,
        jurisdiction=row.jurisdiction,
        capabilities=[RouterCapability(c) for c in row.capabilities],
        priority=row.priority,
        weight=row.weight,
        rpm=row.rpm,
        tpm=row.tpm,
        timeout_ms=row.timeout_ms,
        max_retries=row.max_retries,
        input_price_micros_per_m=row.input_price_micros_per_m,
        output_price_micros_per_m=row.output_price_micros_per_m,
        max_concurrency=row.max_concurrency,
        daily_budget_micros=row.daily_budget_micros,
        cooldown=compile_mod.deployment_out_cooldown(row),
        data_classes=list(row.data_classes or []),
        disabled_at=row.disabled_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


async def _ensure_project(session: AsyncSession, org_id: UUID, project_id: UUID) -> None:
    project = await repo.get_project(session, org_id, project_id)
    if project is None:
        raise ProjectNotFoundError(str(project_id))


async def require_project(session: AsyncSession, org_id: UUID, project_id: UUID) -> None:
    await _ensure_project(session, org_id, project_id)


async def create_deployment(
    session: AsyncSession,
    org_id: UUID,
    project_id: UUID,
    payload: DeploymentCreate,
    *,
    created_by: str,
) -> DeploymentOut:
    await _ensure_project(session, org_id, project_id)
    row = await repo.insert_deployment(
        session,
        org_id,
        {"project_id": project_id, **_deployment_values(payload, created_by=created_by)},
    )
    return _deployment_out(row)


async def list_project_deployments(
    session: AsyncSession,
    org_id: UUID,
    project_id: UUID,
    *,
    include_disabled: bool = False,
    limit: int = 200,
    offset: int = 0,
) -> DeploymentPage:
    await _ensure_project(session, org_id, project_id)
    rows, total = await repo.list_deployments(
        session, org_id, project_id, include_disabled=include_disabled, limit=limit, offset=offset
    )
    return DeploymentPage(items=[_deployment_out(r) for r in rows], total=total)


async def update_deployment(
    session: AsyncSession,
    org_id: UUID,
    project_id: UUID,
    deployment_id: UUID,
    payload: DeploymentUpdate,
) -> DeploymentOut:
    await _ensure_project(session, org_id, project_id)
    values: dict[str, Any] = {}
    for key in (
        "name",
        "endpoint",
        "credential_ref",
        "priority",
        "weight",
        "rpm",
        "tpm",
        "timeout_ms",
        "max_retries",
        "input_price_micros_per_m",
        "output_price_micros_per_m",
        "max_concurrency",
        "daily_budget_micros",
        "data_classes",
    ):
        if key in payload.model_fields_set:
            values[key] = getattr(payload, key)
    if "capabilities" in payload.model_fields_set:
        assert payload.capabilities is not None
        values["capabilities"] = [c.value for c in payload.capabilities]
    if "cooldown" in payload.model_fields_set and payload.cooldown is not None:
        values["cooldown_failure_threshold"] = payload.cooldown.failure_threshold
        values["cooldown_initial_ms"] = payload.cooldown.initial_cooldown_ms
        values["cooldown_max_ms"] = payload.cooldown.max_cooldown_ms
    elif "cooldown" in payload.model_fields_set:
        values["cooldown_failure_threshold"] = None
        values["cooldown_initial_ms"] = None
        values["cooldown_max_ms"] = None
    values["updated_at"] = datetime.now(UTC)
    row = await repo.update_deployment(session, org_id, project_id, deployment_id, values)
    if row is None:
        raise DeploymentNotFoundError(str(deployment_id))
    return _deployment_out(row)


async def disable_deployment(
    session: AsyncSession, org_id: UUID, project_id: UUID, deployment_id: UUID
) -> DeploymentOut:
    await _ensure_project(session, org_id, project_id)
    row = await repo.disable_deployment(
        session, org_id, project_id, deployment_id, datetime.now(UTC)
    )
    if row is None:
        raise DeploymentNotFoundError(str(deployment_id))
    return _deployment_out(row)


async def _validate_targets(
    session: AsyncSession,
    org_id: UUID,
    project_id: UUID,
    targets: list[RouteTargetIn],
) -> list[dict[str, Any]]:
    seen: set[UUID] = set()
    out: list[dict[str, Any]] = []
    for target in sorted(targets, key=lambda t: t.position):
        if target.deployment_id in seen:
            raise InvalidReferenceError("duplicate deployment in route targets")
        seen.add(target.deployment_id)
        dep = await repo.get_deployment(session, org_id, project_id, target.deployment_id)
        if dep is None or dep.disabled_at is not None:
            raise InvalidReferenceError(f"deployment {target.deployment_id} unavailable")
        out.append({"deployment_id": target.deployment_id, "position": target.position})
    return out


async def _route_out(session: AsyncSession, org_id: UUID, route: ModelRoute) -> RouteOut:
    targets = await repo.list_route_targets(session, org_id, route.id)
    return RouteOut(
        id=route.id,
        org_id=route.org_id,
        project_id=route.project_id,
        agent_id=route.agent_id,
        agent_version_id=route.agent_version_id,
        environment=RouteEnvironment(route.environment),
        alias=route.alias,
        strategy=RouteStrategy(route.strategy),
        enforcement=EnforcementLevel(route.enforcement),
        targets=[
            RouteTargetIn(deployment_id=t.deployment_id, position=t.position) for t in targets
        ],
        permitted_regions=list(route.permitted_regions or []),
        data_classes=list(route.data_classes or []),
        fallback_before_first_byte=route.fallback_before_first_byte,
        max_attempts=route.max_attempts,
        response_cache_enabled=route.response_cache_enabled,
        response_cache_ttl_seconds=route.response_cache_ttl_seconds,
        disabled_at=route.disabled_at,
        created_at=route.created_at,
        updated_at=route.updated_at,
    )


async def create_route(
    session: AsyncSession,
    org_id: UUID,
    project_id: UUID,
    payload: RouteCreate,
    *,
    created_by: str,
) -> RouteOut:
    await _ensure_project(session, org_id, project_id)
    try:
        await registry_svc.get_agent_detail(session, org_id, payload.agent_id)
    except registry_svc.AgentNotFoundError as exc:
        raise InvalidReferenceError(str(exc)) from exc
    if payload.agent_version_id is not None:
        try:
            await registry_svc.get_agent_version(
                session, org_id, payload.agent_id, payload.agent_version_id
            )
        except registry_svc.VersionNotFoundError as exc:
            raise InvalidReferenceError(str(exc)) from exc
    target_rows = await _validate_targets(session, org_id, project_id, payload.targets)
    route = await repo.insert_route(
        session,
        org_id,
        {
            "project_id": project_id,
            "agent_id": payload.agent_id,
            "agent_version_id": payload.agent_version_id,
            "environment": payload.environment.value,
            "alias": payload.alias,
            "strategy": payload.strategy.value,
            "enforcement": payload.enforcement.value,
            "permitted_regions": payload.permitted_regions or None,
            "data_classes": payload.data_classes or None,
            "fallback_before_first_byte": payload.fallback_before_first_byte,
            "max_attempts": payload.max_attempts,
            "response_cache_enabled": payload.response_cache_enabled,
            "response_cache_ttl_seconds": payload.response_cache_ttl_seconds,
            "created_by": created_by,
        },
        target_rows,
    )
    return await _route_out(session, org_id, route)


async def list_project_routes(
    session: AsyncSession,
    org_id: UUID,
    project_id: UUID,
    *,
    include_disabled: bool = False,
    limit: int = 200,
    offset: int = 0,
) -> RoutePage:
    await _ensure_project(session, org_id, project_id)
    rows, total = await repo.list_routes(
        session, org_id, project_id, include_disabled=include_disabled, limit=limit, offset=offset
    )
    items = [await _route_out(session, org_id, row) for row in rows]
    return RoutePage(items=items, total=total)


async def update_route(
    session: AsyncSession,
    org_id: UUID,
    project_id: UUID,
    route_id: UUID,
    payload: RouteUpdate,
) -> RouteOut:
    await _ensure_project(session, org_id, project_id)
    existing = await repo.get_route(session, org_id, project_id, route_id)
    if existing is None or existing.disabled_at is not None:
        raise RouteNotFoundError(str(route_id))
    if "agent_version_id" in payload.model_fields_set and payload.agent_version_id is not None:
        try:
            await registry_svc.get_agent_version(
                session, org_id, existing.agent_id, payload.agent_version_id
            )
        except registry_svc.VersionNotFoundError as exc:
            raise InvalidReferenceError(str(exc)) from exc
    data = payload.model_dump(exclude_unset=True)
    targets = data.pop("targets", None)
    values: dict[str, Any] = {"updated_at": datetime.now(UTC)}
    for key in (
        "agent_version_id",
        "permitted_regions",
        "data_classes",
        "fallback_before_first_byte",
        "max_attempts",
        "response_cache_enabled",
        "response_cache_ttl_seconds",
    ):
        if key in data:
            values[key] = data[key]
    if "strategy" in data and data["strategy"] is not None:
        values["strategy"] = RouteStrategy(data["strategy"]).value
    if "enforcement" in data and data["enforcement"] is not None:
        values["enforcement"] = EnforcementLevel(data["enforcement"]).value
    cache_enabled = values.get("response_cache_enabled", existing.response_cache_enabled)
    cache_ttl = values.get("response_cache_ttl_seconds", existing.response_cache_ttl_seconds)
    if cache_enabled and cache_ttl is None:
        raise InvalidReferenceError("response_cache_ttl_seconds is required when cache is enabled")
    if targets is not None:
        target_rows = await _validate_targets(session, org_id, project_id, targets)
        await repo.replace_route_targets(session, org_id, project_id, route_id, target_rows)
    row = await repo.update_route(session, org_id, project_id, route_id, values)
    if row is None:
        raise RouteNotFoundError(str(route_id))
    return await _route_out(session, org_id, row)


def _has_capability(dep: ModelDeployment, operation: str) -> bool:
    return operation in dep.capabilities or (
        operation in {"chat", "responses"} and operation in dep.capabilities
    )


def _simulate_target(
    *,
    route: ModelRoute,
    target: ModelRouteTarget,
    dep: ModelDeployment | None,
    request: RouteSimulateRequest,
) -> RouteTargetSimulation:
    if route.disabled_at is not None:
        return RouteTargetSimulation(
            deployment_id=target.deployment_id,
            position=target.position,
            eligible=False,
            reason="route_disabled",
        )
    if target.disabled_at is not None:
        return RouteTargetSimulation(
            deployment_id=target.deployment_id,
            position=target.position,
            eligible=False,
            reason="target_disabled",
        )
    if dep is None:
        return RouteTargetSimulation(
            deployment_id=target.deployment_id,
            position=target.position,
            eligible=False,
            reason="deployment_missing",
        )
    if dep.disabled_at is not None:
        return RouteTargetSimulation(
            deployment_id=target.deployment_id,
            position=target.position,
            eligible=False,
            reason="deployment_disabled",
        )
    if not _has_capability(dep, request.operation):
        return RouteTargetSimulation(
            deployment_id=target.deployment_id,
            position=target.position,
            eligible=False,
            reason="capability_mismatch",
        )
    if route.permitted_regions and dep.region not in route.permitted_regions:
        return RouteTargetSimulation(
            deployment_id=target.deployment_id,
            position=target.position,
            eligible=False,
            reason="region_not_permitted",
        )
    if request.region_hint and dep.region != request.region_hint:
        return RouteTargetSimulation(
            deployment_id=target.deployment_id,
            position=target.position,
            eligible=False,
            reason="region_hint_mismatch",
        )
    if request.data_class and route.data_classes and request.data_class not in route.data_classes:
        return RouteTargetSimulation(
            deployment_id=target.deployment_id,
            position=target.position,
            eligible=False,
            reason="route_data_class_mismatch",
        )
    if request.data_class and dep.data_classes and request.data_class not in dep.data_classes:
        return RouteTargetSimulation(
            deployment_id=target.deployment_id,
            position=target.position,
            eligible=False,
            reason="deployment_data_class_mismatch",
        )
    return RouteTargetSimulation(
        deployment_id=target.deployment_id,
        position=target.position,
        eligible=True,
        reason="eligible",
    )


async def simulate_route(
    session: AsyncSession,
    org_id: UUID,
    project_id: UUID,
    route_id: UUID,
    request: RouteSimulateRequest,
) -> RouteSimulateResult:
    await _ensure_project(session, org_id, project_id)
    route = await repo.get_route(session, org_id, project_id, route_id)
    if route is None:
        raise RouteNotFoundError(str(route_id))
    targets = await repo.list_route_targets(session, org_id, route_id)
    sims: list[RouteTargetSimulation] = []
    for target in targets:
        dep = await repo.get_deployment(session, org_id, project_id, target.deployment_id)
        sims.append(_simulate_target(route=route, target=target, dep=dep, request=request))
    return RouteSimulateResult(route_id=route_id, targets=sims)


async def compile_project_snapshot(
    session: AsyncSession,
    org_id: UUID,
    project_id: UUID,
    payload: SnapshotCompileRequest,
    *,
    compiled_by: str,
) -> SnapshotOut:
    await _ensure_project(session, org_id, project_id)
    now = datetime.now(UTC)
    settings = get_settings()
    expires_at = payload.expires_at or (now + timedelta(hours=settings.router_snapshot_ttl_hours))
    if expires_at <= now:
        raise RouterCompileError("expires_at must be in the future")

    deployments = await repo.list_enabled_deployments(session, org_id, project_id)
    routes = await repo.list_enabled_routes(session, org_id, project_id)
    if not deployments:
        raise RouterCompileError("no enabled deployments")
    if not routes:
        raise RouterCompileError("no enabled routes")

    targets_by_route: dict[UUID, list[ModelRouteTarget]] = {}
    for route in routes:
        targets_by_route[route.id] = await repo.list_route_targets(session, org_id, route.id)

    bindings = await repo.list_router_workload_bindings(session, org_id, project_id, now=now)
    if not bindings:
        raise RouterCompileError("no active router workload credentials")

    try:
        (
            snapshot_id,
            config_bytes,
            rules_digest,
            signature,
            key_id,
            public_key_pem,
            issued_at,
            expires_at,
        ) = compile_mod.compile_and_sign(
            org_id=org_id,
            project_id=project_id,
            issued_at=now,
            expires_at=expires_at,
            deployments=deployments,
            routes=routes,
            targets_by_route=targets_by_route,
            bindings=bindings,
        )
        config_digest = f"sha256:{hashlib.sha256(config_bytes).hexdigest()}"
    except ValueError as exc:
        raise RouterCompileError(str(exc)) from exc

    signing_key = await repo.register_signing_key(
        session,
        org_id,
        key_id=key_id,
        public_key_pem=public_key_pem,
        used_at=now,
    )
    if signing_key is None:
        raise RouterCompileError("signing key id is already registered with different material")

    await repo.supersede_active_snapshots(session, org_id, project_id)
    row = await repo.insert_snapshot(
        session,
        org_id,
        {
            "id": snapshot_id,
            "project_id": project_id,
            "config_bytes": config_bytes,
            "config_digest": config_digest,
            "rules_digest": rules_digest,
            "signature": signature,
            "key_id": key_id,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "status": SnapshotStatus.ACTIVE.value,
            "compiled_by": compiled_by,
        },
    )
    return SnapshotOut(
        id=row.id,
        org_id=row.org_id,
        project_id=row.project_id,
        config_digest=row.config_digest,
        rules_digest=row.rules_digest,
        key_id=row.key_id,
        issued_at=row.issued_at,
        expires_at=row.expires_at,
        status=SnapshotStatus(row.status),
        compiled_by=row.compiled_by,
        created_at=row.created_at,
    )


async def get_snapshot(
    session: AsyncSession, org_id: UUID, project_id: UUID, snapshot_id: UUID
) -> SnapshotOut:
    await _ensure_project(session, org_id, project_id)
    row = await repo.get_snapshot(session, org_id, project_id, snapshot_id)
    if row is None:
        raise SnapshotNotFoundError(str(snapshot_id))
    return SnapshotOut(
        id=row.id,
        org_id=row.org_id,
        project_id=row.project_id,
        config_digest=row.config_digest,
        rules_digest=row.rules_digest,
        key_id=row.key_id,
        issued_at=row.issued_at,
        expires_at=row.expires_at,
        status=SnapshotStatus(row.status),
        compiled_by=row.compiled_by,
        created_at=row.created_at,
    )


async def get_gateway_config_snapshot(
    session: AsyncSession, org_id: UUID, project_id: UUID, *, snapshot_id: UUID | None = None
) -> tuple[bytes, SnapshotConfigMeta]:
    await _ensure_project(session, org_id, project_id)
    now = datetime.now(UTC)
    if snapshot_id is not None:
        row = await repo.get_snapshot(session, org_id, project_id, snapshot_id)
    else:
        row = await repo.get_latest_active_snapshot(session, org_id, project_id, now=now)
    if row is None:
        raise SnapshotNotFoundError("no active snapshot")
    signing_key = await repo.get_signing_key(session, org_id, row.key_id)
    if signing_key is None:
        raise SnapshotNotFoundError("snapshot signing key is unavailable")
    return row.config_bytes, SnapshotConfigMeta(
        snapshot_id=row.id,
        config_digest=row.config_digest,
        rules_digest=row.rules_digest,
        key_id=row.key_id,
        signature=row.signature,
        issued_at=row.issued_at,
        expires_at=row.expires_at,
        public_key_pem=signing_key.public_key_pem,
    )


def signing_public_key_pem() -> str:
    return build_signer().public_key_pem()
