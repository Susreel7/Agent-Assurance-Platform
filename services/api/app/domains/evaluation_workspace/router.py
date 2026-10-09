"""Entitlement-aware human API for the evaluate workspace."""

from __future__ import annotations

from typing import Annotated, Any, NoReturn
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import Auth, Session, VerifiedOrg, WriteGuard
from app.api.route import TransactionalRoute
from app.domains.evaluation_workspace import service
from app.domains.evaluation_workspace.schemas import (
    AlertOut,
    AnnotationConsensusResponse,
    AnnotationItemCreate,
    AnnotationItemOut,
    AnnotationQueueCreate,
    AnnotationQueueOut,
    AttachmentDownloadOut,
    AttachmentUploadIn,
    AttachmentUploadOut,
    ClaimRequest,
    ClaimResponse,
    DatasetCreate,
    DatasetOut,
    DatasetRevisionCreate,
    DatasetRevisionOut,
    EvaluatorCreate,
    EvaluatorDryRunRequest,
    EvaluatorOut,
    EvaluatorRevisionOut,
    EvaluatorRevisionSummaryOut,
    ExampleSummaryOut,
    ExperimentAggregatesRefreshResponse,
    ExperimentCreate,
    ExperimentOut,
    ExperimentResultsResponse,
    ExportResponse,
    ExportToDatasetRequest,
    ExportToDatasetResponse,
    IdResponse,
    ImportRequest,
    ObserveWebhookEvent,
    OnlineRuleCreate,
    OnlineRuleEventJobResponse,
    OnlineRuleOut,
    PagedResponse,
    ReleaseGateCreate,
    ReleaseGateEvaluateRequest,
    ReleaseGateEvaluateResponse,
    ReleaseGateEvaluationOut,
    ReleaseGateOut,
    ScoreCorrection,
    ScoreCreate,
    ScoreDetailOut,
    ScoreOut,
    SubmissionRequest,
)
from app.domains.modules.schemas import ModuleCapability, SuiteModuleId
from app.domains.modules.service import require_module_capability
from app.domains.workload_identity import service as workload_service

router = APIRouter(route_class=TransactionalRoute)

