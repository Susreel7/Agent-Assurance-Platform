"""Signed router snapshot compilation — internal to model_routing service."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from jsonschema import Draft202012Validator

from app.config import Settings, get_settings
from app.db.models.model_routing import ModelDeployment, ModelRoute, ModelRouteTarget
from app.db.models.workload_identity import WorkloadCredential, WorkloadCredentialGeneration
from app.domains.model_routing.schemas import CooldownPolicyIn
from app.licensing import get_license
from app.providers.signing import Signer, build_signer


def _schema_path() -> Path:
    candidates = [
        Path("/contracts/router-config.schema.json"),
        Path("/app/router-config.schema.json"),
    ]
    for parent in Path(__file__).resolve().parents:
        candidates.extend(
            (
                parent / "docs" / "contracts" / "router-config.schema.json",
                parent / "router-config.schema.json",
            )
        )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise RuntimeError("router-config.schema.json is not installed")


def _load_schema_validator() -> Draft202012Validator:
    schema = json.loads(_schema_path().read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


def _iso_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _digest_hex(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _canonical_json(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _cooldown_dict(dep: ModelDeployment) -> dict[str, int] | None:
    if dep.cooldown_failure_threshold is None:
        return None
    return {
        "failure_threshold": dep.cooldown_failure_threshold,
        "initial_cooldown_ms": dep.cooldown_initial_ms or 1,
        "max_cooldown_ms": dep.cooldown_max_ms or 1,
    }


def deployment_json(dep: ModelDeployment) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(dep.id),
        "provider": dep.provider,
        "model": dep.model,
        "endpoint": dep.endpoint,
        "credential_ref": dep.credential_ref,
        "region": dep.region,
        "jurisdiction": dep.jurisdiction,
        "capabilities": sorted(set(dep.capabilities)),
        "priority": dep.priority,
        "weight": dep.weight,
        "timeout_ms": dep.timeout_ms,
        "max_retries": dep.max_retries,
        "input_price_micros_per_m": dep.input_price_micros_per_m,
        "output_price_micros_per_m": dep.output_price_micros_per_m,
    }
    if dep.rpm is not None:
        out["rpm"] = dep.rpm
    if dep.tpm is not None:
        out["tpm"] = dep.tpm
    if dep.max_concurrency is not None:
        out["max_concurrency"] = dep.max_concurrency
    if dep.daily_budget_micros is not None:
        out["daily_budget_micros"] = dep.daily_budget_micros
    cooldown = _cooldown_dict(dep)
    if cooldown is not None:
        out["cooldown"] = cooldown
    if dep.data_classes:
        out["data_classes"] = sorted(set(dep.data_classes))
    return out


def route_json(
    route: ModelRoute,
    targets: list[ModelRouteTarget],
    deploy_by_id: dict[UUID, ModelDeployment],
) -> dict[str, Any]:
    deployment_ids: list[str] = []
    for target in sorted(targets, key=lambda t: (t.position, str(t.id))):
        if target.disabled_at is not None:
            continue
        dep = deploy_by_id.get(target.deployment_id)
        if dep is None or dep.disabled_at is not None:
            continue
        deployment_ids.append(str(target.deployment_id))
    if not deployment_ids:
        raise ValueError(f"route {route.id} has no enabled deployment targets")

    out: dict[str, Any] = {
        "id": str(route.id),
        "agent_id": str(route.agent_id),
        "environment": route.environment,
        "alias": route.alias,
        "strategy": route.strategy,
        "deployment_ids": deployment_ids,
        "enforcement": route.enforcement,
        "fallback_before_first_byte": route.fallback_before_first_byte,
        "max_attempts": route.max_attempts,
        "response_cache_enabled": route.response_cache_enabled,
    }
    if route.agent_version_id is not None:
        out["agent_version_id"] = str(route.agent_version_id)
    if route.permitted_regions:
        out["permitted_regions"] = sorted(set(route.permitted_regions))
    if route.data_classes:
        out["data_classes"] = sorted(set(route.data_classes))
    if route.response_cache_enabled and route.response_cache_ttl_seconds is not None:
        out["response_cache_ttl_seconds"] = route.response_cache_ttl_seconds
    return out


def binding_json(
    cred: WorkloadCredential,
    gen: WorkloadCredentialGeneration,
    org_id: UUID,
    project_id: UUID,
) -> dict[str, Any]:
    secret_hash = "sha256:" + gen.secret_digest.hex()
    out: dict[str, Any] = {
        "generation_id": str(gen.id),
        "secret_hash": secret_hash,
        "organization_id": str(org_id),
        "project_id": str(project_id),
        "environment": cred.environment,
        "modules": sorted(set(cred.modules)),
        "scopes": sorted(set(cred.scopes)),
        "allowed_model_patterns": sorted(set(cred.allowed_model_patterns)),
    }
    if cred.agent_id is not None:
        out["agent_id"] = str(cred.agent_id)
    if getattr(cred, "member_id", None) is not None:
        out["member_id"] = str(cred.member_id)
    if cred.expires_at is not None:
        out["expires_at"] = _iso_z(cred.expires_at)
    if cred.revoked_at is not None:
        out["revoked_at"] = _iso_z(cred.revoked_at)
    if gen.revoked_at is not None:
        out["revoked_at"] = _iso_z(gen.revoked_at)
    for key in ("rpm", "tpm", "max_concurrency", "daily_budget_micros"):
        value = getattr(cred, key)
        if value is not None:
            out[key] = value
    return out


def organization_limits_json() -> dict[str, Any] | None:
    limits = get_license().suite_modules["router"].limits
    if not limits:
        return None
    out: dict[str, Any] = {}
    for key in ("rpm", "tpm", "max_concurrency", "daily_budget_micros"):
        raw = limits.get(key)
        if raw is None:
            continue
        out[key] = raw
    return out or None


def build_unsigned_config(
    *,
    snapshot_id: UUID,
    org_id: UUID,
    project_id: UUID,
    key_id: str,
    issued_at: datetime,
    expires_at: datetime,
    deployments: list[ModelDeployment],
    routes: list[ModelRoute],
    targets_by_route: dict[UUID, list[ModelRouteTarget]],
    bindings: list[tuple[WorkloadCredential, WorkloadCredentialGeneration]],
) -> tuple[dict[str, Any], str]:
    deploy_by_id = {d.id: d for d in deployments}
    deploy_json = [deployment_json(d) for d in sorted(deployments, key=lambda d: str(d.id))]
    route_jsons: list[dict[str, Any]] = []
    for route in sorted(routes, key=lambda r: str(r.id)):
        route_jsons.append(route_json(route, targets_by_route.get(route.id, []), deploy_by_id))
    binding_jsons = [
        binding_json(cred, gen, org_id, project_id)
        for cred, gen in sorted(bindings, key=lambda row: str(row[1].id))
    ]

    rules_body = {
        "deployments": deploy_json,
        "routes": route_jsons,
        "workload_bindings": binding_jsons,
    }
    rules_digest = _digest_hex(_canonical_json(rules_body))

    body: dict[str, Any] = {
        "schema_revision": 1,
        "snapshot_id": str(snapshot_id),
        "organization_id": str(org_id),
        "project_id": str(project_id),
        "key_id": key_id,
        "issued_at": _iso_z(issued_at),
        "expires_at": _iso_z(expires_at),
        "rules_digest": rules_digest,
        "deployments": deploy_json,
        "routes": route_jsons,
        "workload_bindings": binding_jsons,
    }
    org_limits = organization_limits_json()
    if org_limits:
        body["organization_limits"] = org_limits
    return body, rules_digest


def validate_config_document(doc: dict[str, Any]) -> None:
    validator = _load_schema_validator()
    errors = sorted(validator.iter_errors(doc), key=lambda e: e.path)
    if errors:
        first = errors[0]
        raise ValueError(f"router config schema validation failed: {first.message}")


def sign_config_bytes(
    unsigned: dict[str, Any], signer: Signer | None = None
) -> tuple[bytes, str, str]:
    active = signer or build_signer()
    config_bytes = _canonical_json(unsigned)
    signature = active.sign(config_bytes)
    return config_bytes, signature, active.key_id


def compile_and_sign(
    *,
    org_id: UUID,
    project_id: UUID,
    issued_at: datetime,
    expires_at: datetime,
    deployments: list[ModelDeployment],
    routes: list[ModelRoute],
    targets_by_route: dict[UUID, list[ModelRouteTarget]],
    bindings: list[tuple[WorkloadCredential, WorkloadCredentialGeneration]],
    settings: Settings | None = None,
    signer: Signer | None = None,
) -> tuple[UUID, bytes, str, str, str, str, datetime, datetime]:
    _ = settings or get_settings()
    snapshot_id = uuid4()
    active = signer or build_signer()
    unsigned, rules_digest = build_unsigned_config(
        snapshot_id=snapshot_id,
        org_id=org_id,
        project_id=project_id,
        key_id=active.key_id,
        issued_at=issued_at,
        expires_at=expires_at,
        deployments=deployments,
        routes=routes,
        targets_by_route=targets_by_route,
        bindings=bindings,
    )
    validate_config_document(unsigned)
    config_bytes, signature, key_id = sign_config_bytes(unsigned, signer=active)
    if not active.verify(config_bytes, signature):
        raise ValueError("signature self-check failed")
    return (
        snapshot_id,
        config_bytes,
        rules_digest,
        signature,
        key_id,
        active.public_key_pem(),
        issued_at,
        expires_at,
    )


def deployment_out_cooldown(dep: ModelDeployment) -> CooldownPolicyIn | None:
    if dep.cooldown_failure_threshold is None:
        return None
    return CooldownPolicyIn(
        failure_threshold=dep.cooldown_failure_threshold,
        initial_cooldown_ms=dep.cooldown_initial_ms or 1,
        max_cooldown_ms=dep.cooldown_max_ms or 1,
    )
