"""Control-plane client for the independently deployed evaluate workspace service."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, cast
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel

from app.config import get_settings
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
    PageMeta,
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

_client_factory: Callable[[], httpx.AsyncClient] | None = None


class EvaluateUnavailableError(Exception):
    pass


class EvaluateRequestError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code


def _connection() -> tuple[str, str, float]:
    settings = get_settings()
    if not settings.evaluate_service_url or not settings.evaluate_internal_service_token:
        raise EvaluateUnavailableError("Evaluate workspace service is not configured")
    return (
        settings.evaluate_service_url.rstrip("/"),
        settings.evaluate_internal_service_token,
        settings.evaluate_service_timeout_seconds,
    )


def internal_headers(*, org_id: UUID, project_id: UUID, actor: str) -> dict[str, str]:
    _, token, _ = _connection()
    return {
        "Authorization": f"Bearer {token}",
        "X-Organization-Id": str(org_id),
        "X-Project-Id": str(project_id),
        "X-Actor": actor,
    }


def _safe_detail(response: httpx.Response) -> str:
    if response.status_code >= 500:
        return "Evaluate workspace request failed"
    try:
        body = response.json()
        if isinstance(body, dict):
            detail = body.get("detail")
            if isinstance(detail, dict) and "message" in detail:
                return str(detail["message"])
            if isinstance(detail, str):
                return detail
            if "message" in body:
                return str(body["message"])
    except (ValueError, TypeError):
        pass
    if response.status_code == 404:
        return "Evaluate resource not found"
    if response.status_code == 403:
        return "Evaluate workspace refused the request"
    return "Evaluate workspace request failed"


def _project_prefix(org_id: UUID, project_id: UUID) -> str:
    return f"/v1/orgs/{org_id}/projects/{project_id}"


def _open_client() -> httpx.AsyncClient:
    if _client_factory is not None:
        return _client_factory()
    _, _, timeout = _connection()
    return httpx.AsyncClient(timeout=timeout)


async def _request_json[T: BaseModel](
    method: str,
    path: str,
    *,
    org_id: UUID,
    project_id: UUID,
    actor: str,
    response_model: type[T],
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | BaseModel | None = None,
) -> T:
    base_url, _, _ = _connection()
    headers = internal_headers(org_id=org_id, project_id=project_id, actor=actor)
    payload: dict[str, Any] | None = None
    if isinstance(json_body, BaseModel):
        payload = json_body.model_dump(mode="json")
    elif json_body is not None:
        payload = json_body
    try:
        async with _open_client() as client:
            response = await client.request(
                method,
                f"{base_url}{path}",
                params=params,
                json=payload,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise EvaluateUnavailableError("Evaluate workspace service is unavailable") from exc
    if response.status_code >= 400:
        raise EvaluateRequestError(response.status_code, _safe_detail(response))
    try:
        return response_model.model_validate(response.json())
    except (ValueError, TypeError) as exc:
        raise EvaluateUnavailableError("Evaluate workspace returned an invalid contract") from exc


async def _request_raw(
    method: str,
    path: str,
    *,
    org_id: UUID,
    project_id: UUID,
    actor: str,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | BaseModel | None = None,
    expected_status: int | None = None,
) -> dict[str, Any]:
    base_url, _, _ = _connection()
    headers = internal_headers(org_id=org_id, project_id=project_id, actor=actor)
    payload: dict[str, Any] | None = None
    if isinstance(json_body, BaseModel):
        payload = json_body.model_dump(mode="json")
    elif json_body is not None:
        payload = json_body
    try:
        async with _open_client() as client:
            response = await client.request(
                method,
                f"{base_url}{path}",
                params=params,
                json=payload,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise EvaluateUnavailableError("Evaluate workspace service is unavailable") from exc
    if expected_status is not None and response.status_code != expected_status:
        raise EvaluateRequestError(response.status_code, _safe_detail(response))
    if response.status_code >= 400:
        raise EvaluateRequestError(response.status_code, _safe_detail(response))
    try:
        body = response.json()
    except ValueError as exc:
        raise EvaluateUnavailableError("Evaluate workspace returned an invalid contract") from exc
    if not isinstance(body, dict):
        raise EvaluateUnavailableError("Evaluate workspace returned an invalid contract")
    return body


async def _request_paged[T: BaseModel](
    method: str,
    path: str,
    *,
    org_id: UUID,
    project_id: UUID,
    actor: str,
    item_model: type[T],
    params: dict[str, Any] | None = None,
) -> PagedResponse[T]:
    base_url, _, _ = _connection()
    headers = internal_headers(org_id=org_id, project_id=project_id, actor=actor)
    try:
        async with _open_client() as client:
            response = await client.request(
                method,
                f"{base_url}{path}",
                params=params,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise EvaluateUnavailableError("Evaluate workspace service is unavailable") from exc
    if response.status_code >= 400:
        raise EvaluateRequestError(response.status_code, _safe_detail(response))
    try:
        body = response.json()
        if not isinstance(body, dict):
            raise ValueError("expected object")
        meta = PageMeta.model_validate(body.get("meta", {}))
        items_raw = body.get("items", [])
        if not isinstance(items_raw, list):
            raise ValueError("expected items list")
        items = [item_model.model_validate(item) for item in items_raw]
    except (ValueError, TypeError) as exc:
        raise EvaluateUnavailableError("Evaluate workspace returned an invalid contract") from exc
    return cast(PagedResponse[T], PagedResponse(items=items, meta=meta))


async def list_datasets(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    q: str | None,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[DatasetOut]:
    prefix = _project_prefix(org_id, project_id)
    params = {k: v for k, v in {"q": q, "limit": limit, "cursor": cursor}.items() if v is not None}
    return await _request_paged(
        "GET",
        f"{prefix}/datasets",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        item_model=DatasetOut,
        params=params or None,
    )


async def get_dataset(
    org_id: UUID, project_id: UUID, *, actor: str, dataset_key: str
) -> DatasetOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "GET",
        f"{prefix}/datasets/{quote(dataset_key, safe='')}",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=DatasetOut,
    )


async def list_dataset_revisions(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    dataset_key: str,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[DatasetRevisionOut]:
    prefix = _project_prefix(org_id, project_id)
    params = {k: v for k, v in {"limit": limit, "cursor": cursor}.items() if v is not None}
    return await _request_paged(
        "GET",
        f"{prefix}/datasets/{quote(dataset_key, safe='')}/revisions",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        item_model=DatasetRevisionOut,
        params=params or None,
    )


async def get_dataset_revision(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    dataset_key: str,
    revision_id: UUID,
) -> DatasetRevisionOut:
    prefix = _project_prefix(org_id, project_id)
    key = quote(dataset_key, safe="")
    return await _request_json(
        "GET",
        f"{prefix}/datasets/{key}/revisions/{revision_id}",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=DatasetRevisionOut,
    )


async def list_revision_examples(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    dataset_key: str,
    revision_id: UUID,
    split: str | None,
    q: str | None,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[ExampleSummaryOut]:
    prefix = _project_prefix(org_id, project_id)
    key = quote(dataset_key, safe="")
    params = {
        k: v
        for k, v in {"split": split, "q": q, "limit": limit, "cursor": cursor}.items()
        if v is not None
    }
    return await _request_paged(
        "GET",
        f"{prefix}/datasets/{key}/revisions/{revision_id}/examples",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        item_model=ExampleSummaryOut,
        params=params or None,
    )


async def get_revision_example(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    dataset_key: str,
    revision_id: UUID,
    example_id: UUID,
) -> ExampleSummaryOut:
    prefix = _project_prefix(org_id, project_id)
    key = quote(dataset_key, safe="")
    return await _request_json(
        "GET",
        f"{prefix}/datasets/{key}/revisions/{revision_id}/examples/{example_id}",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=ExampleSummaryOut,
    )


async def list_experiments(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    q: str | None,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[ExperimentOut]:
    prefix = _project_prefix(org_id, project_id)
    params = {k: v for k, v in {"q": q, "limit": limit, "cursor": cursor}.items() if v is not None}
    return await _request_paged(
        "GET",
        f"{prefix}/experiments",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        item_model=ExperimentOut,
        params=params or None,
    )


async def get_experiment_by_key(
    org_id: UUID, project_id: UUID, *, actor: str, experiment_key: str
) -> ExperimentOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "GET",
        f"{prefix}/experiments/by-key/{quote(experiment_key, safe='')}",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=ExperimentOut,
    )


async def get_experiment(
    org_id: UUID, project_id: UUID, *, actor: str, experiment_id: UUID
) -> ExperimentOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "GET",
        f"{prefix}/experiments/{experiment_id}",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=ExperimentOut,
    )


async def list_evaluators(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    q: str | None,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[EvaluatorOut]:
    prefix = _project_prefix(org_id, project_id)
    params = {k: v for k, v in {"q": q, "limit": limit, "cursor": cursor}.items() if v is not None}
    return await _request_paged(
        "GET",
        f"{prefix}/evaluators",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        item_model=EvaluatorOut,
        params=params or None,
    )


async def get_evaluator(
    org_id: UUID, project_id: UUID, *, actor: str, evaluator_key: str
) -> EvaluatorOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "GET",
        f"{prefix}/evaluators/{quote(evaluator_key, safe='')}",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=EvaluatorOut,
    )


async def list_evaluator_revisions(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    evaluator_key: str,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[EvaluatorRevisionSummaryOut]:
    prefix = _project_prefix(org_id, project_id)
    key = quote(evaluator_key, safe="")
    params = {k: v for k, v in {"limit": limit, "cursor": cursor}.items() if v is not None}
    return await _request_paged(
        "GET",
        f"{prefix}/evaluators/{key}/revisions",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        item_model=EvaluatorRevisionSummaryOut,
        params=params or None,
    )


async def get_evaluator_revision(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    evaluator_key: str,
    revision_id: UUID,
) -> EvaluatorRevisionSummaryOut:
    prefix = _project_prefix(org_id, project_id)
    key = quote(evaluator_key, safe="")
    return await _request_json(
        "GET",
        f"{prefix}/evaluators/{key}/revisions/{revision_id}",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=EvaluatorRevisionSummaryOut,
    )


async def list_scores(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    target_type: str | None,
    target_id: str | None,
    name: str | None,
    source: str | None,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[ScoreDetailOut]:
    prefix = _project_prefix(org_id, project_id)
    params = {
        k: v
        for k, v in {
            "target_type": target_type,
            "target_id": target_id,
            "name": name,
            "source": source,
            "limit": limit,
            "cursor": cursor,
        }.items()
        if v is not None
    }
    return await _request_paged(
        "GET",
        f"{prefix}/scores",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        item_model=ScoreDetailOut,
        params=params or None,
    )


async def get_score(
    org_id: UUID, project_id: UUID, *, actor: str, score_id: UUID
) -> ScoreDetailOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "GET",
        f"{prefix}/scores/{score_id}",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=ScoreDetailOut,
    )


async def list_online_alerts(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    status: str | None,
    rule_id: UUID | None,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[AlertOut]:
    prefix = _project_prefix(org_id, project_id)
    params = {
        k: v
        for k, v in {
            "status": status,
            "rule_id": str(rule_id) if rule_id is not None else None,
            "limit": limit,
            "cursor": cursor,
        }.items()
        if v is not None
    }
    return await _request_paged(
        "GET",
        f"{prefix}/online-rules/alerts",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        item_model=AlertOut,
        params=params or None,
    )


async def get_online_alert(
    org_id: UUID, project_id: UUID, *, actor: str, alert_id: UUID
) -> AlertOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "GET",
        f"{prefix}/online-rules/alerts/{alert_id}",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=AlertOut,
    )


async def retry_online_alert(
    org_id: UUID, project_id: UUID, *, actor: str, alert_id: UUID
) -> AlertOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "POST",
        f"{prefix}/online-rules/alerts/{alert_id}/retry",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=AlertOut,
    )


async def acknowledge_online_alert(
    org_id: UUID, project_id: UUID, *, actor: str, alert_id: UUID
) -> AlertOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "POST",
        f"{prefix}/online-rules/alerts/{alert_id}/acknowledge",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=AlertOut,
    )


async def list_online_rules(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[OnlineRuleOut]:
    prefix = _project_prefix(org_id, project_id)
    params = {k: v for k, v in {"limit": limit, "cursor": cursor}.items() if v is not None}
    return await _request_paged(
        "GET",
        f"{prefix}/online-rules",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        item_model=OnlineRuleOut,
        params=params or None,
    )


async def get_online_rule(
    org_id: UUID, project_id: UUID, *, actor: str, rule_id: UUID
) -> OnlineRuleOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "GET",
        f"{prefix}/online-rules/{rule_id}",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=OnlineRuleOut,
    )


async def list_annotation_queues(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[AnnotationQueueOut]:
    prefix = _project_prefix(org_id, project_id)
    params = {k: v for k, v in {"limit": limit, "cursor": cursor}.items() if v is not None}
    return await _request_paged(
        "GET",
        f"{prefix}/annotation-queues",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        item_model=AnnotationQueueOut,
        params=params or None,
    )


async def get_annotation_queue(
    org_id: UUID, project_id: UUID, *, actor: str, queue_id: UUID
) -> AnnotationQueueOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "GET",
        f"{prefix}/annotation-queues/{queue_id}",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=AnnotationQueueOut,
    )


async def list_annotation_items(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    queue_id: UUID | None,
    status: str | None,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[AnnotationItemOut]:
    prefix = _project_prefix(org_id, project_id)
    params = {
        k: v
        for k, v in {
            "queue_id": str(queue_id) if queue_id is not None else None,
            "status": status,
            "limit": limit,
            "cursor": cursor,
        }.items()
        if v is not None
    }
    return await _request_paged(
        "GET",
        f"{prefix}/annotation-queues/items",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        item_model=AnnotationItemOut,
        params=params or None,
    )


async def list_queue_annotation_items(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    queue_id: UUID,
    status: str | None,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[AnnotationItemOut]:
    prefix = _project_prefix(org_id, project_id)
    params = {
        k: v
        for k, v in {"status": status, "limit": limit, "cursor": cursor}.items()
        if v is not None
    }
    return await _request_paged(
        "GET",
        f"{prefix}/annotation-queues/{queue_id}/items",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        item_model=AnnotationItemOut,
        params=params or None,
    )


async def get_annotation_item(
    org_id: UUID, project_id: UUID, *, actor: str, item_id: UUID
) -> AnnotationItemOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "GET",
        f"{prefix}/annotation-queues/items/{item_id}",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=AnnotationItemOut,
    )


async def list_release_gates(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[ReleaseGateOut]:
    prefix = _project_prefix(org_id, project_id)
    params = {k: v for k, v in {"limit": limit, "cursor": cursor}.items() if v is not None}
    return await _request_paged(
        "GET",
        f"{prefix}/release-gates",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        item_model=ReleaseGateOut,
        params=params or None,
    )


async def get_release_gate(
    org_id: UUID, project_id: UUID, *, actor: str, gate_id: UUID
) -> ReleaseGateOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "GET",
        f"{prefix}/release-gates/{gate_id}",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=ReleaseGateOut,
    )


async def list_release_gate_evaluations(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    gate_id: UUID,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[ReleaseGateEvaluationOut]:
    prefix = _project_prefix(org_id, project_id)
    params = {k: v for k, v in {"limit": limit, "cursor": cursor}.items() if v is not None}
    return await _request_paged(
        "GET",
        f"{prefix}/release-gates/{gate_id}/evaluations",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        item_model=ReleaseGateEvaluationOut,
        params=params or None,
    )


async def create_dataset(
    org_id: UUID, project_id: UUID, *, actor: str, payload: DatasetCreate
) -> DatasetOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "POST",
        f"{prefix}/datasets",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=DatasetOut,
        json_body=payload,
    )


async def create_dataset_revision(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    dataset_key: str,
    payload: DatasetRevisionCreate,
) -> DatasetRevisionOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "POST",
        f"{prefix}/datasets/{dataset_key}/revisions",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=DatasetRevisionOut,
        json_body=payload,
    )


async def import_dataset(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    dataset_key: str,
    payload: ImportRequest,
) -> DatasetRevisionOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "POST",
        f"{prefix}/datasets/{dataset_key}/import",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=DatasetRevisionOut,
        json_body=payload,
    )


async def export_dataset_revision(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    dataset_key: str,
    revision_id: UUID,
    export_format: str,
) -> ExportResponse:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "GET",
        f"{prefix}/datasets/{dataset_key}/revisions/{revision_id}/export",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=ExportResponse,
        params={"format": export_format},
    )


async def upload_attachment(
    org_id: UUID, project_id: UUID, *, actor: str, payload: AttachmentUploadIn
) -> AttachmentUploadOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "POST",
        f"{prefix}/datasets/attachments/upload",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=AttachmentUploadOut,
        json_body=payload,
    )


async def download_attachment(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    object_ref_id: UUID,
    expires_at: int,
    signature: str,
) -> AttachmentDownloadOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "GET",
        f"{prefix}/datasets/attachments/{object_ref_id}/download",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=AttachmentDownloadOut,
        params={"expires_at": expires_at, "signature": signature},
    )


async def create_experiment(
    org_id: UUID, project_id: UUID, *, actor: str, payload: ExperimentCreate
) -> ExperimentOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "POST",
        f"{prefix}/experiments",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=ExperimentOut,
        json_body=payload,
    )


async def start_experiment(
    org_id: UUID, project_id: UUID, *, actor: str, experiment_id: UUID
) -> ExperimentOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "POST",
        f"{prefix}/experiments/{experiment_id}/start",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=ExperimentOut,
    )


async def cancel_experiment(
    org_id: UUID, project_id: UUID, *, actor: str, experiment_id: UUID
) -> ExperimentOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "POST",
        f"{prefix}/experiments/{experiment_id}/cancel",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=ExperimentOut,
    )


async def retry_experiment(
    org_id: UUID, project_id: UUID, *, actor: str, experiment_id: UUID
) -> ExperimentOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "POST",
        f"{prefix}/experiments/{experiment_id}/retry",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=ExperimentOut,
    )


async def experiment_results(
    org_id: UUID, project_id: UUID, *, actor: str, experiment_id: UUID
) -> ExperimentResultsResponse:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "GET",
        f"{prefix}/experiments/{experiment_id}/results",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=ExperimentResultsResponse,
    )


async def refresh_experiment_aggregates(
    org_id: UUID, project_id: UUID, *, actor: str, experiment_id: UUID
) -> ExperimentAggregatesRefreshResponse:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "POST",
        f"{prefix}/experiments/{experiment_id}/aggregates/refresh",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=ExperimentAggregatesRefreshResponse,
    )


async def create_evaluator(
    org_id: UUID, project_id: UUID, *, actor: str, payload: EvaluatorCreate
) -> EvaluatorRevisionOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "POST",
        f"{prefix}/evaluators",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=EvaluatorRevisionOut,
        json_body=payload,
    )


async def evaluator_dry_run(
    org_id: UUID, project_id: UUID, *, actor: str, payload: EvaluatorDryRunRequest
) -> dict[str, Any]:
    prefix = _project_prefix(org_id, project_id)
    return await _request_raw(
        "POST",
        f"{prefix}/evaluators/dry-run",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        json_body=payload,
    )


async def create_score(
    org_id: UUID, project_id: UUID, *, actor: str, payload: ScoreCreate
) -> ScoreOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "POST",
        f"{prefix}/scores",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=ScoreOut,
        json_body=payload,
    )


async def create_workload_score(
    org_id: UUID,
    project_id: UUID,
    *,
    authorization: str,
    payload: ScoreCreate,
) -> ScoreOut:
    """Forward the caller's workload bearer to evaluate — never console internal headers."""
    base_url, _, _ = _connection()
    prefix = _project_prefix(org_id, project_id)
    headers = {"Authorization": authorization}
    try:
        async with _open_client() as client:
            response = await client.post(
                f"{base_url}{prefix}/scores/workload",
                json=payload.model_dump(mode="json"),
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise EvaluateUnavailableError("Evaluate workspace service is unavailable") from exc
    if response.status_code >= 400:
        raise EvaluateRequestError(response.status_code, _safe_detail(response))
    try:
        return ScoreOut.model_validate(response.json())
    except (ValueError, TypeError) as exc:
        raise EvaluateUnavailableError("Evaluate workspace returned an invalid contract") from exc


async def correct_score(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    score_id: UUID,
    payload: ScoreCorrection,
) -> ScoreOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "POST",
        f"{prefix}/scores/{score_id}/corrections",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=ScoreOut,
        json_body=payload,
    )


