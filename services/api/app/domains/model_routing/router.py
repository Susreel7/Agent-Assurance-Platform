"""Model routing HTTP handlers."""

from __future__ import annotations

import base64
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response, status

from app.api.deps import CurrentPrincipal, Session, VerifiedOrg, WriteEnabled
from app.api.route import TransactionalRoute
from app.domains.model_routing import service
from app.domains.model_routing.schemas import (
    CatalogEntryCreate,
    CatalogEntryOut,
    CatalogPage,
    DeploymentCreate,
    DeploymentOut,
    DeploymentPage,
    DeploymentUpdate,
    GatewayConfigOut,
    GatewayLogIngest,
    ModelRoutingEvaluateRequest,
    ModelRoutingEvaluateResult,
    RouteCreate,
    RouteOut,
    RoutePage,
    RouteSimulateRequest,
    RouteSimulateResult,
    RouteUpdate,
    RoutingOverview,
    SnapshotCompileRequest,
    SnapshotOut,
)
from app.domains.modules.schemas import ModuleCapability, SuiteModuleId
from app.domains.modules.service import require_module_capability
from app.domains.operations import service as operations_svc

router = APIRouter(route_class=TransactionalRoute)

RouterConfigureDep = Annotated[
    None,
    Depends(require_module_capability(SuiteModuleId.ROUTER, ModuleCapability.CONFIGURE)),
]
RouterReadDep = Annotated[
    None,
    Depends(require_module_capability(SuiteModuleId.ROUTER, ModuleCapability.READ)),
]


def _gateway_signature_header(signature: str) -> str:
    """Gateway verifies detached ECDSA with standard base64."""
    pad = "=" * (-len(signature) % 4)
    raw = base64.urlsafe_b64decode(signature + pad)
    return base64.standard_b64encode(raw).decode()


@router.get("/catalogue/entries", response_model=CatalogPage, summary="List model catalogue")
async def list_catalogue(
    session: Session,
    org_id: VerifiedOrg,
    classification: Annotated[str | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=128)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> CatalogPage:
    return await service.list_catalog(
        session,
        org_id,
        classification=classification,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/catalogue/entries",
    response_model=CatalogEntryOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create tenant catalogue override",
)
async def create_catalogue_entry(
    payload: CatalogEntryCreate,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> CatalogEntryOut:
    return await service.create_catalog_entry(session, org_id, payload)


@router.post(
    "/-/evaluate",
    response_model=ModelRoutingEvaluateResult,
    summary="Pre-dispatch model routing decision for gateway",
)
async def evaluate_model_routing(
    payload: ModelRoutingEvaluateRequest,
    session: Session,
    org_id: VerifiedOrg,
) -> ModelRoutingEvaluateResult:
    try:
        return await service.evaluate_pre_dispatch(session, org_id, payload)
    except service.AgentContextError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get(
    "/agents/{agent_id}/gateway-config",
    response_model=GatewayConfigOut,
    summary="Emitted gateway configuration for an agent",
)
async def get_gateway_config(
    agent_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    agent_version_id: Annotated[UUID | None, Query()] = None,
) -> GatewayConfigOut:
    try:
        compiled = await service.compile_agent_model_policy(
            session, org_id, agent_id, agent_version_id
        )
    except service.AgentContextError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except service.ModelRoutingError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    config = service.build_litellm_config(compiled)
    gaps = service.verify_emitted_config(config.config)
    if gaps:
        config = config.model_copy(update={"fallback_access_enforced": False})
    return config


@router.post(
    "/gateway/logs",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Ingest gateway request log line",
)
async def ingest_gateway_log(
    payload: GatewayLogIngest,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
) -> None:
    await service.ingest_gateway_log(session, org_id, payload)


@router.get(
    "/overview",
    response_model=RoutingOverview,
    summary="Routing and residency console summary",
)
async def routing_overview(session: Session, org_id: VerifiedOrg) -> RoutingOverview:
    return await service.routing_overview(session, org_id)


@router.post(
    "/projects/{project_id}/deployments",
    response_model=DeploymentOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a router model deployment",
)
async def create_deployment(
    project_id: UUID,
    payload: DeploymentCreate,
    session: Session,
    org_id: VerifiedOrg,
    principal: CurrentPrincipal,
    _: WriteEnabled,
    __: RouterConfigureDep,
) -> DeploymentOut:
    try:
        return await service.create_deployment(
            session, org_id, project_id, payload, created_by=principal.actor_ref
        )
    except service.ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/projects/{project_id}/deployments",
    response_model=DeploymentPage,
    summary="List router model deployments",
)
async def list_deployments(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    _: RouterReadDep,
    include_disabled: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DeploymentPage:
    try:
        return await service.list_project_deployments(
            session,
            org_id,
            project_id,
            include_disabled=include_disabled,
            limit=limit,
            offset=offset,
        )
    except service.ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch(
    "/projects/{project_id}/deployments/{deployment_id}",
    response_model=DeploymentOut,
    summary="Update a router model deployment",
)
async def patch_deployment(
    project_id: UUID,
    deployment_id: UUID,
    payload: DeploymentUpdate,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
    __: RouterConfigureDep,
) -> DeploymentOut:
    try:
        return await service.update_deployment(session, org_id, project_id, deployment_id, payload)
    except service.ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.DeploymentNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/projects/{project_id}/deployments/{deployment_id}/disable",
    response_model=DeploymentOut,
    summary="Disable a router model deployment",
)
async def disable_deployment(
    project_id: UUID,
    deployment_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
    __: RouterConfigureDep,
) -> DeploymentOut:
    try:
        return await service.disable_deployment(session, org_id, project_id, deployment_id)
    except service.ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.DeploymentNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/projects/{project_id}/routes",
    response_model=RouteOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create a model route",
)
async def create_route(
    project_id: UUID,
    payload: RouteCreate,
    session: Session,
    org_id: VerifiedOrg,
    principal: CurrentPrincipal,
    _: WriteEnabled,
    __: RouterConfigureDep,
) -> RouteOut:
    try:
        return await service.create_route(
            session, org_id, project_id, payload, created_by=principal.actor_ref
        )
    except service.ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.InvalidReferenceError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get(
    "/projects/{project_id}/routes",
    response_model=RoutePage,
    summary="List model routes",
)
async def list_routes(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    _: RouterReadDep,
    include_disabled: Annotated[bool, Query()] = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> RoutePage:
    try:
        return await service.list_project_routes(
            session,
            org_id,
            project_id,
            include_disabled=include_disabled,
            limit=limit,
            offset=offset,
        )
    except service.ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch(
    "/projects/{project_id}/routes/{route_id}",
    response_model=RouteOut,
    summary="Update a model route",
)
async def patch_route(
    project_id: UUID,
    route_id: UUID,
    payload: RouteUpdate,
    session: Session,
    org_id: VerifiedOrg,
    _: WriteEnabled,
    __: RouterConfigureDep,
) -> RouteOut:
    try:
        return await service.update_route(session, org_id, project_id, route_id, payload)
    except service.ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.RouteNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.InvalidReferenceError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.post(
    "/projects/{project_id}/routes/{route_id}/simulate",
    response_model=RouteSimulateResult,
    summary="Simulate route target eligibility",
)
async def simulate_route(
    project_id: UUID,
    route_id: UUID,
    payload: RouteSimulateRequest,
    session: Session,
    org_id: VerifiedOrg,
    _: RouterReadDep,
) -> RouteSimulateResult:
    try:
        return await service.simulate_route(session, org_id, project_id, route_id, payload)
    except service.ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.RouteNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/projects/{project_id}/snapshots/compile",
    response_model=SnapshotOut,
    status_code=status.HTTP_201_CREATED,
    summary="Compile and sign a router configuration snapshot",
)
async def compile_snapshot(
    project_id: UUID,
    payload: SnapshotCompileRequest,
    session: Session,
    org_id: VerifiedOrg,
    principal: CurrentPrincipal,
    _: WriteEnabled,
    __: RouterConfigureDep,
) -> SnapshotOut:
    try:
        return await service.compile_project_snapshot(
            session,
            org_id,
            project_id,
            payload,
            compiled_by=principal.actor_ref,
        )
    except service.ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.RouterCompileError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc


