"""Entitlement-aware human API for the prompt artifact workspace."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse, StreamingResponse

from app.api.deps import Auth, Session, VerifiedOrg, WriteGuard
from app.api.route import TransactionalRoute
from app.config import get_settings
from app.domains.artifact_workspace import service
from app.domains.artifact_workspace.schemas import (
    ArtifactCreate,
    ArtifactListResponse,
    ArtifactOut,
    AuditListResponse,
    CompareLabelsRequest,
    CompareRevisionsRequest,
    CompareRevisionsResponse,
    DiffRequest,
    DiffResponse,
    LabelHistoryResponse,
    LabelOut,
    PlaygroundCancelResponse,
    PlaygroundRunRequest,
    PlaygroundRunResponse,
    PlaygroundRunStatusOut,
    PromoteLabelRequest,
    RevisionCreate,
    RevisionDetailOut,
    RevisionListResponse,
    RollbackRequest,
    RuntimeArtifactResponse,
)
from app.domains.modules.schemas import ModuleCapability, SuiteModuleId
from app.domains.modules.service import require_module_capability
from app.domains.workload_identity import service as workload_service

router = APIRouter(route_class=TransactionalRoute)

PromptRead = Annotated[
    None,
    Depends(require_module_capability(SuiteModuleId.PROMPT, ModuleCapability.READ)),
]
PromptConfigure = Annotated[
    None,
    Depends(require_module_capability(SuiteModuleId.PROMPT, ModuleCapability.CONFIGURE)),
]


def _actor(auth: Auth) -> str:
    if auth.principal.email:
        return auth.principal.email
    return auth.principal.subject


async def _project_exists(session: Session, org_id: UUID, project_id: UUID) -> None:
    try:
        await workload_service.get_project(session, org_id, project_id)
    except workload_service.ProjectNotFoundError as exc:
        raise HTTPException(status_code=404, detail="project not found") from exc


def _raise_prompt(exc: Exception) -> NoReturn:
    if isinstance(exc, service.PromptRequestError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    raise HTTPException(status_code=503, detail="Prompt workspace service unavailable") from exc


def _workload_header(value: str | None) -> str | None:
    if value and value.lower().startswith("bearer "):
        return value
    configured = get_settings().runtime_workload_bearer
    if configured:
        return f"Bearer {configured}"
    return None


@router.get(
    "/projects/{project_id}/runtime/read/artifacts/{artifact_key}",
    response_model=RuntimeArtifactResponse,
)
async def read_runtime_artifact(
    project_id: UUID,
    artifact_key: str,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: PromptRead,
    label: Annotated[str | None, Query(max_length=64)] = None,
    revision_id: UUID | None = None,
    pin_revision_id: UUID | None = None,
    if_none_match: Annotated[str | None, Header(alias="If-None-Match")] = None,
) -> RuntimeArtifactResponse | Response:
    await _project_exists(session, org_id, project_id)
    try:
        result = await service.read_runtime_artifact(
            org_id,
            project_id,
            actor=_actor(auth),
            artifact_key=artifact_key,
            label=label,
            revision_id=revision_id,
            pin_revision_id=pin_revision_id,
            if_none_match=if_none_match,
        )
    except (service.PromptUnavailableError, service.PromptRequestError) as exc:
        _raise_prompt(exc)
    if result.status_code == 304:
        return Response(status_code=304, headers=result.headers)
    assert result.body is not None
    return JSONResponse(
        content=result.body.model_dump(mode="json"),
        headers=result.headers,
    )


@router.get("/projects/{project_id}/artifacts", response_model=ArtifactListResponse)
async def list_artifacts(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: PromptRead,
    kind: Annotated[str | None, Query(max_length=32)] = None,
    query: Annotated[str | None, Query(max_length=256)] = None,
    label: Annotated[str | None, Query(max_length=64)] = None,
    cursor: Annotated[str | None, Query(max_length=256)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> ArtifactListResponse:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.list_artifacts(
            org_id,
            project_id,
            actor=_actor(auth),
            kind=kind,
            query=query,
            label=label,
            cursor=cursor,
            limit=limit,
        )
    except (service.PromptUnavailableError, service.PromptRequestError) as exc:
        _raise_prompt(exc)


@router.post(
    "/projects/{project_id}/artifacts",
    response_model=ArtifactOut,
    status_code=201,
    dependencies=[WriteGuard],
)
async def create_artifact(
    project_id: UUID,
    payload: ArtifactCreate,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: PromptConfigure,
) -> ArtifactOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.create_artifact(
            org_id, project_id, actor=_actor(auth), payload=payload
        )
    except (service.PromptUnavailableError, service.PromptRequestError) as exc:
        _raise_prompt(exc)


@router.get("/projects/{project_id}/artifacts/{artifact_key}", response_model=ArtifactOut)
async def get_artifact(
    project_id: UUID,
    artifact_key: str,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: PromptRead,
) -> ArtifactOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_artifact(
            org_id, project_id, actor=_actor(auth), artifact_key=artifact_key
        )
    except (service.PromptUnavailableError, service.PromptRequestError) as exc:
        _raise_prompt(exc)


@router.post(
    "/projects/{project_id}/artifacts/{artifact_key}/revisions",
    response_model=RevisionDetailOut,
    status_code=201,
    dependencies=[WriteGuard],
)
async def create_revision(
    project_id: UUID,
    artifact_key: str,
    payload: RevisionCreate,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: PromptConfigure,
) -> RevisionDetailOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.create_revision(
            org_id,
            project_id,
            actor=_actor(auth),
            artifact_key=artifact_key,
            payload=payload,
        )
    except (service.PromptUnavailableError, service.PromptRequestError) as exc:
        _raise_prompt(exc)


@router.get(
    "/projects/{project_id}/artifacts/{artifact_key}/revisions",
    response_model=RevisionListResponse,
)
async def list_revisions(
    project_id: UUID,
    artifact_key: str,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: PromptRead,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> RevisionListResponse:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.list_revisions(
            org_id,
            project_id,
            actor=_actor(auth),
            artifact_key=artifact_key,
            limit=limit,
        )
    except (service.PromptUnavailableError, service.PromptRequestError) as exc:
        _raise_prompt(exc)


@router.get(
    "/projects/{project_id}/artifacts/{artifact_key}/revisions/{revision_id}",
    response_model=RevisionDetailOut,
)
async def get_revision(
    project_id: UUID,
    artifact_key: str,
    revision_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: PromptRead,
) -> RevisionDetailOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_revision(
            org_id,
            project_id,
            actor=_actor(auth),
            artifact_key=artifact_key,
            revision_id=revision_id,
        )
    except (service.PromptUnavailableError, service.PromptRequestError) as exc:
        _raise_prompt(exc)


@router.post(
    "/projects/{project_id}/artifacts/{artifact_key}/revisions:diff",
    response_model=DiffResponse,
)
async def diff_revisions(
    project_id: UUID,
    artifact_key: str,
    payload: DiffRequest,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: PromptRead,
) -> DiffResponse:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.diff_revisions(
            org_id,
            project_id,
            actor=_actor(auth),
            artifact_key=artifact_key,
            payload=payload,
        )
    except (service.PromptUnavailableError, service.PromptRequestError) as exc:
        _raise_prompt(exc)


@router.post(
    "/projects/{project_id}/artifacts/{artifact_key}/revisions:rollback",
    response_model=RevisionDetailOut,
    status_code=201,
    dependencies=[WriteGuard],
)
async def rollback_revision(
    project_id: UUID,
    artifact_key: str,
    payload: RollbackRequest,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: PromptConfigure,
) -> RevisionDetailOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.rollback_revision(
            org_id,
            project_id,
            actor=_actor(auth),
            artifact_key=artifact_key,
            payload=payload,
        )
    except (service.PromptUnavailableError, service.PromptRequestError) as exc:
        _raise_prompt(exc)


@router.post(
    "/projects/{project_id}/artifacts/{artifact_key}/revisions:compare",
    response_model=CompareRevisionsResponse,
)
async def compare_revisions(
    project_id: UUID,
    artifact_key: str,
    payload: CompareRevisionsRequest,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: PromptRead,
) -> CompareRevisionsResponse:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.compare_revisions(
            org_id,
            project_id,
            actor=_actor(auth),
            artifact_key=artifact_key,
            payload=payload,
        )
    except (service.PromptUnavailableError, service.PromptRequestError) as exc:
        _raise_prompt(exc)


@router.post(
    "/projects/{project_id}/artifacts/{artifact_key}/labels:promote",
    response_model=LabelOut,
    dependencies=[WriteGuard],
)
async def promote_label(
    project_id: UUID,
    artifact_key: str,
    payload: PromoteLabelRequest,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: PromptConfigure,
) -> LabelOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.promote_label(
            org_id,
            project_id,
            actor=_actor(auth),
            artifact_key=artifact_key,
            payload=payload,
        )
    except (service.PromptUnavailableError, service.PromptRequestError) as exc:
        _raise_prompt(exc)


@router.get(
    "/projects/{project_id}/artifacts/{artifact_key}/labels/{label_name}",
    response_model=LabelOut,
)
async def get_label(
    project_id: UUID,
    artifact_key: str,
    label_name: str,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: PromptRead,
) -> LabelOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_label(
            org_id,
            project_id,
            actor=_actor(auth),
            artifact_key=artifact_key,
            label_name=label_name,
        )
    except (service.PromptUnavailableError, service.PromptRequestError) as exc:
        _raise_prompt(exc)


@router.get(
    "/projects/{project_id}/artifacts/{artifact_key}/labels/{label_name}/history",
    response_model=LabelHistoryResponse,
)
async def label_history(
    project_id: UUID,
    artifact_key: str,
    label_name: str,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: PromptRead,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> LabelHistoryResponse:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.label_history(
            org_id,
            project_id,
            actor=_actor(auth),
            artifact_key=artifact_key,
            label_name=label_name,
            limit=limit,
        )
    except (service.PromptUnavailableError, service.PromptRequestError) as exc:
        _raise_prompt(exc)


@router.post("/projects/{project_id}/artifacts/{artifact_key}/labels:compare")
async def compare_labels(
    project_id: UUID,
    artifact_key: str,
    payload: CompareLabelsRequest,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: PromptRead,
) -> dict[str, object]:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.compare_labels(
            org_id,
            project_id,
            actor=_actor(auth),
            artifact_key=artifact_key,
            payload=payload,
        )
    except (service.PromptUnavailableError, service.PromptRequestError) as exc:
        _raise_prompt(exc)


@router.post(
    "/projects/{project_id}/playground/runs",
    status_code=201,
    response_model=None,
    dependencies=[WriteGuard],
)
async def create_playground_run(
    project_id: UUID,
    payload: PlaygroundRunRequest,
    request: Request,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: PromptConfigure,
    x_workload_authorization: Annotated[
        str | None, Header(alias="X-Workload-Authorization")
    ] = None,
) -> PlaygroundRunResponse | StreamingResponse:
    await _project_exists(session, org_id, project_id)
    workload = _workload_header(x_workload_authorization)
    try:
        if payload.stream:
            return StreamingResponse(
                service.stream_playground_run(
                    org_id,
                    project_id,
                    actor=_actor(auth),
                    payload=payload,
                    workload_authorization=workload,
                    disconnect=request.is_disconnected,
                ),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        return await service.run_playground_sync(
            org_id,
            project_id,
            actor=_actor(auth),
            payload=payload,
            workload_authorization=workload,
        )
    except (service.PromptUnavailableError, service.PromptRequestError) as exc:
        _raise_prompt(exc)


@router.get(
    "/projects/{project_id}/playground/runs/{run_id}",
    response_model=PlaygroundRunStatusOut,
)
async def get_playground_run(
    project_id: UUID,
    run_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: PromptRead,
) -> PlaygroundRunStatusOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.playground_run_status(
            org_id, project_id, actor=_actor(auth), run_id=run_id
        )
    except (service.PromptUnavailableError, service.PromptRequestError) as exc:
        _raise_prompt(exc)


@router.post(
    "/projects/{project_id}/playground/runs/{run_id}:cancel",
    response_model=PlaygroundCancelResponse,
    dependencies=[WriteGuard],
)
async def cancel_playground_run(
    project_id: UUID,
    run_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: PromptConfigure,
) -> PlaygroundCancelResponse:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.cancel_playground_run(
            org_id, project_id, actor=_actor(auth), run_id=run_id
        )
    except (service.PromptUnavailableError, service.PromptRequestError) as exc:
        _raise_prompt(exc)


@router.post(
    "/projects/{project_id}/playground/runs/{run_id}:replay",
    response_model=PlaygroundRunResponse,
    status_code=201,
    dependencies=[WriteGuard],
)
async def replay_playground_run(
    project_id: UUID,
    run_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: PromptConfigure,
    x_workload_authorization: Annotated[
        str | None, Header(alias="X-Workload-Authorization")
    ] = None,
) -> PlaygroundRunResponse:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.replay_playground_run(
            org_id,
            project_id,
            actor=_actor(auth),
            run_id=run_id,
            workload_authorization=_workload_header(x_workload_authorization),
        )
    except (service.PromptUnavailableError, service.PromptRequestError) as exc:
        _raise_prompt(exc)


@router.get("/projects/{project_id}/audit", response_model=AuditListResponse)
async def list_audit(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: PromptRead,
    resource_type: Annotated[str | None, Query(max_length=64)] = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    audit_actor: Annotated[str | None, Query(alias="actor", max_length=256)] = None,
    since: datetime | None = None,
    until: datetime | None = None,
    cursor: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 50,
) -> AuditListResponse:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.list_audit(
            org_id,
            project_id,
            actor=_actor(auth),
            resource_type=resource_type,
            action=action,
            audit_actor=audit_actor,
            since=since,
            until=until,
            cursor=cursor,
            limit=limit,
        )
    except (service.PromptUnavailableError, service.PromptRequestError) as exc:
        _raise_prompt(exc)


@router.get("/projects/{project_id}/audit/export")
async def export_audit(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: PromptRead,
    resource_type: Annotated[str | None, Query(max_length=64)] = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    audit_actor: Annotated[str | None, Query(alias="actor", max_length=256)] = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: Annotated[int, Query(ge=1, le=5000)] = 500,
) -> PlainTextResponse:
    await _project_exists(session, org_id, project_id)
    try:
        body = await service.export_audit(
            org_id,
            project_id,
            actor=_actor(auth),
            resource_type=resource_type,
            action=action,
            audit_actor=audit_actor,
            since=since,
            until=until,
            limit=limit,
        )
        return PlainTextResponse(body, media_type="application/x-ndjson")
    except (service.PromptUnavailableError, service.PromptRequestError) as exc:
        _raise_prompt(exc)