async def create_online_rule(
    org_id: UUID, project_id: UUID, *, actor: str, payload: OnlineRuleCreate
) -> IdResponse:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "POST",
        f"{prefix}/online-rules",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=IdResponse,
        json_body=payload,
    )


async def ingest_online_rule_event(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    rule_id: UUID,
    event: ObserveWebhookEvent,
) -> OnlineRuleEventJobResponse:
    prefix = _project_prefix(org_id, project_id)
    enforced = event.model_copy(update={"organization_id": org_id, "project_id": project_id})
    return await _request_json(
        "POST",
        f"{prefix}/online-rules/{rule_id}/events",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=OnlineRuleEventJobResponse,
        json_body=enforced,
    )


async def create_annotation_queue(
    org_id: UUID, project_id: UUID, *, actor: str, payload: AnnotationQueueCreate
) -> IdResponse:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "POST",
        f"{prefix}/annotation-queues",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=IdResponse,
        json_body=payload,
    )


async def add_annotation_item(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    queue_id: UUID,
    payload: AnnotationItemCreate,
) -> IdResponse:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "POST",
        f"{prefix}/annotation-queues/{queue_id}/items",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=IdResponse,
        json_body=payload,
    )


async def claim_annotation_item(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    item_id: UUID,
    payload: ClaimRequest,
) -> ClaimResponse:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "POST",
        f"{prefix}/annotation-queues/items/{item_id}/claim",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=ClaimResponse,
        json_body=payload,
    )


