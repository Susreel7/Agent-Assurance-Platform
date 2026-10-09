"""Trace query HTTP service."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from observe.auth import internal as internal_auth
from observe.clickhouse.client import ClickHouseClient
from observe.clickhouse.migrations_runner import apply_clickhouse_migrations
from observe.config import Settings, get_settings
from observe.db import postgres as pg
from observe.db import repository as repo
from observe.errors import AuthenticationError
from observe.health import build_health_router, freshness_payload
from observe.migrations.runner import apply_migrations
from observe.providers.object_store.encrypted import PayloadCipher
from observe.providers.object_store.factory import build_object_store
from observe.query.filters import SpanSearchFilters
from observe.query.schemas import (
    AnalyticsBreakdownItem,
    ExecutionAnalyticsResponse,
    ExecutionDetailResponse,
    ExecutionEventOut,
    ExecutionEventsResponse,
    ExecutionLinkOut,
    ExecutionListResponse,
    ExecutionObservationOut,
    ExecutionObservationsResponse,
    ExecutionSummary,
    ExecutionTimelineItem,
    ExecutionTimelineResponse,
    GraphNode,
    McpToolUsageCount,
    MetricsResponse,
    ModelUsageCount,
    ObservedUserListResponse,
    ObservedUserSummary,
    PayloadContentResponse,
    PayloadLegalHoldOut,
    PayloadLegalHoldRequest,
    PayloadRefOut,
    PipelineMetrics,
    SamplingPolicyOut,
    SamplingPolicyUpdate,
    SdkUsageCount,
    SearchFacets,
    SessionDetailResponse,
    SessionListResponse,
    SessionSummary,
    SpanOut,
    ToolUsageCount,
    TraceDetailResponse,
    TraceGraphResponse,
    TraceListResponse,
    TraceSummary,
    UserActivityBreakdown,
    UserIdentityBindingOut,
    UserIdentityBindingRequest,
)
from observe.worker import execution_reducer

log = logging.getLogger(__name__)
DETAIL_SPAN_CAP = 25_000


def _auth(settings: Settings, authorization: str | None) -> None:
    try:
        internal_auth.verify_internal_token(settings, authorization)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=401,
            detail={"code": exc.code, "message": str(exc)},
        ) from exc


def _parse_cursor(cursor: str | None) -> int:
    if not cursor:
        return 0
    if not cursor.isdigit():
        raise HTTPException(status_code=400, detail={"code": "invalid_cursor", "message": cursor})
    return int(cursor)


def _stream_events(
    settings: Settings,
    organization_id: UUID,
    project_id: UUID,
    after_id: int,
    limit: int,
    trace_id: str | None = None,
) -> list[dict[str, Any]]:
    with pg.connect(settings.database_url) as conn:
        return repo.list_stream_events(
            conn,
            org_id=organization_id,
            project_id=project_id,
            after_id=after_id,
            limit=limit,
            trace_id=trace_id,
        )


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.run_migrations_on_startup:
        apply_migrations(settings.database_url)
    ch = ClickHouseClient(settings)
    if settings.run_clickhouse_init_on_startup:
        apply_clickhouse_migrations(settings, ch)
    payload_store = build_object_store(settings)

    app = FastAPI(title="Observe Query", version="0.1.0")

    def settings_dep() -> Settings:
        return settings

    app.include_router(
        build_health_router(
            check_postgres=True,
            check_clickhouse=True,
            postgres_ping=lambda: pg.ping(settings.database_url),
            clickhouse_ping=ch.ping,
        )
    )

    @app.get("/v1/freshness")
    def freshness(
        organization_id: UUID,
        project_id: UUID,
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> dict[str, Any]:
        _auth(s, authorization)
        with pg.connect(
            s.database_url, organization_id=organization_id, project_id=project_id
        ) as conn:
            pending = repo.count_pending_manifests(conn)
            last_at = repo.last_manifest_created_at(conn)
        return freshness_payload(
            last_manifest_at=last_at.isoformat() if last_at else None,
            pending_manifests=pending,
            clickhouse_lag_seconds=None,
        )

    @app.get("/v1/traces", response_model=TraceListResponse)
    def list_traces(
        organization_id: UUID,
        project_id: UUID,
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        session_id: str | None = None,
        agent_id: str | None = None,
        initiating_user_id: str | None = Query(default=None, max_length=256),
        kind: str | None = None,
        model: str | None = None,
        tool_name: str | None = None,
        outcome: str | None = None,
        text: str | None = None,
        min_latency_ms: float | None = Query(default=None, ge=0),
        max_latency_ms: float | None = Query(default=None, ge=0),
        min_cost_micros: int | None = Query(default=None, ge=0),
        max_cost_micros: int | None = Query(default=None, ge=0),
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> TraceListResponse:
        _auth(s, authorization)
        filters = SpanSearchFilters(
            limit=limit,
            offset=offset,
            session_id=session_id,
            agent_id=agent_id,
            initiating_user_id=initiating_user_id,
            kind=kind,
            model=model,
            tool_name=tool_name,
            outcome=outcome,
            text=text,
            min_latency_ms=min_latency_ms,
            max_latency_ms=max_latency_ms,
            min_cost_micros=min_cost_micros,
            max_cost_micros=max_cost_micros,
        )
        rows, total = ch.search_traces(organization_id, project_id, filters)
        items = [TraceSummary.model_validate(row) for row in rows]
        return TraceListResponse(items=items, limit=limit, offset=offset, total=total)

    @app.get("/v1/sessions", response_model=SessionListResponse)
    def list_sessions(
        organization_id: UUID,
        project_id: UUID,
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        initiating_user_id: str | None = Query(default=None, max_length=256),
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> SessionListResponse:
        _auth(s, authorization)
        with pg.connect(
            s.database_url, organization_id=organization_id, project_id=project_id
        ) as conn:
            rows, total = repo.list_sessions(
                conn,
                org_id=organization_id,
                project_id=project_id,
                limit=limit,
                offset=offset,
                initiating_user_id=initiating_user_id,
            )
        items = [SessionSummary.model_validate(row) for row in rows]
        return SessionListResponse(
            items=items,
            limit=limit,
            offset=offset,
            total=total,
        )

    @app.get("/v1/sessions/{session_id}/traces", response_model=TraceListResponse)
    def session_traces(
        session_id: str,
        organization_id: UUID,
        project_id: UUID,
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> TraceListResponse:
        _auth(s, authorization)
        filters = SpanSearchFilters(limit=limit, offset=offset, session_id=session_id)
        rows, total = ch.search_traces(organization_id, project_id, filters)
        items = [TraceSummary.model_validate(row) for row in rows]
        return TraceListResponse(items=items, limit=limit, offset=offset, total=total)

    @app.get("/v1/sessions/{session_id}", response_model=SessionDetailResponse)
    def session_detail(
        session_id: str,
        organization_id: UUID,
        project_id: UUID,
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> SessionDetailResponse:
        _auth(s, authorization)
        with pg.connect(
            s.database_url, organization_id=organization_id, project_id=project_id
        ) as conn:
            session_row = repo.get_session(
                conn,
                org_id=organization_id,
                project_id=project_id,
                session_id=session_id,
            )
        if session_row is None:
            raise HTTPException(status_code=404, detail={"code": "session_not_found"})
        rows, _total = ch.search_traces(
            organization_id,
            project_id,
            SpanSearchFilters(limit=500, offset=0, session_id=session_id),
        )
        traces = [TraceSummary.model_validate(row) for row in rows]
        session = SessionSummary.model_validate(session_row)
        return SessionDetailResponse(session=session, traces=traces)

    @app.get("/v1/traces/{trace_id}", response_model=TraceDetailResponse)
    def trace_detail(
        trace_id: str,
        organization_id: UUID,
        project_id: UUID,
        limit: int = Query(default=500, ge=1, le=5000),
        offset: int = Query(default=0, ge=0),
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> TraceDetailResponse:
        _auth(s, authorization)
        malformed = False
        has_cycle = False
        total_spans = ch.count_spans_for_trace(organization_id, project_id, trace_id)
        with pg.connect(
            s.database_url, organization_id=organization_id, project_id=project_id
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT is_malformed, has_cycle FROM observe.trace_metadata
                    WHERE organization_id = %s AND project_id = %s AND trace_id = %s
                    """,
                    (organization_id, project_id, trace_id),
                )
                meta = cur.fetchone()
        if meta:
            malformed = bool(meta["is_malformed"])
            has_cycle = bool(meta["has_cycle"])

        rows = ch.spans_for_trace_final(organization_id, project_id, trace_id)[
            offset : offset + limit
        ]
        spans = [
            SpanOut(
                trace_id=trace_id,
                span_id=str(r.get("span_id", "")),
                parent_span_id=r.get("parent_span_id") or None,
                kind=str(r.get("kind", "unknown")),
                operation_name=str(r.get("operation_name", "")),
                outcome=r.get("outcome"),
                model=r.get("model") or None,
                tool_name=r.get("tool_name") or None,
                duration_ms=float(r.get("duration_ms") or 0),
                source_convention=r.get("source_convention"),
            )
            for r in rows
        ]
        truncated = total_spans > DETAIL_SPAN_CAP or (offset + len(spans) < total_spans)
        return TraceDetailResponse(
            trace_id=trace_id,
            spans=spans,
            limit=limit,
            offset=offset,
            truncated=truncated,
            malformed=malformed,
            has_cycle=has_cycle,
        )

    @app.get("/v1/traces/{trace_id}/graph", response_model=TraceGraphResponse)
    def trace_graph(
        trace_id: str,
        organization_id: UUID,
        project_id: UUID,
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> TraceGraphResponse:
        _auth(s, authorization)
        rows = ch.spans_for_trace_final(organization_id, project_id, trace_id)
        nodes = [
            GraphNode(
                span_id=str(r.get("span_id", "")),
                parent_span_id=r.get("parent_span_id") or None,
                kind=str(r.get("kind", "unknown")),
                operation_name=str(r.get("operation_name", "")),
            )
            for r in rows
        ]
        malformed = False
        has_cycle = False
        with pg.connect(
            s.database_url, organization_id=organization_id, project_id=project_id
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT is_malformed, has_cycle FROM observe.trace_metadata
                    WHERE organization_id = %s AND project_id = %s AND trace_id = %s
                    """,
                    (organization_id, project_id, trace_id),
                )
                meta = cur.fetchone()
        if meta:
            malformed = bool(meta["is_malformed"])
            has_cycle = bool(meta["has_cycle"])
        return TraceGraphResponse(
            trace_id=trace_id, nodes=nodes, malformed=malformed, has_cycle=has_cycle
        )

    @app.get("/v1/search/facets", response_model=SearchFacets)
    def search_facets(
        organization_id: UUID,
        project_id: UUID,
        session_id: str | None = None,
        agent_id: str | None = None,
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> SearchFacets:
        _auth(s, authorization)
        filters = SpanSearchFilters(session_id=session_id, agent_id=agent_id)
        data = ch.search_facets(organization_id, project_id, filters)
        return SearchFacets(
            time_range=data["time_range"],
            agents=data["agents"],
            kinds=data["kinds"],
            models=data["models"],
            tools=data["tools"],
            outcomes=["success", "error", "partial", "open"],
        )

    @app.get("/v1/metrics/aggregate", response_model=MetricsResponse)
    def aggregate_metrics(
        organization_id: UUID,
        project_id: UUID,
        session_id: str | None = None,
        kind: str | None = None,
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> MetricsResponse:
        _auth(s, authorization)
        filters = SpanSearchFilters(session_id=session_id, kind=kind)
        row = ch.aggregate_metrics(organization_id, project_id, filters)
        return MetricsResponse(
            span_count=int(row.get("span_count") or 0),
            trace_count=int(row.get("trace_count") or 0),
            error_rate=float(row.get("error_rate") or 0),
            avg_latency_ms=float(row.get("avg_latency_ms") or 0),
            p50_latency_ms=float(row.get("p50_latency_ms") or 0),
            p95_latency_ms=float(row.get("p95_latency_ms") or 0),
            p99_latency_ms=float(row.get("p99_latency_ms") or 0),
            input_tokens=int(row.get("input_tokens") or 0),
            output_tokens=int(row.get("output_tokens") or 0),
            total_cost_micros=int(row.get("total_cost_micros") or 0),
        )

    @app.get("/v1/analytics/executions", response_model=ExecutionAnalyticsResponse)
    def execution_analytics(
        organization_id: UUID,
        project_id: UUID,
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> ExecutionAnalyticsResponse:
        _auth(s, authorization)
        with pg.connect(
            s.database_url, organization_id=organization_id, project_id=project_id
        ) as conn:
            summary = repo.execution_analytics(conn, org_id=organization_id, project_id=project_id)
            breakdowns = {
                dimension: [
                    AnalyticsBreakdownItem.model_validate(row)
                    for row in repo.execution_breakdown(
                        conn,
                        org_id=organization_id,
                        project_id=project_id,
                        dimension=dimension,
                    )
                ]
                for dimension in (
                    "agent",
                    "environment",
                    "user",
                    "source",
                    "framework",
                    "status",
                )
            }
            pipeline = repo.observe_pipeline_metrics(
                conn, org_id=organization_id, project_id=project_id
            )
        operation_breakdowns = {
            dimension: [
                AnalyticsBreakdownItem.model_validate(row)
                for row in ch.operation_breakdown(
                    organization_id,
                    project_id,
                    dimension=dimension,
                )
            ]
            for dimension in ("model", "tool", "sdk", "mcp")
        }
        execution_count = int(summary.get("execution_count") or 0)
        recorded_count = int(summary.get("success_count") or 0) + int(
            summary.get("failed_count") or 0
        )
        sampled = (
            bool(summary.get("has_sampling")) or float(summary.get("minimum_sample_rate") or 1) < 1
        )
        return ExecutionAnalyticsResponse(
            execution_count=execution_count,
            session_count=int(summary.get("session_count") or 0),
            user_count=int(summary.get("user_count") or 0),
            actor_count=int(summary.get("actor_count") or 0),
            agent_count=int(summary.get("agent_count") or 0),
            success_count=int(summary.get("success_count") or 0),
            failed_count=int(summary.get("failed_count") or 0),
            success_rate=(
                float(summary.get("success_count") or 0) / recorded_count
                if recorded_count
                else None
            ),
            error_rate=(
                float(summary.get("failed_count") or 0) / recorded_count if recorded_count else None
            ),
            avg_duration_ms=(
                float(summary["avg_duration_ms"])
                if summary.get("avg_duration_ms") is not None
                else None
            ),
            p50_duration_ms=(
                float(summary["p50_duration_ms"])
                if summary.get("p50_duration_ms") is not None
                else None
            ),
            p90_duration_ms=(
                float(summary["p90_duration_ms"])
                if summary.get("p90_duration_ms") is not None
                else None
            ),
            p95_duration_ms=(
                float(summary["p95_duration_ms"])
                if summary.get("p95_duration_ms") is not None
                else None
            ),
            p99_duration_ms=(
                float(summary["p99_duration_ms"])
                if summary.get("p99_duration_ms") is not None
                else None
            ),
            input_tokens=int(summary.get("input_tokens") or 0),
            output_tokens=int(summary.get("output_tokens") or 0),
            total_cost_micros=int(summary.get("total_cost_micros") or 0),
            error_count=int(summary.get("error_count") or 0),
            retry_count=int(summary.get("retry_count") or 0),
            population_start=summary.get("population_start"),
            population_end=summary.get("population_end"),
            population_label="Sampled recorded executions" if sampled else "Recorded executions",
            by_agent=breakdowns["agent"],
            by_environment=breakdowns["environment"],
            by_user=breakdowns["user"],
            by_source=breakdowns["source"],
            by_framework=breakdowns["framework"],
            by_status=breakdowns["status"],
            by_model=operation_breakdowns["model"],
            by_tool=operation_breakdowns["tool"],
            by_sdk=operation_breakdowns["sdk"],
            by_mcp=operation_breakdowns["mcp"],
            pipeline=PipelineMetrics.model_validate(pipeline),
        )

    @app.get("/v1/sampling-policy", response_model=SamplingPolicyOut)
    def get_sampling_policy(
        organization_id: UUID,
        project_id: UUID,
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> SamplingPolicyOut:
        _auth(s, authorization)
        with pg.connect(
            s.database_url, organization_id=organization_id, project_id=project_id
        ) as conn:
            row = repo.get_sampling_policy(conn, org_id=organization_id, project_id=project_id)
        return SamplingPolicyOut.model_validate(row)

    @app.put("/v1/sampling-policy", response_model=SamplingPolicyOut)
    def update_sampling_policy(
        payload: SamplingPolicyUpdate,
        organization_id: UUID,
        project_id: UUID,
        actor_subject: str | None = Header(default=None, alias="X-Actor-Subject"),
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> SamplingPolicyOut:
        _auth(s, authorization)
        with pg.connect(
            s.database_url, organization_id=organization_id, project_id=project_id
        ) as conn:
            row = repo.upsert_sampling_policy(
                conn,
                org_id=organization_id,
                project_id=project_id,
                **payload.model_dump(),
                updated_by=actor_subject,
            )
        return SamplingPolicyOut.model_validate(row)

    @app.get("/v1/metrics/timeseries")
    def metrics_timeseries(
        organization_id: UUID,
        project_id: UUID,
        bucket_seconds: int = Query(default=60, ge=10, le=3600),
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> dict[str, Any]:
        _auth(s, authorization)
        filters = SpanSearchFilters()
        points = ch.time_series(organization_id, project_id, filters, bucket_seconds=bucket_seconds)
        return {"points": points, "bucket_seconds": bucket_seconds}

    def _sign_ref(key: str, s: Settings) -> tuple[str, datetime]:
        expires = datetime.now(UTC) + timedelta(seconds=s.payload_ref_sign_ttl_seconds)
        msg = f"{key}:{int(expires.timestamp())}".encode()
        sig = hmac.new(s.internal_service_token.encode("utf-8"), msg, hashlib.sha256).hexdigest()
        url = f"/v1/payloads/ref?key={key}&exp={int(expires.timestamp())}&sig={sig}"
        return url, expires

    def _execution_summary(row: dict[str, Any]) -> ExecutionSummary:
        raw_status = row.get("status")
        status = execution_reducer.normalize_execution_status(str(raw_status or "open"))
        return ExecutionSummary(
            execution_id=str(row.get("execution_id", "")),
            execution_type=row.get("execution_type"),
            trace_id=str(row.get("trace_id", "")),
            root_span_id=row.get("root_span_id") or None,
            parent_execution_id=row.get("parent_execution_id") or None,
            parent_trace_id=row.get("parent_trace_id") or None,
            session_id=row.get("session_id") or None,
            user_session_id=row.get("user_session_id") or None,
            environment_id=row.get("environment_id") or None,
            status=status,
            agent_id=row.get("agent_id"),
            agent_version_id=row.get("agent_version_id"),
            agent_name=row.get("agent_name"),
            initiating_user_id=row.get("initiating_user_id"),
            effective_actor_id=row.get("effective_actor_id"),
            effective_actor_type=row.get("effective_actor_type"),
            invocation_source=row.get("invocation_source"),
            application_name=row.get("application_name"),
            client_name=row.get("client_name"),
            request_id=row.get("request_id"),
            replay_of_execution_id=row.get("replay_of_execution_id"),
            replay_reason=row.get("replay_reason"),
            repository_ref=row.get("repository_ref"),
            branch_ref=row.get("branch_ref"),
            commit_sha=row.get("commit_sha"),
            deployment_name=row.get("deployment_name"),
            region_name=row.get("region_name"),
            runtime_name=row.get("runtime_name"),
            framework=row.get("framework"),
            framework_version=row.get("framework_version"),
            start_time=row.get("start_time"),
            end_time=row.get("end_time"),
            duration_ms=float(row["duration_ms"]) if row.get("duration_ms") is not None else None,
            span_count=int(row.get("span_count") or 0),
            node_count=int(row.get("node_count") or 0),
            generation_count=int(row.get("generation_count") or 0),
            tool_count=int(row.get("tool_count") or 0),
            sdk_count=int(row.get("sdk_count") or 0),
            mcp_tool_count=int(row.get("mcp_tool_count") or 0),
            error_count=int(row.get("error_count") or 0),
            retry_count=int(row.get("retry_count") or 0),
            input_tokens=int(row.get("input_tokens") or 0),
            output_tokens=int(row.get("output_tokens") or 0),
            total_cost_micros=int(row.get("total_cost_micros") or 0),
            is_live=bool(int(row.get("is_live") or 0)),
            is_partial=bool(int(row.get("is_partial") or 0)),
            is_malformed=bool(int(row.get("is_malformed") or 0)),
            has_cycle=bool(int(row.get("has_cycle") or 0)),
            has_late_data=bool(int(row.get("has_late_data") or 0)),
            capture_level=row.get("capture_level"),
            provider=row.get("provider"),
            sdk_name=row.get("sdk_name"),
            mcp_server=row.get("mcp_server"),
            tags=list(row.get("tags") or []),
        )

    @app.get("/v1/executions", response_model=ExecutionListResponse)
    def list_executions(
        organization_id: UUID,
        project_id: UUID,
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        initiating_user_id: str | None = None,
        session_id: str | None = None,
        status: str | None = None,
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> ExecutionListResponse:
        _auth(s, authorization)
        with pg.connect(
            s.database_url, organization_id=organization_id, project_id=project_id
        ) as conn:
            rows, total = repo.list_agent_executions(
                conn,
                org_id=organization_id,
                project_id=project_id,
                limit=limit,
                offset=offset,
                initiating_user_id=initiating_user_id,
                session_id=session_id,
                status=status,
            )
        if not rows and session_id is None:
            rows, total = ch.search_executions(
                organization_id,
                project_id,
                limit=limit,
                offset=offset,
                initiating_user_id=initiating_user_id,
                status=status,
            )
        items = [_execution_summary(r) for r in rows]
        return ExecutionListResponse(items=items, limit=limit, offset=offset, total=total)

    @app.get("/v1/executions/{execution_id}", response_model=ExecutionDetailResponse)
    def execution_detail(
        execution_id: str,
        organization_id: UUID,
        project_id: UUID,
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> ExecutionDetailResponse:
        _auth(s, authorization)
        malformed = False
        has_cycle = False
        with pg.connect(
            s.database_url, organization_id=organization_id, project_id=project_id
        ) as conn:
            row = repo.get_agent_execution(
                conn,
                org_id=organization_id,
                project_id=project_id,
                execution_id=execution_id,
            )
        if row is None:
            row = ch.get_execution_index(organization_id, project_id, execution_id)
            if row is None:
                raise HTTPException(status_code=404, detail={"code": "execution_not_found"})
        trace_id = str(row.get("trace_id", ""))
        with pg.connect(
            s.database_url, organization_id=organization_id, project_id=project_id
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT is_malformed, has_cycle FROM observe.trace_metadata
                    WHERE organization_id = %s AND project_id = %s AND trace_id = %s
                    """,
                    (organization_id, project_id, trace_id),
                )
                meta = cur.fetchone()
        if meta:
            malformed = bool(meta["is_malformed"])
            has_cycle = bool(meta["has_cycle"])
        return ExecutionDetailResponse(
            execution=_execution_summary(row),
            trace_id=trace_id,
            malformed=malformed,
            has_cycle=has_cycle,
        )

    @app.get("/v1/executions/{execution_id}/tree", response_model=TraceGraphResponse)
    def execution_tree(
        execution_id: str,
        organization_id: UUID,
        project_id: UUID,
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> TraceGraphResponse:
        _auth(s, authorization)
        detail = execution_detail(
            execution_id, organization_id, project_id, authorization=authorization, s=s
        )
        return trace_graph(
            detail.trace_id,
            organization_id,
            project_id,
            authorization=authorization,
            s=s,
        )

    @app.get(
        "/v1/executions/{execution_id}/observations", response_model=ExecutionObservationsResponse
    )
    def execution_observations(
        execution_id: str,
        organization_id: UUID,
        project_id: UUID,
        limit: int = Query(default=500, ge=1, le=5000),
        offset: int = Query(default=0, ge=0),
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> ExecutionObservationsResponse:
        _auth(s, authorization)
        detail = execution_detail(
            execution_id, organization_id, project_id, authorization=authorization, s=s
        )
        rows = ch.spans_for_trace_final(organization_id, project_id, detail.trace_id)
        exec_rows = [
            r
            for r in rows
            if not r.get("execution_id") or str(r.get("execution_id")) in ("", execution_id)
        ]
        page = exec_rows[offset : offset + limit]
        items = [
            ExecutionObservationOut(
                span_id=str(r.get("span_id", "")),
                parent_span_id=r.get("parent_span_id") or None,
                execution_id=r.get("execution_id") or None,
                parent_execution_id=r.get("parent_execution_id") or None,
                kind=str(r.get("kind", "unknown")),
                observation_type=r.get("observation_type"),
                operation_name=str(r.get("operation_name", "")),
                outcome=r.get("outcome"),
                model=r.get("model") or None,
                tool_name=r.get("tool_name") or None,
                provider=r.get("provider") or None,
                sdk_name=r.get("sdk_name") or None,
                sdk_version=r.get("sdk_version") or None,
                sdk_operation=r.get("sdk_operation") or None,
                mcp_server=r.get("mcp_server") or None,
                mcp_method=r.get("mcp_method") or None,
                mcp_role=r.get("mcp_role") or None,
                mcp_request_id=r.get("mcp_request_id") or None,
                a2a_target_agent_id=r.get("a2a_target_agent_id") or None,
                a2a_target_execution_id=r.get("a2a_target_execution_id") or None,
                a2a_target_trace_id=r.get("a2a_target_trace_id") or None,
                retry_attempt=int(r.get("retry_attempt") or 0),
                graph_node_id=r.get("graph_node_id") or None,
                graph_node_path=r.get("graph_node_path") or None,
                initiating_user_id=r.get("initiating_user_id") or None,
                effective_actor_id=r.get("effective_actor_id") or None,
                effective_actor_type=r.get("effective_actor_type") or None,
                user_session_id=r.get("user_session_id") or None,
                environment_id=r.get("environment_id") or None,
                agent_version_id=r.get("agent_version_id") or None,
                session_id=r.get("session_id") or None,
                service_name=r.get("service_name") or None,
                agent_id=r.get("agent_id") or None,
                agent_name=r.get("agent_name") or None,
                duration_ms=float(r.get("duration_ms") or 0),
                start_time=r.get("start_time"),
                end_time=r.get("end_time"),
                is_terminal=bool(int(r.get("is_terminal") or 0)),
                input_tokens=int(r.get("input_tokens") or 0),
                output_tokens=int(r.get("output_tokens") or 0),
                cost_micros=int(r.get("cost_micros") or 0),
                tags=list(r.get("tags") or []),
            )
            for r in page
        ]
        return ExecutionObservationsResponse(
            execution_id=execution_id,
            items=items,
            limit=limit,
            offset=offset,
            truncated=len(exec_rows) > offset + len(items),
        )

    @app.get("/v1/executions/{execution_id}/events", response_model=ExecutionEventsResponse)
    def execution_events(
        execution_id: str,
        organization_id: UUID,
        project_id: UUID,
        limit: int = Query(default=500, ge=1, le=5000),
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> ExecutionEventsResponse:
        _auth(s, authorization)
        rows = ch.events_for_execution(organization_id, project_id, execution_id, limit=limit)
        items = [
            ExecutionEventOut(
                event_uid=r.get("event_uid"),
                execution_id=r.get("execution_id"),
                trace_id=r.get("trace_id"),
                event_type=str(r.get("event_type", "")),
                observation_type=r.get("observation_type"),
                event_time=r.get("event_time"),
                status=r.get("status"),
                span_id=r.get("span_id") or None,
                initiating_user_id=r.get("initiating_user_id") or None,
                effective_actor_id=r.get("effective_actor_id") or None,
                agent_id=r.get("agent_id") or None,
                model=r.get("model") or None,
                tool_name=r.get("tool_name") or None,
                sdk_name=r.get("sdk_name") or None,
                sdk_operation=r.get("sdk_operation") or None,
                mcp_server=r.get("mcp_server") or None,
                mcp_method=r.get("mcp_method") or None,
                sequence=int(r.get("sequence") or 0),
                attributes=dict(r.get("attributes") or {}),
            )
            for r in rows
        ]
        return ExecutionEventsResponse(execution_id=execution_id, items=items, limit=limit)

    @app.get("/v1/executions/{execution_id}/timeline", response_model=ExecutionTimelineResponse)
    def execution_timeline(
        execution_id: str,
        organization_id: UUID,
        project_id: UUID,
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> ExecutionTimelineResponse:
        _auth(s, authorization)
        obs = execution_observations(
            execution_id,
            organization_id,
            project_id,
            limit=500,
            offset=0,
            authorization=authorization,
            s=s,
        )
        evs = execution_events(
            execution_id, organization_id, project_id, limit=500, authorization=authorization, s=s
        )
        items: list[ExecutionTimelineItem] = []
        for span in obs.items:
            items.append(
                ExecutionTimelineItem(
                    kind="span",
                    label=span.operation_name,
                    start_time=span.start_time,
                    end_time=span.end_time,
                    observation_type=span.observation_type,
                    span_id=span.span_id,
                )
            )
        for ev in evs.items:
            items.append(
                ExecutionTimelineItem(
                    kind="event",
                    label=ev.event_type,
                    start_time=ev.event_time,
                    end_time=ev.event_time,
                    observation_type=ev.observation_type,
                    event_type=ev.event_type,
                    span_id=ev.span_id,
                )
            )
        items.sort(key=lambda x: x.start_time or datetime.min.replace(tzinfo=UTC))
        return ExecutionTimelineResponse(execution_id=execution_id, items=items[:1000])

    @app.get("/v1/executions/{execution_id}/links", response_model=list[ExecutionLinkOut])
    def execution_links(
        execution_id: str,
        organization_id: UUID,
        project_id: UUID,
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> list[ExecutionLinkOut]:
        _auth(s, authorization)
        with pg.connect(
            s.database_url, organization_id=organization_id, project_id=project_id
        ) as conn:
            rows = repo.list_execution_links(
                conn,
                org_id=organization_id,
                project_id=project_id,
                execution_id=execution_id,
            )
        return [ExecutionLinkOut.model_validate(row) for row in rows]

    @app.get("/v1/users", response_model=ObservedUserListResponse)
    def list_users(
        organization_id: UUID,
        project_id: UUID,
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> ObservedUserListResponse:
        _auth(s, authorization)
        with pg.connect(
            s.database_url, organization_id=organization_id, project_id=project_id
        ) as conn:
            rows, total = repo.list_observed_users(
                conn, org_id=organization_id, project_id=project_id, limit=limit, offset=offset
            )
        items = [ObservedUserSummary.model_validate(r) for r in rows]
        return ObservedUserListResponse(items=items, limit=limit, offset=offset, total=total)

    @app.post("/v1/user-bindings", response_model=UserIdentityBindingOut)
    def create_user_binding(
        payload: UserIdentityBindingRequest,
        organization_id: UUID,
        project_id: UUID,
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> UserIdentityBindingOut:
        _auth(s, authorization)
        with pg.connect(
            s.database_url, organization_id=organization_id, project_id=project_id
        ) as conn:
            row = repo.upsert_user_identity_binding(
                conn,
                org_id=organization_id,
                project_id=project_id,
                user_id=payload.user_id,
                binding_type=payload.binding_type,
                binding_value=payload.binding_value,
            )
        return UserIdentityBindingOut.model_validate(row)

    @app.get("/v1/users/{user_id}", response_model=ObservedUserSummary)
    def user_detail(
        user_id: str,
        organization_id: UUID,
        project_id: UUID,
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> ObservedUserSummary:
        _auth(s, authorization)
        with pg.connect(
            s.database_url, organization_id=organization_id, project_id=project_id
        ) as conn:
            row = repo.get_observed_user(
                conn, org_id=organization_id, project_id=project_id, user_id=user_id
            )
        if row is None:
            raise HTTPException(status_code=404, detail={"code": "user_not_found"})
        return ObservedUserSummary.model_validate(row)

    @app.get("/v1/users/{user_id}/executions", response_model=ExecutionListResponse)
    def user_executions(
        user_id: str,
        organization_id: UUID,
        project_id: UUID,
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> ExecutionListResponse:
        _auth(s, authorization)
        with pg.connect(
            s.database_url, organization_id=organization_id, project_id=project_id
        ) as conn:
            rows, total = repo.list_agent_executions_for_user(
                conn,
                org_id=organization_id,
                project_id=project_id,
                user_id=user_id,
                limit=limit,
                offset=offset,
            )
        items = [_execution_summary(r) for r in rows]
        return ExecutionListResponse(items=items, limit=limit, offset=offset, total=total)

    @app.get("/v1/users/{user_id}/models", response_model=UserActivityBreakdown)
    def user_models(
        user_id: str,
        organization_id: UUID,
        project_id: UUID,
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> UserActivityBreakdown:
        _auth(s, authorization)
        filters = SpanSearchFilters(limit=500, offset=0)
        _, _total = ch.search_traces(organization_id, project_id, filters)
        sql_models = ch.query_json(
            f"""
            SELECT model, count() AS c FROM {ch._database}.spans FINAL
            WHERE organization_id = {{org_id:UUID}} AND project_id = {{project_id:UUID}}
              AND initiating_user_id = {{user_id:String}} AND model != ''
            GROUP BY model ORDER BY c DESC LIMIT 50
            """,
            parameters={
                "org_id": str(organization_id),
                "project_id": str(project_id),
                "user_id": user_id,
            },
        )
        return UserActivityBreakdown(
            user_id=user_id,
            models=[ModelUsageCount(model=str(r["model"]), count=int(r["c"])) for r in sql_models],
        )

    @app.get("/v1/users/{user_id}/tools", response_model=UserActivityBreakdown)
    def user_tools(
        user_id: str,
        organization_id: UUID,
        project_id: UUID,
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> UserActivityBreakdown:
        _auth(s, authorization)
        sql_tools = ch.query_json(
            f"""
            SELECT tool_name, count() AS c FROM {ch._database}.spans FINAL
            WHERE organization_id = {{org_id:UUID}} AND project_id = {{project_id:UUID}}
              AND initiating_user_id = {{user_id:String}} AND tool_name != ''
            GROUP BY tool_name ORDER BY c DESC LIMIT 50
            """,
            parameters={
                "org_id": str(organization_id),
                "project_id": str(project_id),
                "user_id": user_id,
            },
        )
        return UserActivityBreakdown(
            user_id=user_id,
            tools=[ToolUsageCount(tool=str(r["tool_name"]), count=int(r["c"])) for r in sql_tools],
        )

    @app.get("/v1/users/{user_id}/mcp-tools", response_model=UserActivityBreakdown)
    def user_mcp_tools(
        user_id: str,
        organization_id: UUID,
        project_id: UUID,
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> UserActivityBreakdown:
        _auth(s, authorization)
        sql_rows = ch.query_json(
            f"""
            SELECT mcp_server, tool_name, count() AS c FROM {ch._database}.spans FINAL
            WHERE organization_id = {{org_id:UUID}} AND project_id = {{project_id:UUID}}
              AND initiating_user_id = {{user_id:String}}
              AND (mcp_server != '' OR observation_type = 'mcp')
            GROUP BY mcp_server, tool_name ORDER BY c DESC LIMIT 50
            """,
            parameters={
                "org_id": str(organization_id),
                "project_id": str(project_id),
                "user_id": user_id,
            },
        )
        return UserActivityBreakdown(
            user_id=user_id,
            mcp_tools=[
                McpToolUsageCount(
                    server=str(r.get("mcp_server") or ""),
                    tool=str(r.get("tool_name") or ""),
                    count=int(r["c"]),
                )
                for r in sql_rows
            ],
        )

    @app.get("/v1/users/{user_id}/sdk-operations", response_model=UserActivityBreakdown)
    def user_sdk_ops(
        user_id: str,
        organization_id: UUID,
        project_id: UUID,
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> UserActivityBreakdown:
        _auth(s, authorization)
        sql_rows = ch.query_json(
            f"""
            SELECT sdk_name, sdk_operation, count() AS c FROM {ch._database}.spans FINAL
            WHERE organization_id = {{org_id:UUID}} AND project_id = {{project_id:UUID}}
              AND initiating_user_id = {{user_id:String}} AND sdk_name != ''
            GROUP BY sdk_name, sdk_operation ORDER BY c DESC LIMIT 50
            """,
            parameters={
                "org_id": str(organization_id),
                "project_id": str(project_id),
                "user_id": user_id,
            },
        )
        return UserActivityBreakdown(
            user_id=user_id,
            sdk_operations=[
                SdkUsageCount(
                    sdk=str(r["sdk_name"]),
                    operation=str(r.get("sdk_operation") or ""),
                    count=int(r["c"]),
                )
                for r in sql_rows
            ],
        )

    @app.get("/v1/payloads/{payload_id}", response_model=PayloadContentResponse)
    def payload_content(
        payload_id: UUID,
        organization_id: UUID,
        project_id: UUID,
        authorization: str | None = Header(default=None),
        actor_subject: str = Header(default="internal-service", alias="X-Actor-Subject"),
        s: Settings = Depends(settings_dep),
    ) -> PayloadContentResponse:
        _auth(s, authorization)
        import base64

        with pg.connect(
            s.database_url, organization_id=organization_id, project_id=project_id
        ) as conn:
            row = repo.get_payload_ref(
                conn, org_id=organization_id, project_id=project_id, payload_id=payload_id
            )
            if row is None:
                raise HTTPException(status_code=404, detail={"code": "payload_not_found"})
            if row.get("retention_deleted_at"):
                raise HTTPException(status_code=410, detail={"code": "payload_retention_expired"})
            byte_size = int(row.get("byte_size") or 0)
            if byte_size > s.max_payload_content_bytes:
                raise HTTPException(
                    status_code=413,
                    detail={
                        "code": "payload_too_large",
                        "message": f"payload exceeds {s.max_payload_content_bytes} bytes",
                    },
                )
            object_key = row.get("object_key")
            if not object_key or not payload_store.exists(str(object_key)):
                raise HTTPException(status_code=404, detail={"code": "payload_object_missing"})
            repo.insert_payload_access_audit(
                conn,
                org_id=organization_id,
                project_id=project_id,
                payload_ref_id=row.get("id"),
                trace_id=row.get("trace_id"),
                span_id=row.get("span_id"),
                field_name=row.get("field_name"),
                actor_subject=actor_subject[:256],
                access_kind="full",
            )
        raw = payload_store.get(str(object_key))
        if row.get("encryption_key_ref") and not s.payload_encryption_key:
            raise HTTPException(
                status_code=503,
                detail={"code": "payload_decryption_unavailable"},
            )
        if row.get("encryption_key_ref"):
            raw = PayloadCipher(s.payload_encryption_key).decrypt(raw)
        if len(raw) > s.max_payload_content_bytes:
            raw = raw[: s.max_payload_content_bytes]
        return PayloadContentResponse(
            payload_id=payload_id,
            media_type=str(row.get("media_type") or "application/octet-stream"),
            byte_size=len(raw),
            redaction_state=row.get("redaction_state"),
            content_base64=base64.b64encode(raw).decode("ascii"),
        )

    @app.put("/v1/payloads/{payload_id}/legal-hold", response_model=PayloadLegalHoldOut)
    def payload_legal_hold(
        payload_id: UUID,
        payload: PayloadLegalHoldRequest,
        organization_id: UUID,
        project_id: UUID,
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> PayloadLegalHoldOut:
        _auth(s, authorization)
        with pg.connect(
            s.database_url, organization_id=organization_id, project_id=project_id
        ) as conn:
            row = repo.set_payload_legal_hold(
                conn,
                org_id=organization_id,
                project_id=project_id,
                payload_id=payload_id,
                enabled=payload.enabled,
                actor_subject=payload.actor_subject,
                reason=payload.reason,
            )
        if row is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "payload_not_found_or_expired"},
            )
        return PayloadLegalHoldOut.model_validate(row)

    @app.get("/v1/traces/{trace_id}/payload-refs")
    def payload_refs(
        trace_id: str,
        organization_id: UUID,
        project_id: UUID,
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> list[PayloadRefOut]:
        _auth(s, authorization)
        out: list[PayloadRefOut] = []
        with pg.connect(
            s.database_url, organization_id=organization_id, project_id=project_id
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, payload_id, trace_id, span_id, field_name, digest, media_type,
                           byte_size, object_key, encryption_key_ref, redaction_state,
                           retention_deadline, legal_hold, legal_hold_reason, legal_hold_actor,
                           legal_hold_at, retention_deleted_at
                    FROM observe.payload_refs
                    WHERE organization_id = %s AND project_id = %s AND trace_id = %s
                    """,
                    (organization_id, project_id, trace_id),
                )
                for row in cur.fetchall():
                    raw_pid = row.get("payload_id") or row.get("id")
                    if raw_pid is None:
                        continue
                    pid = raw_pid if isinstance(raw_pid, UUID) else UUID(str(raw_pid))
                    content_path = f"/v1/payloads/{pid}"
                    if row.get("encryption_key_ref") or not row.get("object_key"):
                        signed, expires = None, None
                    else:
                        signed, expires = _sign_ref(row["object_key"], s)
                    out.append(
                        PayloadRefOut(
                            trace_id=row["trace_id"],
                            span_id=row["span_id"],
                            field_name=row["field_name"],
                            digest=row["digest"],
                            media_type=row["media_type"],
                            byte_size=int(row["byte_size"]),
                            payload_id=pid,
                            content_path=content_path,
                            redaction_state=row.get("redaction_state"),
                            retention_deadline=row.get("retention_deadline"),
                            legal_hold=bool(row.get("legal_hold")),
                            legal_hold_reason=row.get("legal_hold_reason"),
                            legal_hold_actor=row.get("legal_hold_actor"),
                            legal_hold_at=row.get("legal_hold_at"),
                            retention_deleted_at=row.get("retention_deleted_at"),
                            signed_url=signed,
                            expires_at=expires,
                        )
                    )
        return out

    @app.get("/v1/live-tail")
    async def live_tail(
        request: Request,
        organization_id: UUID,
        project_id: UUID,
        cursor: str | None = None,
        trace_id: str | None = Query(default=None, min_length=1, max_length=128),
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
        authorization: str | None = Header(default=None),
        s: Settings = Depends(settings_dep),
    ) -> StreamingResponse:
        _auth(s, authorization)
        after_id = _parse_cursor(cursor or last_event_id)

        async def event_stream() -> AsyncIterator[str]:
            emitted = 0
            last_id = after_id
            while emitted < s.live_tail_max_events:
                if await request.is_disconnected():
                    break
                yield ": heartbeat\n\n"
                events = await asyncio.to_thread(
                    _stream_events,
                    s,
                    organization_id,
                    project_id,
                    last_id,
                    min(20, s.live_tail_max_events - emitted),
                    trace_id,
                )
                if not events:
                    await _sleep(s.live_tail_poll_seconds)
                    continue
                for ev in events:
                    last_id = int(ev["id"])
                    payload = {
                        "id": last_id,
                        "type": ev["event_type"],
                        "trace_id": ev.get("trace_id"),
                        "span_id": ev.get("span_id"),
                        "cursor": str(last_id),
                        "payload": ev.get("payload"),
                        "created_at": ev["created_at"].isoformat(),
                    }
                    yield (
                        f"id: {last_id}\n"
                        f"event: {ev['event_type']}\n"
                        f"data: {json.dumps(payload, default=str)}\n\n"
                    )
                    emitted += 1
                    if emitted >= s.live_tail_max_events:
                        break
                await _sleep(s.live_tail_poll_seconds)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )

    return app


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)
