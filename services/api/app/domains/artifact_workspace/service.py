"""Control-plane client for the independently deployed prompt workspace service."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel

from app.config import get_settings
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

_RUNTIME_FORWARD_HEADERS = frozenset(
    {
        "etag",
        "cache-control",
        "x-revision-id",
        "x-revision-number",
        "x-content-digest",
        "x-schema-digest",
        "x-config-digest",
        "x-pinned-revision",
    }
)


@dataclass(frozen=True, slots=True)
class RuntimeReadResult:
    status_code: int
    body: RuntimeArtifactResponse | None
    headers: dict[str, str]


PROMPT_CONFIGURE_SCOPES: tuple[str, ...] = (
    "prompt:label:production",
    "prompt:label:staging",
    "prompt:label:latest",
)

_client_factory: Callable[[], httpx.AsyncClient] | None = None


class PromptUnavailableError(Exception):
    pass


class PromptRequestError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code


def _connection() -> tuple[str, str, float]:
    settings = get_settings()
    if not settings.prompt_service_url or not settings.prompt_internal_service_token:
        raise PromptUnavailableError("Prompt workspace service is not configured")
    return (
        settings.prompt_service_url.rstrip("/"),
        settings.prompt_internal_service_token,
        settings.prompt_service_timeout_seconds,
    )


def internal_headers(
    *,
    org_id: UUID,
    project_id: UUID,
    actor: str,
    configure: bool,
) -> dict[str, str]:
    _, token, _ = _connection()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Organization-Id": str(org_id),
        "X-Project-Id": str(project_id),
        "X-Actor": actor,
        "X-Internal-Roles": "console:configure" if configure else "console:read",
    }
    if configure:
        headers["X-Internal-Scopes"] = ",".join(PROMPT_CONFIGURE_SCOPES)
    return headers


def _safe_detail(response: httpx.Response) -> str:
    if response.status_code >= 500:
        return "Prompt workspace request failed"
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
        return "Prompt resource not found"
    if response.status_code == 403:
        return "Prompt workspace refused the request"
    return "Prompt workspace request failed"


def _project_prefix(org_id: UUID, project_id: UUID) -> str:
    return f"/v1/orgs/{org_id}/projects/{project_id}"


def _open_client(*, read_timeout: float | None = None) -> httpx.AsyncClient:
    if _client_factory is not None:
        return _client_factory()
    _, _, timeout = _connection()
    effective = read_timeout if read_timeout is not None else timeout
    return httpx.AsyncClient(timeout=effective)


async def _request_json[T: BaseModel](
    method: str,
    path: str,
    *,
    org_id: UUID,
    project_id: UUID,
    actor: str,
    configure: bool,
    response_model: type[T],
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | BaseModel | None = None,
    extra_headers: dict[str, str] | None = None,
) -> T:
    base_url, _, _ = _connection()
    headers = internal_headers(
        org_id=org_id, project_id=project_id, actor=actor, configure=configure
    )
    if extra_headers:
        headers.update(extra_headers)
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
        raise PromptUnavailableError("Prompt workspace service is unavailable") from exc
    if response.status_code >= 400:
        raise PromptRequestError(response.status_code, _safe_detail(response))
    try:
        return response_model.model_validate(response.json())
    except (ValueError, TypeError) as exc:
        raise PromptUnavailableError("Prompt workspace returned an invalid contract") from exc


async def _request_raw(
    method: str,
    path: str,
    *,
    org_id: UUID,
    project_id: UUID,
    actor: str,
    configure: bool,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | BaseModel | None = None,
) -> dict[str, Any]:
    base_url, _, _ = _connection()
    headers = internal_headers(
        org_id=org_id, project_id=project_id, actor=actor, configure=configure
    )
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
        raise PromptUnavailableError("Prompt workspace service is unavailable") from exc
    if response.status_code >= 400:
        raise PromptRequestError(response.status_code, _safe_detail(response))
    try:
        body = response.json()
    except ValueError as exc:
        raise PromptUnavailableError("Prompt workspace returned an invalid contract") from exc
    if not isinstance(body, dict):
        raise PromptUnavailableError("Prompt workspace returned an invalid contract")
    return body


async def _request_text(
    method: str,
    path: str,
    *,
    org_id: UUID,
    project_id: UUID,
    actor: str,
    configure: bool,
    params: dict[str, Any] | None = None,
) -> str:
    base_url, _, _ = _connection()
    headers = internal_headers(
        org_id=org_id, project_id=project_id, actor=actor, configure=configure
    )
    try:
        async with _open_client() as client:
            response = await client.request(
                method,
                f"{base_url}{path}",
                params=params,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise PromptUnavailableError("Prompt workspace service is unavailable") from exc
    if response.status_code >= 400:
        raise PromptRequestError(response.status_code, _safe_detail(response))
    return response.text


async def create_artifact(
    org_id: UUID, project_id: UUID, *, actor: str, payload: ArtifactCreate
) -> ArtifactOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "POST",
        f"{prefix}/artifacts",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        configure=True,
        response_model=ArtifactOut,
        json_body=payload,
    )


async def list_artifacts(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    kind: str | None,
    query: str | None,
    label: str | None,
    cursor: str | None,
    limit: int,
) -> ArtifactListResponse:
    prefix = _project_prefix(org_id, project_id)
    params = {
        "kind": kind,
        "q": query,
        "label": label,
        "cursor": cursor,
        "limit": limit,
    }
    return await _request_json(
        "GET",
        f"{prefix}/artifacts",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        configure=False,
        response_model=ArtifactListResponse,
        params={k: v for k, v in params.items() if v is not None},
    )


async def get_artifact(
    org_id: UUID, project_id: UUID, *, actor: str, artifact_key: str
) -> ArtifactOut:
    prefix = _project_prefix(org_id, project_id)
    key = quote(artifact_key, safe="")
    return await _request_json(
        "GET",
        f"{prefix}/artifacts/{key}",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        configure=False,
        response_model=ArtifactOut,
    )


async def create_revision(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    artifact_key: str,
    payload: RevisionCreate,
) -> RevisionDetailOut:
    prefix = _project_prefix(org_id, project_id)
    key = quote(artifact_key, safe="")
    return await _request_json(
        "POST",
        f"{prefix}/artifacts/{key}/revisions",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        configure=True,
        response_model=RevisionDetailOut,
        json_body=payload,
    )


async def list_revisions(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    artifact_key: str,
    limit: int,
) -> RevisionListResponse:
    prefix = _project_prefix(org_id, project_id)
    key = quote(artifact_key, safe="")
    return await _request_json(
        "GET",
        f"{prefix}/artifacts/{key}/revisions",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        configure=False,
        response_model=RevisionListResponse,
        params={"limit": limit},
    )


async def get_revision(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    artifact_key: str,
    revision_id: UUID,
) -> RevisionDetailOut:
    prefix = _project_prefix(org_id, project_id)
    key = quote(artifact_key, safe="")
    return await _request_json(
        "GET",
        f"{prefix}/artifacts/{key}/revisions/{revision_id}",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        configure=False,
        response_model=RevisionDetailOut,
    )


async def diff_revisions(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    artifact_key: str,
    payload: DiffRequest,
) -> DiffResponse:
    prefix = _project_prefix(org_id, project_id)
    key = quote(artifact_key, safe="")
    return await _request_json(
        "POST",
        f"{prefix}/artifacts/{key}/revisions:diff",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        configure=False,
        response_model=DiffResponse,
        json_body=payload,
    )


async def rollback_revision(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    artifact_key: str,
    payload: RollbackRequest,
) -> RevisionDetailOut:
    prefix = _project_prefix(org_id, project_id)
    key = quote(artifact_key, safe="")
    return await _request_json(
        "POST",
        f"{prefix}/artifacts/{key}/revisions:rollback",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        configure=True,
        response_model=RevisionDetailOut,
        json_body=payload,
    )


async def compare_revisions(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    artifact_key: str,
    payload: CompareRevisionsRequest,
) -> CompareRevisionsResponse:
    prefix = _project_prefix(org_id, project_id)
    key = quote(artifact_key, safe="")
    body = await _request_raw(
        "POST",
        f"{prefix}/artifacts/{key}/revisions:compare",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        configure=False,
        json_body=payload,
    )
    return CompareRevisionsResponse.model_validate(body)


async def promote_label(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    artifact_key: str,
    payload: PromoteLabelRequest,
) -> LabelOut:
    prefix = _project_prefix(org_id, project_id)
    key = quote(artifact_key, safe="")
    return await _request_json(
        "POST",
        f"{prefix}/artifacts/{key}/labels:promote",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        configure=True,
        response_model=LabelOut,
        json_body=payload,
    )


async def get_label(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    artifact_key: str,
    label_name: str,
) -> LabelOut:
    prefix = _project_prefix(org_id, project_id)
    key = quote(artifact_key, safe="")
    name = quote(label_name, safe="")
    return await _request_json(
        "GET",
        f"{prefix}/artifacts/{key}/labels/{name}",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        configure=False,
        response_model=LabelOut,
    )


async def label_history(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    artifact_key: str,
    label_name: str,
    limit: int,
) -> LabelHistoryResponse:
    prefix = _project_prefix(org_id, project_id)
    key = quote(artifact_key, safe="")
    name = quote(label_name, safe="")
    return await _request_json(
        "GET",
        f"{prefix}/artifacts/{key}/labels/{name}/history",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        configure=False,
        response_model=LabelHistoryResponse,
        params={"limit": limit},
    )


async def compare_labels(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    artifact_key: str,
    payload: CompareLabelsRequest,
) -> dict[str, object]:
    prefix = _project_prefix(org_id, project_id)
    key = quote(artifact_key, safe="")
    return await _request_raw(
        "POST",
        f"{prefix}/artifacts/{key}/labels:compare",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        configure=False,
        json_body=payload,
    )


async def run_playground_sync(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    payload: PlaygroundRunRequest,
    workload_authorization: str | None,
) -> PlaygroundRunResponse:
    prefix = _project_prefix(org_id, project_id)
    extra: dict[str, str] = {}
    if workload_authorization:
        extra["X-Workload-Authorization"] = workload_authorization
    return await _request_json(
        "POST",
        f"{prefix}/playground/runs",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        configure=True,
        response_model=PlaygroundRunResponse,
        json_body=payload,
        extra_headers=extra or None,
    )


async def playground_run_status(
    org_id: UUID, project_id: UUID, *, actor: str, run_id: UUID
) -> PlaygroundRunStatusOut:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "GET",
        f"{prefix}/playground/runs/{run_id}",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        configure=False,
        response_model=PlaygroundRunStatusOut,
    )


async def cancel_playground_run(
    org_id: UUID, project_id: UUID, *, actor: str, run_id: UUID
) -> PlaygroundCancelResponse:
    prefix = _project_prefix(org_id, project_id)
    return await _request_json(
        "POST",
        f"{prefix}/playground/runs/{run_id}:cancel",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        configure=True,
        response_model=PlaygroundCancelResponse,
    )


async def replay_playground_run(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    run_id: UUID,
    workload_authorization: str | None,
) -> PlaygroundRunResponse:
    prefix = _project_prefix(org_id, project_id)
    extra: dict[str, str] = {}
    if workload_authorization:
        extra["X-Workload-Authorization"] = workload_authorization
    return await _request_json(
        "POST",
        f"{prefix}/playground/runs/{run_id}:replay",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        configure=True,
        response_model=PlaygroundRunResponse,
        extra_headers=extra or None,
    )


async def stream_playground_run(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    payload: PlaygroundRunRequest,
    workload_authorization: str | None,
    disconnect: Callable[[], Awaitable[bool]],
) -> AsyncIterator[bytes]:
    base_url, _, timeout = _connection()
    prefix = _project_prefix(org_id, project_id)
    headers = internal_headers(org_id=org_id, project_id=project_id, actor=actor, configure=True)
    if workload_authorization:
        headers["X-Workload-Authorization"] = workload_authorization
    stream_payload = payload.model_copy(update={"stream": True})
    client = (
        _open_client()
        if _client_factory is not None
        else httpx.AsyncClient(timeout=httpx.Timeout(timeout, read=None))
    )
    try:
        async with client.stream(
            "POST",
            f"{base_url}{prefix}/playground/runs",
            headers=headers,
            json=stream_payload.model_dump(mode="json"),
        ) as response:
            if response.status_code >= 400:
                raise PromptRequestError(response.status_code, _safe_detail(response))
            async for chunk in response.aiter_bytes():
                if await disconnect():
                    await response.aclose()
                    break
                yield chunk
    except httpx.HTTPError as exc:
        raise PromptUnavailableError("Prompt playground stream is unavailable") from exc
    finally:
        await client.aclose()


async def read_runtime_artifact(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    artifact_key: str,
    label: str | None,
    revision_id: UUID | None,
    pin_revision_id: UUID | None,
    if_none_match: str | None,
) -> RuntimeReadResult:
    base_url, _, _ = _connection()
    prefix = _project_prefix(org_id, project_id)
    key = quote(artifact_key, safe="")
    headers = internal_headers(org_id=org_id, project_id=project_id, actor=actor, configure=False)
    if if_none_match:
        headers["If-None-Match"] = if_none_match
    params = {
        k: v
        for k, v in {
            "label": label,
            "revision_id": str(revision_id) if revision_id else None,
            "pin_revision_id": str(pin_revision_id) if pin_revision_id else None,
        }.items()
        if v is not None
    }
    try:
        async with _open_client() as client:
            response = await client.get(
                f"{base_url}{prefix}/runtime/read/artifacts/{key}",
                params=params or None,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise PromptUnavailableError("Prompt workspace service is unavailable") from exc
    if response.status_code >= 400 and response.status_code != 304:
        raise PromptRequestError(response.status_code, _safe_detail(response))
    forwarded = {
        key: value
        for key, value in response.headers.items()
        if key.lower() in _RUNTIME_FORWARD_HEADERS
    }
    if response.status_code == 304:
        return RuntimeReadResult(status_code=304, body=None, headers=forwarded)
    try:
        body = RuntimeArtifactResponse.model_validate(response.json())
    except (ValueError, TypeError) as exc:
        raise PromptUnavailableError("Prompt workspace returned an invalid contract") from exc
    return RuntimeReadResult(status_code=200, body=body, headers=forwarded)


async def list_audit(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    resource_type: str | None,
    action: str | None,
    audit_actor: str | None,
    since: datetime | None,
    until: datetime | None,
    cursor: datetime | None,
    limit: int,
) -> AuditListResponse:
    prefix = _project_prefix(org_id, project_id)
    params: dict[str, Any] = {"limit": limit}
    if resource_type:
        params["resource_type"] = resource_type
    if action:
        params["action"] = action
    if audit_actor:
        params["actor"] = audit_actor
    if since:
        params["since"] = since.isoformat()
    if until:
        params["until"] = until.isoformat()
    if cursor:
        params["cursor"] = cursor.isoformat()
    return await _request_json(
        "GET",
        f"{prefix}/audit",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        configure=False,
        response_model=AuditListResponse,
        params=params,
    )


async def export_audit(
    org_id: UUID,
    project_id: UUID,
    *,
    actor: str,
    resource_type: str | None,
    action: str | None,
    audit_actor: str | None,
    since: datetime | None,
    until: datetime | None,
    limit: int,
) -> str:
    prefix = _project_prefix(org_id, project_id)
    params: dict[str, Any] = {"limit": limit, "format": "ndjson"}
    if resource_type:
        params["resource_type"] = resource_type
    if action:
        params["action"] = action
    if audit_actor:
        params["actor"] = audit_actor
    if since:
        params["since"] = since.isoformat()
    if until:
        params["until"] = until.isoformat()
    return await _request_text(
        "GET",
        f"{prefix}/audit/export",
        org_id=org_id,
        project_id=project_id,
        actor=actor,
        configure=False,
        params=params,
    )