async def submit_annotation(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    item_id: UUID,
    payload: SubmissionRequest,
) -> IdResponse:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "POST",
        f"{prefix}/annotation-queues/items/{item_id}/submissions",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=IdResponse,
        json_body=payload,
    )


async def annotation_consensus(
    org_id: UUID, project_id: UUID, *, actor: str, item_id: UUID
) -> AnnotationConsensusResponse:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "GET",
        f"{prefix}/annotation-queues/items/{item_id}/consensus",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=AnnotationConsensusResponse,
    )


async def export_annotation_to_dataset(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    item_id: UUID,
    payload: ExportToDatasetRequest,
) -> ExportToDatasetResponse:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "POST",
        f"{prefix}/annotation-queues/items/{item_id}/export-to-dataset",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=ExportToDatasetResponse,
        json_body=payload,
    )


async def create_release_gate(
    org_id: UUID, project_id: UUID, *, actor: str, payload: ReleaseGateCreate
) -> IdResponse:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "POST",
        f"{prefix}/release-gates",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=IdResponse,
        json_body=payload,
    )


async def evaluate_release_gate(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    gate_id: UUID,
    payload: ReleaseGateEvaluateRequest,
) -> ReleaseGateEvaluateResponse:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "POST",
        f"{prefix}/release-gates/{gate_id}/evaluate",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        response_model=ReleaseGateEvaluateResponse,
        json_body=payload,
    )