@router.get(
    "/projects/{project_id}/snapshots/{snapshot_id}",
    response_model=SnapshotOut,
    summary="Fetch router snapshot metadata",
)
async def get_snapshot(
    project_id: UUID,
    snapshot_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    _: RouterReadDep,
) -> SnapshotOut:
    try:
        return await service.get_snapshot(session, org_id, project_id, snapshot_id)
    except service.ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.SnapshotNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get(
    "/projects/{project_id}/gateway-config",
    summary="Latest signed router configuration bytes for the gateway",
)
async def get_project_gateway_config(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    _: RouterReadDep,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
) -> Response:
    etag_hint = if_none_match
    try:
        config_bytes, meta = await service.get_gateway_config_snapshot(session, org_id, project_id)
    except service.ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.SnapshotNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    etag = f'"{meta.config_digest}"'
    if etag_hint == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})

    return Response(
        content=config_bytes,
        media_type="application/json",
        headers={
            "ETag": etag,
            "X-AAP-Config-Digest": meta.config_digest,
            "X-AAP-Rules-Digest": meta.rules_digest,
            "X-AAP-Config-Key-Id": meta.key_id,
            "X-AAP-Config-Signature": _gateway_signature_header(meta.signature),
            "X-AAP-Snapshot-Id": str(meta.snapshot_id),
        },
    )


@router.get(
    "/projects/{project_id}/snapshots/{snapshot_id}/config",
    summary="Exact signed configuration bytes for a snapshot",
)
async def get_snapshot_config(
    project_id: UUID,
    snapshot_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    _: RouterReadDep,
    header_if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
) -> Response:
    try:
        config_bytes, meta = await service.get_gateway_config_snapshot(
            session, org_id, project_id, snapshot_id=snapshot_id
        )
    except service.ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.SnapshotNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    etag = f'"{meta.config_digest}"'
    if header_if_none_match == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})

    return Response(
        content=config_bytes,
        media_type="application/json",
        headers={
            "ETag": etag,
            "X-AAP-Config-Digest": meta.config_digest,
            "X-AAP-Rules-Digest": meta.rules_digest,
            "X-AAP-Config-Key-Id": meta.key_id,
            "X-AAP-Config-Signature": _gateway_signature_header(meta.signature),
            "X-AAP-Snapshot-Id": str(meta.snapshot_id),
        },
    )


@router.get(
    "/projects/{project_id}/signing/public-key",
    summary="PEM public key for verifying router configuration signatures",
)
async def get_router_signing_public_key(
    project_id: UUID, session: Session, org_id: VerifiedOrg, _: RouterReadDep
) -> dict[str, str]:
    try:
        await service.require_project(session, org_id, project_id)
    except service.ProjectNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"public_key_pem": service.signing_public_key_pem()}


@router.post(
    "/runs/{run_id}/detect-drift",
    summary="Scan run steps for model routing drift (observation only)",
)
async def detect_run_drift(
    run_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
) -> dict[str, int]:
    try:
        scanned = await service.scan_run_for_model_drift(session, org_id, run_id)
    except operations_svc.RunNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return {"llm_steps_scanned": scanned}
