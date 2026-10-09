"""Control-plane client for the independently deployed Observe query service."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx
from pydantic import BaseModel

from app.config import get_settings
from app.domains.observe.schemas import (
    ExecutionAnalytics,
    ExecutionDetail,
    ExecutionEvents,
    ExecutionLink,
    ExecutionObservations,
    ExecutionPage,
    ExecutionTimeline,
    ObservedUser,
    ObservedUserPage,
    ObserveFreshness,
    PayloadContent,
    PayloadLegalHold,
    PayloadLegalHoldUpdate,
    PayloadReference,
    SamplingPolicy,
    SamplingPolicyUpdate,
    SessionDetail,
    SessionPage,
    TraceDetail,
    TraceFacets,
    TraceGraph,
    TraceMetrics,
    TracePage,
    UserActivity,
    UserIdentityBinding,
    UserIdentityBindingCreate,
)


class ObserveUnavailableError(Exception):
    pass


class ObserveRequestError(Exception):
    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code


class _PayloadLegalHoldRequest(BaseModel):
    enabled: bool
    reason: str | None = None
    actor_subject: str


def _connection() -> tuple[str, str, float]:
    settings = get_settings()
    if not settings.observe_query_url or not settings.observe_internal_service_token:
        raise ObserveUnavailableError("Observe query service is not configured")
    return (
        settings.observe_query_url.rstrip("/"),
        settings.observe_internal_service_token,
        settings.observe_query_timeout_seconds,
    )


async def _get[T: BaseModel](
    path: str,
    *,
    org_id: UUID,
    project_id: UUID,
    response_model: type[T],
    params: dict[str, Any] | None = None,
    forwarded_headers: dict[str, str] | None = None,
) -> T:
    base_url, token, timeout = _connection()
    query = {"organization_id": str(org_id), "project_id": str(project_id)}
    if params:
        query.update({key: value for key, value in params.items() if value is not None})
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            headers = {"Authorization": f"Bearer {token}"}
            if forwarded_headers:
                headers.update(forwarded_headers)
            response = await client.get(
                f"{base_url}{path}",
                params=query,
                headers=headers,
            )
    except httpx.HTTPError as exc:
        raise ObserveUnavailableError("Observe query service is unavailable") from exc
    if response.status_code >= 400:
        detail = "Observe query failed"
        if response.status_code == 404:
            detail = "Observe resource not found"
        raise ObserveRequestError(response.status_code, detail)
    try:
        return response_model.model_validate(response.json())
    except (ValueError, TypeError) as exc:
        raise ObserveUnavailableError("Observe query returned an invalid contract") from exc


async def _post[T: BaseModel](
    path: str,
    *,
    org_id: UUID,
    project_id: UUID,
    response_model: type[T],
    payload: BaseModel,
) -> T:
    base_url, token, timeout = _connection()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{base_url}{path}",
                params={"organization_id": str(org_id), "project_id": str(project_id)},
                headers={"Authorization": f"Bearer {token}"},
                json=payload.model_dump(mode="json"),
            )
    except httpx.HTTPError as exc:
        raise ObserveUnavailableError("Observe query service is unavailable") from exc
    if response.status_code >= 400:
        raise ObserveRequestError(response.status_code, "Observe write failed")
    try:
        return response_model.model_validate(response.json())
    except (ValueError, TypeError) as exc:
        raise ObserveUnavailableError("Observe query returned an invalid contract") from exc


async def _put[T: BaseModel](
    path: str,
    *,
    org_id: UUID,
    project_id: UUID,
    response_model: type[T],
    payload: BaseModel,
    forwarded_headers: dict[str, str] | None = None,
) -> T:
    base_url, token, timeout = _connection()
    headers = {"Authorization": f"Bearer {token}", **(forwarded_headers or {})}
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.put(
                f"{base_url}{path}",
                params={"organization_id": str(org_id), "project_id": str(project_id)},
                headers=headers,
                json=payload.model_dump(mode="json"),
            )
    except httpx.HTTPError as exc:
        raise ObserveUnavailableError("Observe query service is unavailable") from exc
    if response.status_code >= 400:
        raise ObserveRequestError(response.status_code, "Observe write failed")
    try:
        return response_model.model_validate(response.json())
    except (ValueError, TypeError) as exc:
        raise ObserveUnavailableError("Observe query returned an invalid contract") from exc


async def list_traces(
    org_id: UUID, project_id: UUID, *, limit: int, offset: int, filters: dict[str, Any]
) -> TracePage:
    forwarded_filters = dict(filters)
    forwarded_filters["text"] = forwarded_filters.pop("query", None)
    forwarded_filters["tool_name"] = forwarded_filters.pop("tool", None)
    return await _get(
        "/v1/traces",
        org_id=org_id,
        project_id=project_id,
        response_model=TracePage,
        params={"limit": limit, "offset": offset, **forwarded_filters},
    )


async def get_trace(
    org_id: UUID, project_id: UUID, trace_id: str, *, limit: int, offset: int
) -> TraceDetail:
    return await _get(
        f"/v1/traces/{quote(trace_id, safe='')}",
        org_id=org_id,
        project_id=project_id,
        response_model=TraceDetail,
        params={"limit": limit, "offset": offset},
    )


async def get_trace_graph(org_id: UUID, project_id: UUID, trace_id: str) -> TraceGraph:
    return await _get(
        f"/v1/traces/{quote(trace_id, safe='')}/graph",
        org_id=org_id,
        project_id=project_id,
        response_model=TraceGraph,
    )


async def trace_facets(org_id: UUID, project_id: UUID) -> TraceFacets:
    return await _get(
        "/v1/search/facets",
        org_id=org_id,
        project_id=project_id,
        response_model=TraceFacets,
    )


async def trace_metrics(org_id: UUID, project_id: UUID, *, filters: dict[str, Any]) -> TraceMetrics:
    return await _get(
        "/v1/metrics/aggregate",
        org_id=org_id,
        project_id=project_id,
        response_model=TraceMetrics,
        params=filters,
    )


async def execution_analytics(org_id: UUID, project_id: UUID) -> ExecutionAnalytics:
    return await _get(
        "/v1/analytics/executions",
        org_id=org_id,
        project_id=project_id,
        response_model=ExecutionAnalytics,
    )


async def get_sampling_policy(org_id: UUID, project_id: UUID) -> SamplingPolicy:
    return await _get(
        "/v1/sampling-policy",
        org_id=org_id,
        project_id=project_id,
        response_model=SamplingPolicy,
    )


async def update_sampling_policy(
    org_id: UUID,
    project_id: UUID,
    payload: SamplingPolicyUpdate,
    *,
    actor_subject: str,
) -> SamplingPolicy:
    return await _put(
        "/v1/sampling-policy",
        org_id=org_id,
        project_id=project_id,
        response_model=SamplingPolicy,
        payload=payload,
        forwarded_headers={"X-Actor-Subject": actor_subject[:256]},
    )


async def list_sessions(
    org_id: UUID,
    project_id: UUID,
    *,
    limit: int,
    offset: int,
    initiating_user_id: str | None = None,
) -> SessionPage:
    return await _get(
        "/v1/sessions",
        org_id=org_id,
        project_id=project_id,
        response_model=SessionPage,
        params={
            "limit": limit,
            "offset": offset,
            "initiating_user_id": initiating_user_id,
        },
    )


async def get_session(org_id: UUID, project_id: UUID, session_id: str) -> SessionDetail:
    return await _get(
        f"/v1/sessions/{quote(session_id, safe='')}",
        org_id=org_id,
        project_id=project_id,
        response_model=SessionDetail,
    )


async def payload_references(
    org_id: UUID, project_id: UUID, trace_id: str
) -> list[PayloadReference]:
    base_url, token, timeout = _connection()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{base_url}/v1/traces/{quote(trace_id, safe='')}/payload-refs",
                params={"organization_id": str(org_id), "project_id": str(project_id)},
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as exc:
        raise ObserveUnavailableError("Observe query service is unavailable") from exc
    if response.status_code >= 400:
        raise ObserveRequestError(response.status_code, "Observe payload references failed")
    try:
        return [PayloadReference.model_validate(item) for item in response.json()]
    except (ValueError, TypeError) as exc:
        raise ObserveUnavailableError("Observe query returned an invalid contract") from exc


async def list_executions(
    org_id: UUID,
    project_id: UUID,
    *,
    limit: int,
    offset: int,
    initiating_user_id: str | None = None,
    session_id: str | None = None,
    status: str | None = None,
) -> ExecutionPage:
    return await _get(
        "/v1/executions",
        org_id=org_id,
        project_id=project_id,
        response_model=ExecutionPage,
        params={
            "limit": limit,
            "offset": offset,
            "initiating_user_id": initiating_user_id,
            "session_id": session_id,
            "status": status,
        },
    )


async def get_execution(org_id: UUID, project_id: UUID, execution_id: str) -> ExecutionDetail:
    return await _get(
        f"/v1/executions/{quote(execution_id, safe='')}",
        org_id=org_id,
        project_id=project_id,
        response_model=ExecutionDetail,
    )


async def get_execution_tree(org_id: UUID, project_id: UUID, execution_id: str) -> TraceGraph:
    return await _get(
        f"/v1/executions/{quote(execution_id, safe='')}/tree",
        org_id=org_id,
        project_id=project_id,
        response_model=TraceGraph,
    )


async def get_execution_observations(
    org_id: UUID,
    project_id: UUID,
    execution_id: str,
    *,
    limit: int,
    offset: int,
) -> ExecutionObservations:
    return await _get(
        f"/v1/executions/{quote(execution_id, safe='')}/observations",
        org_id=org_id,
        project_id=project_id,
        response_model=ExecutionObservations,
        params={"limit": limit, "offset": offset},
    )


async def get_execution_events(
    org_id: UUID,
    project_id: UUID,
    execution_id: str,
    *,
    limit: int,
) -> ExecutionEvents:
    return await _get(
        f"/v1/executions/{quote(execution_id, safe='')}/events",
        org_id=org_id,
        project_id=project_id,
        response_model=ExecutionEvents,
        params={"limit": limit},
    )


async def get_execution_timeline(
    org_id: UUID, project_id: UUID, execution_id: str
) -> ExecutionTimeline:
    return await _get(
        f"/v1/executions/{quote(execution_id, safe='')}/timeline",
        org_id=org_id,
        project_id=project_id,
        response_model=ExecutionTimeline,
    )


async def get_execution_links(
    org_id: UUID, project_id: UUID, execution_id: str
) -> list[ExecutionLink]:
    base_url, token, timeout = _connection()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                f"{base_url}/v1/executions/{quote(execution_id, safe='')}/links",
                params={"organization_id": str(org_id), "project_id": str(project_id)},
                headers={"Authorization": f"Bearer {token}"},
            )
    except httpx.HTTPError as exc:
        raise ObserveUnavailableError("Observe query service is unavailable") from exc
    if response.status_code >= 400:
        raise ObserveRequestError(response.status_code, "Observe execution links failed")
    try:
        return [ExecutionLink.model_validate(item) for item in response.json()]
    except (ValueError, TypeError) as exc:
        raise ObserveUnavailableError("Observe query returned an invalid contract") from exc


async def list_users(
    org_id: UUID, project_id: UUID, *, limit: int, offset: int
) -> ObservedUserPage:
    return await _get(
        "/v1/users",
        org_id=org_id,
        project_id=project_id,
        response_model=ObservedUserPage,
        params={"limit": limit, "offset": offset},
    )


async def get_user(org_id: UUID, project_id: UUID, user_id: str) -> ObservedUser:
    return await _get(
        f"/v1/users/{quote(user_id, safe='')}",
        org_id=org_id,
        project_id=project_id,
        response_model=ObservedUser,
    )


async def create_user_binding(
    org_id: UUID,
    project_id: UUID,
    payload: UserIdentityBindingCreate,
) -> UserIdentityBinding:
    return await _post(
        "/v1/user-bindings",
        org_id=org_id,
        project_id=project_id,
        response_model=UserIdentityBinding,
        payload=payload,
    )


async def get_user_executions(
    org_id: UUID,
    project_id: UUID,
    user_id: str,
    *,
    limit: int,
    offset: int,
) -> ExecutionPage:
    return await _get(
        f"/v1/users/{quote(user_id, safe='')}/executions",
        org_id=org_id,
        project_id=project_id,
        response_model=ExecutionPage,
        params={"limit": limit, "offset": offset},
    )


async def get_user_activity(
    org_id: UUID,
    project_id: UUID,
    user_id: str,
    dimension: str,
) -> UserActivity:
    if dimension not in {"models", "tools", "mcp-tools", "sdk-operations"}:
        raise ValueError("unsupported user activity dimension")
    return await _get(
        f"/v1/users/{quote(user_id, safe='')}/{dimension}",
        org_id=org_id,
        project_id=project_id,
        response_model=UserActivity,
    )


async def get_payload_content(
    org_id: UUID,
    project_id: UUID,
    payload_id: UUID,
    *,
    actor_subject: str,
) -> PayloadContent:
    return await _get(
        f"/v1/payloads/{payload_id}",
        org_id=org_id,
        project_id=project_id,
        response_model=PayloadContent,
        forwarded_headers={"X-Actor-Subject": actor_subject[:256]},
    )


async def update_payload_legal_hold(
    org_id: UUID,
    project_id: UUID,
    payload_id: UUID,
    payload: PayloadLegalHoldUpdate,
    *,
    actor_subject: str,
) -> PayloadLegalHold:
    return await _put(
        f"/v1/payloads/{payload_id}/legal-hold",
        org_id=org_id,
        project_id=project_id,
        response_model=PayloadLegalHold,
        payload=_PayloadLegalHoldRequest(
            enabled=payload.enabled,
            reason=payload.reason,
            actor_subject=actor_subject[:256],
        ),
    )


async def freshness(org_id: UUID, project_id: UUID) -> ObserveFreshness:
    return await _get(
        "/v1/freshness",
        org_id=org_id,
        project_id=project_id,
        response_model=ObserveFreshness,
    )


async def live_tail(
    org_id: UUID,
    project_id: UUID,
    *,
    cursor: str | None,
    trace_id: str | None = None,
) -> AsyncIterator[bytes]:
    base_url, token, timeout = _connection()
    params = {"organization_id": str(org_id), "project_id": str(project_id)}
    if cursor:
        params["cursor"] = cursor
    if trace_id:
        params["trace_id"] = trace_id
    client = httpx.AsyncClient(timeout=httpx.Timeout(timeout, read=None))
    try:
        async with client.stream(
            "GET",
            f"{base_url}/v1/live-tail",
            params=params,
            headers={"Authorization": f"Bearer {token}"},
        ) as response:
            if response.status_code >= 400:
                raise ObserveRequestError(response.status_code, "Observe live tail failed")
            async for chunk in response.aiter_bytes():
                yield chunk
    except httpx.HTTPError as exc:
        raise ObserveUnavailableError("Observe live tail is unavailable") from exc
    finally:
        await client.aclose()
