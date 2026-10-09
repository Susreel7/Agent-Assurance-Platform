"""Effective suite module manifest and reusable access checks."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException, status

from app.domains.modules.schemas import (
    MODULE_BASE_PATHS,
    SUITE_MODULE_IDS,
    ModuleAccessOut,
    ModuleCapability,
    ModulesManifestOut,
    SuiteModuleOut,
)
from app.licensing import (
    License,
    ModuleAccess,
    get_license,
    suite_module_access,
)


class ModuleNotEntitledError(Exception):
    pass


def _canonical_manifest_body(modules: dict[str, SuiteModuleOut]) -> dict[str, Any]:
    """Stable JSON-serialisable body used for ``revision`` (excludes the revision field)."""
    ordered: dict[str, Any] = {}
    for module_id in SUITE_MODULE_IDS:
        entry = modules[module_id]
        ordered[module_id] = {
            "enabled": entry.enabled,
            "base_path": entry.base_path,
            "limits": entry.limits,
            "access": entry.access.model_dump(),
        }
    return ordered


def manifest_revision(modules: dict[str, SuiteModuleOut]) -> str:
    body = _canonical_manifest_body(modules)
    digest = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"sha256:{digest}"


def _access_out(access: ModuleAccess) -> ModuleAccessOut:
    return ModuleAccessOut(
        read=access.read,
        configure=access.configure,
        ingest=access.ingest,
        infer=access.infer,
    )


def build_effective_manifest(lic: License | None = None) -> ModulesManifestOut:
    active = lic or get_license()
    modules: dict[str, SuiteModuleOut] = {}
    for module_id in SUITE_MODULE_IDS:
        ent = active.suite_modules[module_id]
        access = suite_module_access(active, module_id)
        modules[module_id] = SuiteModuleOut(
            enabled=ent.enabled,
            base_path=MODULE_BASE_PATHS[module_id],
            limits=dict(ent.limits),
            access=_access_out(access),
        )
    return ModulesManifestOut(revision=manifest_revision(modules), modules=modules)


def assert_module_capability(module_id: str, capability: ModuleCapability) -> None:
    if module_id not in SUITE_MODULE_IDS:
        raise ModuleNotEntitledError(f"unknown suite module {module_id!r}")
    lic = get_license()
    access = suite_module_access(lic, module_id)
    allowed = {
        ModuleCapability.READ: access.read,
        ModuleCapability.CONFIGURE: access.configure,
        ModuleCapability.INGEST: access.ingest,
        ModuleCapability.INFER: access.infer,
    }[capability]
    if not allowed:
        raise ModuleNotEntitledError("module_not_entitled")


def require_module_capability(
    module_id: str,
    capability: ModuleCapability,
) -> Callable[[], Awaitable[None]]:
    """FastAPI dependency factory for other domain routers."""

    async def _dependency() -> None:
        try:
            assert_module_capability(module_id, capability)
        except ModuleNotEntitledError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            ) from exc

    return _dependency


def require_entitled_module(module_id: str) -> Callable[[], Awaitable[None]]:
    """Module must be signed on in the licence (ignores grace — use capability for that)."""

    async def _dependency() -> None:
        if module_id not in SUITE_MODULE_IDS:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="module_not_entitled",
            )
        lic = get_license()
        if not lic.suite_modules[module_id].enabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="module_not_entitled",
            )

    return _dependency
