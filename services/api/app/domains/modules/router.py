"""Suite module discovery (runtime-suite contract)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentPrincipal
from app.api.route import TransactionalRoute
from app.domains.modules import service
from app.domains.modules.schemas import ModulesManifestOut

router = APIRouter(route_class=TransactionalRoute)


@router.get(
    "",
    response_model=ModulesManifestOut,
    summary="Effective suite modules for this install",
)
async def list_modules(_: CurrentPrincipal) -> ModulesManifestOut:
    return service.build_effective_manifest()