EvaluateRead = Annotated[
    None,
    Depends(require_module_capability(SuiteModuleId.EVALUATE, ModuleCapability.READ)),
]
EvaluateConfigure = Annotated[
    None,
    Depends(require_module_capability(SuiteModuleId.EVALUATE, ModuleCapability.CONFIGURE)),
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


def _raise_evaluate(exc: Exception) -> NoReturn:
    if isinstance(exc, service.EvaluateRequestError):
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    raise HTTPException(status_code=503, detail="Evaluate workspace service unavailable") from exc


@router.get("/projects/{project_id}/datasets", response_model=PagedResponse[DatasetOut])
async def list_datasets(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
    q: Annotated[str | None, Query(max_length=256)] = None,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> PagedResponse[DatasetOut]:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.list_datasets(
            org_id, project_id, actor=_actor(auth), q=q, limit=limit, cursor=cursor
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get("/projects/{project_id}/datasets/{dataset_key}", response_model=DatasetOut)
async def get_dataset(
    project_id: UUID,
    dataset_key: str,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
) -> DatasetOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_dataset(
            org_id, project_id, actor=_actor(auth), dataset_key=dataset_key
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get(
    "/projects/{project_id}/datasets/{dataset_key}/revisions",
    response_model=PagedResponse[DatasetRevisionOut],
)
async def list_dataset_revisions(
    project_id: UUID,
    dataset_key: str,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> PagedResponse[DatasetRevisionOut]:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.list_dataset_revisions(
            org_id,
            project_id,
            actor=_actor(auth),
            dataset_key=dataset_key,
            limit=limit,
            cursor=cursor,
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get(
    "/projects/{project_id}/datasets/{dataset_key}/revisions/{revision_id}",
    response_model=DatasetRevisionOut,
)
async def get_dataset_revision(
    project_id: UUID,
    dataset_key: str,
    revision_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
) -> DatasetRevisionOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_dataset_revision(
            org_id,
            project_id,
            actor=_actor(auth),
            dataset_key=dataset_key,
            revision_id=revision_id,
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get(
    "/projects/{project_id}/datasets/{dataset_key}/revisions/{revision_id}/examples",
    response_model=PagedResponse[ExampleSummaryOut],
)
async def list_revision_examples(
    project_id: UUID,
    dataset_key: str,
    revision_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
    split: Annotated[str | None, Query(max_length=64)] = None,
    q: Annotated[str | None, Query(max_length=256)] = None,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> PagedResponse[ExampleSummaryOut]:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.list_revision_examples(
            org_id,
            project_id,
            actor=_actor(auth),
            dataset_key=dataset_key,
            revision_id=revision_id,
            split=split,
            q=q,
            limit=limit,
            cursor=cursor,
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get(
    "/projects/{project_id}/datasets/{dataset_key}/revisions/{revision_id}/examples/{example_id}",
    response_model=ExampleSummaryOut,
)
async def get_revision_example(
    project_id: UUID,
    dataset_key: str,
    revision_id: UUID,
    example_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
) -> ExampleSummaryOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_revision_example(
            org_id,
            project_id,
            actor=_actor(auth),
            dataset_key=dataset_key,
            revision_id=revision_id,
            example_id=example_id,
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post(
    "/projects/{project_id}/datasets",
    response_model=DatasetOut,
    status_code=201,
    dependencies=[WriteGuard],
)
async def create_dataset(
    project_id: UUID,
    payload: DatasetCreate,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateConfigure,
) -> DatasetOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.create_dataset(org_id, project_id, actor=_actor(auth), payload=payload)
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post(
    "/projects/{project_id}/datasets/{dataset_key}/revisions",
    response_model=DatasetRevisionOut,
    status_code=201,
    dependencies=[WriteGuard],
)
async def create_dataset_revision(
    project_id: UUID,
    dataset_key: str,
    payload: DatasetRevisionCreate,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateConfigure,
) -> DatasetRevisionOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.create_dataset_revision(
            org_id,
            project_id,
            actor=_actor(auth),
            dataset_key=dataset_key,
            payload=payload,
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post(
    "/projects/{project_id}/datasets/{dataset_key}/import",
    response_model=DatasetRevisionOut,
    status_code=201,
    dependencies=[WriteGuard],
)
async def import_dataset(
    project_id: UUID,
    dataset_key: str,
    payload: ImportRequest,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateConfigure,
) -> DatasetRevisionOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.import_dataset(
            org_id,
            project_id,
            actor=_actor(auth),
            dataset_key=dataset_key,
            payload=payload,
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get(
    "/projects/{project_id}/datasets/{dataset_key}/revisions/{revision_id}/export",
    response_model=ExportResponse,
)
async def export_dataset_revision(
    project_id: UUID,
    dataset_key: str,
    revision_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
    export_format: Annotated[str, Query(alias="format", pattern="^(jsonl|csv)$")] = "jsonl",
) -> ExportResponse:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.export_dataset_revision(
            org_id,
            project_id,
            actor=_actor(auth),
            dataset_key=dataset_key,
            revision_id=revision_id,
            export_format=export_format,
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post(
    "/projects/{project_id}/datasets/attachments/upload",
    response_model=AttachmentUploadOut,
    status_code=201,
    dependencies=[WriteGuard],
)
async def upload_attachment(
    project_id: UUID,
    payload: AttachmentUploadIn,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateConfigure,
) -> AttachmentUploadOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.upload_attachment(
            org_id, project_id, actor=_actor(auth), payload=payload
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get(
    "/projects/{project_id}/datasets/attachments/{object_ref_id}/download",
    response_model=AttachmentDownloadOut,
)
async def download_attachment(
    project_id: UUID,
    object_ref_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
    expires_at: Annotated[int, Query()],
    signature: Annotated[str, Query(min_length=1)],
) -> AttachmentDownloadOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.download_attachment(
            org_id,
            project_id,
            actor=_actor(auth),
            object_ref_id=object_ref_id,
            expires_at=expires_at,
            signature=signature,
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get("/projects/{project_id}/experiments", response_model=PagedResponse[ExperimentOut])
async def list_experiments(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
    q: Annotated[str | None, Query(max_length=256)] = None,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> PagedResponse[ExperimentOut]:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.list_experiments(
            org_id, project_id, actor=_actor(auth), q=q, limit=limit, cursor=cursor
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get(
    "/projects/{project_id}/experiments/by-key/{experiment_key}",
    response_model=ExperimentOut,
)
async def get_experiment_by_key(
    project_id: UUID,
    experiment_key: str,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
) -> ExperimentOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_experiment_by_key(
            org_id, project_id, actor=_actor(auth), experiment_key=experiment_key
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get("/projects/{project_id}/experiments/{experiment_id}", response_model=ExperimentOut)
async def get_experiment(
    project_id: UUID,
    experiment_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
) -> ExperimentOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_experiment(
            org_id, project_id, actor=_actor(auth), experiment_id=experiment_id
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post(
    "/projects/{project_id}/experiments",
    response_model=ExperimentOut,
    status_code=201,
    dependencies=[WriteGuard],
)
async def create_experiment(
    project_id: UUID,
    payload: ExperimentCreate,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateConfigure,
) -> ExperimentOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.create_experiment(
            org_id, project_id, actor=_actor(auth), payload=payload
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post(
    "/projects/{project_id}/experiments/{experiment_id}/start",
    response_model=ExperimentOut,
    dependencies=[WriteGuard],
)
async def start_experiment(
    project_id: UUID,
    experiment_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateConfigure,
) -> ExperimentOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.start_experiment(
            org_id, project_id, actor=_actor(auth), experiment_id=experiment_id
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post(
    "/projects/{project_id}/experiments/{experiment_id}/cancel",
    response_model=ExperimentOut,
    dependencies=[WriteGuard],
)
async def cancel_experiment(
    project_id: UUID,
    experiment_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateConfigure,
) -> ExperimentOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.cancel_experiment(
            org_id, project_id, actor=_actor(auth), experiment_id=experiment_id
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post(
    "/projects/{project_id}/experiments/{experiment_id}/retry",
    response_model=ExperimentOut,
    dependencies=[WriteGuard],
)
async def retry_experiment(
    project_id: UUID,
    experiment_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateConfigure,
) -> ExperimentOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.retry_experiment(
            org_id, project_id, actor=_actor(auth), experiment_id=experiment_id
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get(
    "/projects/{project_id}/experiments/{experiment_id}/results",
    response_model=ExperimentResultsResponse,
)
async def experiment_results(
    project_id: UUID,
    experiment_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
) -> ExperimentResultsResponse:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.experiment_results(
            org_id, project_id, actor=_actor(auth), experiment_id=experiment_id
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post(
    "/projects/{project_id}/experiments/{experiment_id}/aggregates/refresh",
    response_model=ExperimentAggregatesRefreshResponse,
    dependencies=[WriteGuard],
)
async def refresh_experiment_aggregates(
    project_id: UUID,
    experiment_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateConfigure,
) -> ExperimentAggregatesRefreshResponse:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.refresh_experiment_aggregates(
            org_id, project_id, actor=_actor(auth), experiment_id=experiment_id
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get("/projects/{project_id}/evaluators", response_model=PagedResponse[EvaluatorOut])
async def list_evaluators(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
    q: Annotated[str | None, Query(max_length=256)] = None,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> PagedResponse[EvaluatorOut]:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.list_evaluators(
            org_id, project_id, actor=_actor(auth), q=q, limit=limit, cursor=cursor
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get(
    "/projects/{project_id}/evaluators/{evaluator_key}",
    response_model=EvaluatorOut,
)
async def get_evaluator(
    project_id: UUID,
    evaluator_key: str,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
) -> EvaluatorOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_evaluator(
            org_id, project_id, actor=_actor(auth), evaluator_key=evaluator_key
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get(
    "/projects/{project_id}/evaluators/{evaluator_key}/revisions",
    response_model=PagedResponse[EvaluatorRevisionSummaryOut],
)
async def list_evaluator_revisions(
    project_id: UUID,
    evaluator_key: str,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> PagedResponse[EvaluatorRevisionSummaryOut]:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.list_evaluator_revisions(
            org_id,
            project_id,
            actor=_actor(auth),
            evaluator_key=evaluator_key,
            limit=limit,
            cursor=cursor,
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get(
    "/projects/{project_id}/evaluators/{evaluator_key}/revisions/{revision_id}",
    response_model=EvaluatorRevisionSummaryOut,
)
async def get_evaluator_revision(
    project_id: UUID,
    evaluator_key: str,
    revision_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
) -> EvaluatorRevisionSummaryOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_evaluator_revision(
            org_id,
            project_id,
            actor=_actor(auth),
            evaluator_key=evaluator_key,
            revision_id=revision_id,
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post(
    "/projects/{project_id}/evaluators",
    response_model=EvaluatorRevisionOut,
    status_code=201,
    dependencies=[WriteGuard],
)
async def create_evaluator(
    project_id: UUID,
    payload: EvaluatorCreate,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateConfigure,
) -> EvaluatorRevisionOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.create_evaluator(
            org_id, project_id, actor=_actor(auth), payload=payload
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post("/projects/{project_id}/evaluators/dry-run")
async def evaluator_dry_run(
    project_id: UUID,
    payload: EvaluatorDryRunRequest,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
) -> dict[str, Any]:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.evaluator_dry_run(
            org_id, project_id, actor=_actor(auth), payload=payload
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get("/projects/{project_id}/scores", response_model=PagedResponse[ScoreDetailOut])
async def list_scores(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
    target_type: Annotated[str | None, Query(max_length=64)] = None,
    target_id: Annotated[str | None, Query(max_length=256)] = None,
    name: Annotated[str | None, Query(max_length=128)] = None,
    source: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> PagedResponse[ScoreDetailOut]:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.list_scores(
            org_id,
            project_id,
            actor=_actor(auth),
            target_type=target_type,
            target_id=target_id,
            name=name,
            source=source,
            limit=limit,
            cursor=cursor,
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get("/projects/{project_id}/scores/{score_id}", response_model=ScoreDetailOut)
async def get_score(
    project_id: UUID,
    score_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
) -> ScoreDetailOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_score(org_id, project_id, actor=_actor(auth), score_id=score_id)
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post(
    "/projects/{project_id}/scores",
    response_model=ScoreOut,
    status_code=201,
    dependencies=[WriteGuard],
)
async def create_score(
    project_id: UUID,
    payload: ScoreCreate,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateConfigure,
) -> ScoreOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.create_score(org_id, project_id, actor=_actor(auth), payload=payload)
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post(
    "/projects/{project_id}/scores/{score_id}/corrections",
    response_model=ScoreOut,
    status_code=201,
    dependencies=[WriteGuard],
)
async def correct_score(
    project_id: UUID,
    score_id: UUID,
    payload: ScoreCorrection,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateConfigure,
) -> ScoreOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.correct_score(
            org_id,
            project_id,
            actor=_actor(auth),
            score_id=score_id,
            payload=payload,
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get(
    "/projects/{project_id}/online-rules/alerts",
    response_model=PagedResponse[AlertOut],
)
async def list_online_alerts(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
    status: Annotated[str | None, Query(max_length=32)] = None,
    rule_id: UUID | None = None,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> PagedResponse[AlertOut]:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.list_online_alerts(
            org_id,
            project_id,
            actor=_actor(auth),
            status=status,
            rule_id=rule_id,
            limit=limit,
            cursor=cursor,
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get(
    "/projects/{project_id}/online-rules/alerts/{alert_id}",
    response_model=AlertOut,
)
async def get_online_alert(
    project_id: UUID,
    alert_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
) -> AlertOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_online_alert(
            org_id, project_id, actor=_actor(auth), alert_id=alert_id
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post(
    "/projects/{project_id}/online-rules/alerts/{alert_id}/retry",
    response_model=AlertOut,
    dependencies=[WriteGuard],
)
async def retry_online_alert(
    project_id: UUID,
    alert_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateConfigure,
) -> AlertOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.retry_online_alert(
            org_id, project_id, actor=_actor(auth), alert_id=alert_id
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post(
    "/projects/{project_id}/online-rules/alerts/{alert_id}/acknowledge",
    response_model=AlertOut,
    dependencies=[WriteGuard],
)
async def acknowledge_online_alert(
    project_id: UUID,
    alert_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateConfigure,
) -> AlertOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.acknowledge_online_alert(
            org_id, project_id, actor=_actor(auth), alert_id=alert_id
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get(
    "/projects/{project_id}/online-rules",
    response_model=PagedResponse[OnlineRuleOut],
)
async def list_online_rules(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> PagedResponse[OnlineRuleOut]:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.list_online_rules(
            org_id, project_id, actor=_actor(auth), limit=limit, cursor=cursor
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get(
    "/projects/{project_id}/online-rules/{rule_id}",
    response_model=OnlineRuleOut,
)
async def get_online_rule(
    project_id: UUID,
    rule_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
) -> OnlineRuleOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_online_rule(
            org_id, project_id, actor=_actor(auth), rule_id=rule_id
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post(
    "/projects/{project_id}/online-rules",
    response_model=IdResponse,
    status_code=201,
    dependencies=[WriteGuard],
)
async def create_online_rule(
    project_id: UUID,
    payload: OnlineRuleCreate,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateConfigure,
) -> IdResponse:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.create_online_rule(
            org_id, project_id, actor=_actor(auth), payload=payload
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post(
    "/projects/{project_id}/online-rules/{rule_id}/events",
    response_model=OnlineRuleEventJobResponse,
    status_code=202,
    dependencies=[WriteGuard],
)
async def ingest_online_rule_event(
    project_id: UUID,
    rule_id: UUID,
    event: ObserveWebhookEvent,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateConfigure,
) -> OnlineRuleEventJobResponse:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.ingest_online_rule_event(
            org_id,
            project_id,
            actor=_actor(auth),
            rule_id=rule_id,
            event=event,
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get(
    "/projects/{project_id}/annotation-queues/items",
    response_model=PagedResponse[AnnotationItemOut],
)
async def list_annotation_items(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
    queue_id: UUID | None = None,
    status: Annotated[str | None, Query(max_length=32)] = None,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> PagedResponse[AnnotationItemOut]:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.list_annotation_items(
            org_id,
            project_id,
            actor=_actor(auth),
            queue_id=queue_id,
            status=status,
            limit=limit,
            cursor=cursor,
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get(
    "/projects/{project_id}/annotation-queues/items/{item_id}",
    response_model=AnnotationItemOut,
)
async def get_annotation_item(
    project_id: UUID,
    item_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
) -> AnnotationItemOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_annotation_item(
            org_id, project_id, actor=_actor(auth), item_id=item_id
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get(
    "/projects/{project_id}/annotation-queues",
    response_model=PagedResponse[AnnotationQueueOut],
)
async def list_annotation_queues(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> PagedResponse[AnnotationQueueOut]:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.list_annotation_queues(
            org_id, project_id, actor=_actor(auth), limit=limit, cursor=cursor
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get(
    "/projects/{project_id}/annotation-queues/{queue_id}",
    response_model=AnnotationQueueOut,
)
async def get_annotation_queue(
    project_id: UUID,
    queue_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
) -> AnnotationQueueOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_annotation_queue(
            org_id, project_id, actor=_actor(auth), queue_id=queue_id
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get(
    "/projects/{project_id}/annotation-queues/{queue_id}/items",
    response_model=PagedResponse[AnnotationItemOut],
)
async def list_queue_annotation_items(
    project_id: UUID,
    queue_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
    status: Annotated[str | None, Query(max_length=32)] = None,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> PagedResponse[AnnotationItemOut]:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.list_queue_annotation_items(
            org_id,
            project_id,
            actor=_actor(auth),
            queue_id=queue_id,
            status=status,
            limit=limit,
            cursor=cursor,
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post(
    "/projects/{project_id}/annotation-queues",
    response_model=IdResponse,
    status_code=201,
    dependencies=[WriteGuard],
)
async def create_annotation_queue(
    project_id: UUID,
    payload: AnnotationQueueCreate,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateConfigure,
) -> IdResponse:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.create_annotation_queue(
            org_id, project_id, actor=_actor(auth), payload=payload
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post(
    "/projects/{project_id}/annotation-queues/{queue_id}/items",
    response_model=IdResponse,
    status_code=201,
    dependencies=[WriteGuard],
)
async def add_annotation_item(
    project_id: UUID,
    queue_id: UUID,
    payload: AnnotationItemCreate,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateConfigure,
) -> IdResponse:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.add_annotation_item(
            org_id,
            project_id,
            actor=_actor(auth),
            queue_id=queue_id,
            payload=payload,
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post(
    "/projects/{project_id}/annotation-queues/items/{item_id}/claim",
    response_model=ClaimResponse,
    dependencies=[WriteGuard],
)
async def claim_annotation_item(
    project_id: UUID,
    item_id: UUID,
    payload: ClaimRequest,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateConfigure,
) -> ClaimResponse:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.claim_annotation_item(
            org_id,
            project_id,
            actor=_actor(auth),
            item_id=item_id,
            payload=payload,
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post(
    "/projects/{project_id}/annotation-queues/items/{item_id}/submissions",
    response_model=IdResponse,
    status_code=201,
    dependencies=[WriteGuard],
)
async def submit_annotation(
    project_id: UUID,
    item_id: UUID,
    payload: SubmissionRequest,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateConfigure,
) -> IdResponse:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.submit_annotation(
            org_id,
            project_id,
            actor=_actor(auth),
            item_id=item_id,
            payload=payload,
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post(
    "/projects/{project_id}/annotation-queues/items/{item_id}/skip",
    response_model=IdResponse,
    status_code=201,
    dependencies=[WriteGuard],
)
async def skip_annotation_item(
    project_id: UUID,
    item_id: UUID,
    payload: ClaimRequest,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateConfigure,
) -> IdResponse:
    await _project_exists(session, org_id, project_id)
    skip_payload = SubmissionRequest(
        assignee=payload.assignee,
        action="skip",
        scores={},
        comments="",
        rubric_version=1,
    )
    try:
        return await service.submit_annotation(
            org_id,
            project_id,
            actor=_actor(auth),
            item_id=item_id,
            payload=skip_payload,
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get(
    "/projects/{project_id}/annotation-queues/items/{item_id}/consensus",
    response_model=AnnotationConsensusResponse,
)
async def annotation_consensus(
    project_id: UUID,
    item_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
) -> AnnotationConsensusResponse:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.annotation_consensus(
            org_id, project_id, actor=_actor(auth), item_id=item_id
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post(
    "/projects/{project_id}/annotation-queues/items/{item_id}/export-to-dataset",
    response_model=ExportToDatasetResponse,
    dependencies=[WriteGuard],
)
async def export_annotation_to_dataset(
    project_id: UUID,
    item_id: UUID,
    payload: ExportToDatasetRequest,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateConfigure,
) -> ExportToDatasetResponse:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.export_annotation_to_dataset(
            org_id,
            project_id,
            actor=_actor(auth),
            item_id=item_id,
            payload=payload,
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get(
    "/projects/{project_id}/release-gates",
    response_model=PagedResponse[ReleaseGateOut],
)
async def list_release_gates(
    project_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> PagedResponse[ReleaseGateOut]:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.list_release_gates(
            org_id, project_id, actor=_actor(auth), limit=limit, cursor=cursor
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get(
    "/projects/{project_id}/release-gates/{gate_id}",
    response_model=ReleaseGateOut,
)
async def get_release_gate(
    project_id: UUID,
    gate_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
) -> ReleaseGateOut:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.get_release_gate(
            org_id, project_id, actor=_actor(auth), gate_id=gate_id
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.get(
    "/projects/{project_id}/release-gates/{gate_id}/evaluations",
    response_model=PagedResponse[ReleaseGateEvaluationOut],
)
async def list_release_gate_evaluations(
    project_id: UUID,
    gate_id: UUID,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateRead,
    limit: Annotated[int | None, Query(ge=1, le=500)] = None,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
) -> PagedResponse[ReleaseGateEvaluationOut]:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.list_release_gate_evaluations(
            org_id,
            project_id,
            actor=_actor(auth),
            gate_id=gate_id,
            limit=limit,
            cursor=cursor,
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post(
    "/projects/{project_id}/release-gates",
    response_model=IdResponse,
    status_code=201,
    dependencies=[WriteGuard],
)
async def create_release_gate(
    project_id: UUID,
    payload: ReleaseGateCreate,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateConfigure,
) -> IdResponse:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.create_release_gate(
            org_id, project_id, actor=_actor(auth), payload=payload
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)


@router.post(
    "/projects/{project_id}/release-gates/{gate_id}/evaluate",
    response_model=ReleaseGateEvaluateResponse,
    dependencies=[WriteGuard],
)
async def evaluate_release_gate(
    project_id: UUID,
    gate_id: UUID,
    payload: ReleaseGateEvaluateRequest,
    session: Session,
    org_id: VerifiedOrg,
    auth: Auth,
    _: EvaluateConfigure,
) -> ReleaseGateEvaluateResponse:
    await _project_exists(session, org_id, project_id)
    try:
        return await service.evaluate_release_gate(
            org_id,
            project_id,
            actor=_actor(auth),
            gate_id=gate_id,
            payload=payload,
        )
    except (service.EvaluateUnavailableError, service.EvaluateRequestError) as exc:
        _raise_evaluate(exc)
