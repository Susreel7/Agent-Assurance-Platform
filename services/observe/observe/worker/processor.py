"""Normalize manifests and write ClickHouse + Postgres metadata."""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from observe.clickhouse.client import ClickHouseClient
from observe.config import CaptureMode, Settings
from observe.db import postgres as pg
from observe.db import repository as repo
from observe.errors import ObserveError
from observe.ingest import otlp
from observe.ingest.limits import decompress_if_needed
from observe.providers.object_store.base import ObjectStore
from observe.worker import execution_reducer, normalizer
from observe.worker.capture import process_capture_for_manifest
from observe.worker.ch_time import clickhouse_datetime_to_nano
from observe.worker.trace_index import build_trace_index_rows

log = logging.getLogger(__name__)


def _nano_to_ch(ts: int) -> str:
    if ts <= 0:
        return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")
    sec, nano = divmod(ts, 1_000_000_000)
    dt = datetime.fromtimestamp(sec, tz=UTC).replace(microsecond=nano // 1000)
    return dt.strftime("%Y-%m-%d %H:%M:%S.%f")


def _nano_to_iso(ts: int) -> str | None:
    if ts <= 0:
        return None
    sec, nano = divmod(ts, 1_000_000_000)
    return datetime.fromtimestamp(sec, tz=UTC).replace(microsecond=nano // 1000).isoformat()


def _span_lifecycle_event(ns: normalizer.NormalizedSpan) -> str:
    is_execution = not ns.parent_span_id and ns.observation_type in {"agent", "chain"}
    prefix = "execution" if is_execution else "observation"
    if not ns.is_terminal:
        return f"{prefix}.started"
    if ns.outcome.lower() in {"error", "failed", "failure", "cancelled", "timed_out"}:
        return f"{prefix}.failed"
    return f"{prefix}.completed"


def _ch_row(
    ns: normalizer.NormalizedSpan, manifest: repo.IngestManifest, version: int
) -> dict[str, Any]:
    return {
        "organization_id": str(manifest.organization_id),
        "project_id": str(manifest.project_id),
        "trace_id": ns.trace_id,
        "span_id": ns.span_id,
        "parent_span_id": ns.parent_span_id or "",
        "parent_trace_id": ns.parent_trace_id or "",
        "execution_id": ns.execution_id or "",
        "parent_execution_id": ns.parent_execution_id or "",
        "session_id": ns.session_id or "",
        "user_session_id": ns.user_session_id or "",
        "service_name": ns.service_name or "",
        "agent_id": ns.agent_id or "",
        "agent_name": ns.agent_name or "",
        "agent_version_id": ns.agent_version_id or "",
        "environment_id": ns.environment_id or "",
        "initiating_user_id": ns.initiating_user_id or "",
        "effective_actor_id": ns.effective_actor_id or "",
        "effective_actor_type": ns.effective_actor_type or "",
        "invocation_source": ns.invocation_source or "",
        "application_name": ns.application_name or "",
        "client_name": ns.client_name or "",
        "request_id": ns.request_id or "",
        "replay_of_execution_id": ns.replay_of_execution_id or "",
        "replay_reason": ns.replay_reason or "",
        "repository_ref": ns.repository_ref or "",
        "branch_ref": ns.branch_ref or "",
        "commit_sha": ns.commit_sha or "",
        "deployment_name": ns.deployment_name or "",
        "region_name": ns.region_name or "",
        "runtime_name": ns.runtime_name or "",
        "framework": ns.framework or "",
        "framework_version": ns.framework_version or "",
        "kind": ns.kind,
        "observation_type": ns.observation_type,
        "operation_name": ns.operation_name,
        "source_convention": ns.source_convention,
        "mapping_revision": ns.mapping_revision,
        "status_code": ns.status_code,
        "outcome": ns.outcome,
        "model": ns.model or "",
        "tool_name": ns.tool_name or "",
        "provider": ns.provider or "",
        "sdk_name": ns.sdk_name or "",
        "sdk_version": ns.sdk_version or "",
        "sdk_operation": ns.sdk_operation or "",
        "mcp_server": ns.mcp_server or "",
        "mcp_method": ns.mcp_method or "",
        "mcp_role": ns.mcp_role or "",
        "mcp_request_id": ns.mcp_request_id or "",
        "a2a_target_agent_id": ns.a2a_target_agent_id or "",
        "a2a_target_execution_id": ns.a2a_target_execution_id or "",
        "a2a_target_trace_id": ns.a2a_target_trace_id or "",
        "retry_attempt": ns.retry_attempt,
        "graph_node_id": ns.graph_node_id or "",
        "graph_node_path": ns.graph_node_path or "",
        "start_time": _nano_to_ch(ns.start_time_unix_nano),
        "end_time": _nano_to_ch(ns.end_time_unix_nano),
        "duration_ms": ns.duration_ms,
        "input_tokens": ns.input_tokens,
        "output_tokens": ns.output_tokens,
        "cost_micros": ns.cost_micros,
        "sample_rate": ns.sample_rate,
        "clock_skew_flag": 1 if ns.clock_skew_flag else 0,
        "is_terminal": 1 if ns.is_terminal else 0,
        "version": version,
        "tags": ns.tags,
        "search_text": ns.search_text,
    }


def _ch_event_row(
    ev: normalizer.NormalizedLogEvent, manifest: repo.IngestManifest, version: int
) -> dict[str, Any]:
    return {
        "organization_id": str(manifest.organization_id),
        "project_id": str(manifest.project_id),
        "event_uid": ev.log_record_uid,
        "execution_id": ev.execution_id or "",
        "trace_id": ev.trace_id,
        "span_id": ev.span_id or "",
        "event_type": ev.event_type,
        "observation_type": ev.observation_type,
        "event_time": _nano_to_ch(ev.event_time_unix_nano),
        "status": ev.status,
        "initiating_user_id": ev.initiating_user_id or "",
        "effective_actor_id": ev.effective_actor_id or "",
        "agent_id": ev.agent_id or "",
        "model": ev.model or "",
        "tool_name": ev.tool_name or "",
        "sdk_name": ev.sdk_name or "",
        "sdk_operation": ev.sdk_operation or "",
        "mcp_server": ev.mcp_server or "",
        "mcp_method": ev.mcp_method or "",
        "sequence": ev.sequence,
        "attributes": ev.attributes,
        "version": version,
    }


def _log_events_from_rows(
    trace_id: str, rows: list[dict[str, Any]]
) -> list[normalizer.NormalizedLogEvent]:
    out: list[normalizer.NormalizedLogEvent] = []
    for row in rows:
        out.append(
            normalizer.NormalizedLogEvent(
                trace_id=trace_id,
                span_id=row.get("span_id") or None,
                log_record_uid=f"{trace_id}:{row.get('event_type')}:{row.get('sequence')}",
                execution_id=row.get("execution_id") or None,
                event_type=str(row.get("event_type") or "event"),
                observation_type=str(row.get("observation_type") or "event"),
                event_time_unix_nano=clickhouse_datetime_to_nano(row.get("event_time")),
                status=str(row.get("status") or "info"),
                initiating_user_id=row.get("initiating_user_id"),
                effective_actor_id=row.get("effective_actor_id"),
                agent_id=row.get("agent_id"),
                model=row.get("model"),
                tool_name=row.get("tool_name"),
                sdk_name=row.get("sdk_name"),
                sdk_operation=row.get("sdk_operation"),
                mcp_server=row.get("mcp_server"),
                mcp_method=row.get("mcp_method"),
                sequence=int(row.get("sequence") or 0),
                attributes=dict(row.get("attributes") or {}),
                content_fingerprint="",
            )
        )
    return out


def _aggregate_pg_row(agg: execution_reducer.ExecutionAggregate) -> dict[str, Any]:
    return {
        "execution_id": agg.execution_id,
        "execution_type": agg.execution_type,
        "trace_id": agg.trace_id,
        "parent_trace_id": agg.parent_trace_id,
        "parent_execution_id": agg.parent_execution_id,
        "root_span_id": agg.root_span_id,
        "session_id": agg.session_id,
        "user_session_id": agg.user_session_id,
        "environment_id": agg.environment_id,
        "agent_id": agg.agent_id,
        "agent_version_id": agg.agent_version_id,
        "agent_name": agg.agent_name,
        "initiating_user_id": agg.initiating_user_id,
        "effective_actor_id": agg.effective_actor_id,
        "effective_actor_type": agg.effective_actor_type,
        "invocation_source": agg.invocation_source,
        "application_name": agg.application_name,
        "client_name": agg.client_name,
        "request_id": agg.request_id,
        "replay_of_execution_id": agg.replay_of_execution_id,
        "replay_reason": agg.replay_reason,
        "repository_ref": agg.repository_ref,
        "branch_ref": agg.branch_ref,
        "commit_sha": agg.commit_sha,
        "deployment_name": agg.deployment_name,
        "region_name": agg.region_name,
        "runtime_name": agg.runtime_name,
        "framework": agg.framework,
        "framework_version": agg.framework_version,
        "status": agg.status,
        "start_time": agg.start_time,
        "end_time": agg.end_time,
        "duration_ms": agg.duration_ms,
        "span_count": agg.span_count,
        "node_count": agg.node_count,
        "generation_count": agg.generation_count,
        "tool_count": agg.tool_count,
        "sdk_count": agg.sdk_count,
        "error_count": agg.error_count,
        "retry_count": agg.retry_count,
        "input_tokens": agg.input_tokens,
        "output_tokens": agg.output_tokens,
        "total_cost_micros": agg.total_cost_micros,
        "sample_rate": agg.sample_rate,
        "sampling_decision": "sampled" if agg.sample_rate < 1 else "recorded",
        "is_live": agg.is_live,
        "is_partial": agg.is_partial,
        "is_malformed": agg.is_malformed,
        "has_cycle": agg.has_cycle,
        "has_late_data": agg.has_late_data,
        "capture_level": agg.capture_level,
        "provider": agg.provider,
        "sdk_name": agg.sdk_name,
        "mcp_server": agg.mcp_server,
        "mcp_tool_count": agg.mcp_tool_count,
        "tags": agg.tags,
    }


def _ch_edge_row(
    ns: normalizer.NormalizedSpan, manifest: repo.IngestManifest, version: int
) -> dict[str, Any] | None:
    if not ns.parent_span_id:
        return None
    return {
        "organization_id": str(manifest.organization_id),
        "project_id": str(manifest.project_id),
        "execution_id": ns.execution_id or "",
        "trace_id": ns.trace_id,
        "from_span_id": ns.parent_span_id,
        "to_span_id": ns.span_id,
        "edge_type": "parent",
        "version": version,
    }


def _recompute_trace(
    settings: Settings,
    ch: ClickHouseClient,
    conn: repo.PgConn,
    manifest: repo.IngestManifest,
    trace_id: str,
    *,
    version: int,
) -> None:
    rows = ch.spans_for_trace_final(manifest.organization_id, manifest.project_id, trace_id)
    graph_spans = [
        normalizer.NormalizedSpan(
            trace_id=trace_id,
            span_id=str(r["span_id"]),
            parent_span_id=r.get("parent_span_id") or None,
            execution_id=r.get("execution_id") or None,
            parent_execution_id=r.get("parent_execution_id") or None,
            execution_type=None,
            session_id=r.get("session_id"),
            user_session_id=r.get("user_session_id"),
            environment_id=r.get("environment_id"),
            service_name=r.get("service_name"),
            agent_id=r.get("agent_id"),
            agent_name=r.get("agent_name"),
            agent_version_id=r.get("agent_version_id"),
            kind=str(r.get("kind", "unknown")),
            observation_type=str(r.get("observation_type") or r.get("kind", "unknown")),
            operation_name=str(r.get("operation_name", "")),
            source_convention=str(r.get("source_convention", "unknown")),
            mapping_revision=1,
            status_code="ok",
            outcome=str(r.get("outcome", "unknown")),
            model=r.get("model"),
            tool_name=r.get("tool_name"),
            provider=r.get("provider"),
            sdk_name=r.get("sdk_name"),
            sdk_version=r.get("sdk_version"),
            sdk_operation=r.get("sdk_operation"),
            mcp_server=r.get("mcp_server"),
            mcp_method=r.get("mcp_method"),
            retry_attempt=int(r.get("retry_attempt") or 0),
            graph_node_id=r.get("graph_node_id"),
            graph_node_path=r.get("graph_node_path"),
            initiating_user_id=r.get("initiating_user_id"),
            effective_actor_id=r.get("effective_actor_id"),
            effective_actor_type=r.get("effective_actor_type"),
            start_time_unix_nano=clickhouse_datetime_to_nano(r.get("start_time")),
            end_time_unix_nano=clickhouse_datetime_to_nano(r.get("end_time")),
            duration_ms=float(r.get("duration_ms") or 0),
            input_tokens=int(r.get("input_tokens") or 0),
            output_tokens=int(r.get("output_tokens") or 0),
            cost_micros=int(r.get("cost_micros") or 0),
            clock_skew_flag=False,
            is_terminal=bool(int(r.get("is_terminal") or 0)),
            tags=list(r.get("tags") or []),
            search_text=str(r.get("search_text") or ""),
            content_fingerprint="",
            payload_fields={},
            payload_preprocessed=True,
            invocation_source=r.get("invocation_source") or None,
            application_name=r.get("application_name") or None,
            client_name=r.get("client_name") or None,
            request_id=r.get("request_id") or None,
            replay_of_execution_id=r.get("replay_of_execution_id") or None,
            replay_reason=r.get("replay_reason") or None,
            repository_ref=r.get("repository_ref") or None,
            branch_ref=r.get("branch_ref") or None,
            commit_sha=r.get("commit_sha") or None,
            deployment_name=r.get("deployment_name") or None,
            region_name=r.get("region_name") or None,
            runtime_name=r.get("runtime_name") or None,
            framework=r.get("framework") or r.get("source_convention") or None,
            framework_version=r.get("framework_version") or None,
            parent_trace_id=r.get("parent_trace_id") or None,
            sample_rate=float(r.get("sample_rate") or 1),
            mcp_role=r.get("mcp_role") or None,
            mcp_request_id=r.get("mcp_request_id") or None,
            a2a_target_agent_id=r.get("a2a_target_agent_id") or None,
            a2a_target_execution_id=r.get("a2a_target_execution_id") or None,
            a2a_target_trace_id=r.get("a2a_target_trace_id") or None,
        )
        for r in rows
    ]
    events = _log_events_from_rows(
        trace_id,
        ch.events_for_trace(manifest.organization_id, manifest.project_id, trace_id),
    )
    malformed, has_cycle, root = normalizer.detect_graph_flags(graph_spans)
    span_count = ch.count_spans_for_trace(manifest.organization_id, manifest.project_id, trace_id)
    session = next((g.session_id for g in graph_spans if g.session_id), None)
    service = next((g.service_name for g in graph_spans if g.service_name), None)
    agent_id = next((g.agent_id for g in graph_spans if g.agent_id), None)
    agent_name = next((g.agent_name for g in graph_spans if g.agent_name), None)
    repo.set_trace_metadata_from_graph(
        conn,
        org_id=manifest.organization_id,
        project_id=manifest.project_id,
        trace_id=trace_id,
        session_id=session,
        service_name=service,
        agent_id=agent_id,
        agent_name=agent_name,
        root_span_id=root,
        span_count=span_count,
        is_malformed=malformed,
        has_cycle=has_cycle,
    )
    if session:
        repo.upsert_session_metadata(
            conn,
            org_id=manifest.organization_id,
            project_id=manifest.project_id,
            session_id=session,
            trace_delta=0,
        )

    agg = execution_reducer.reduce_execution(
        trace_id=trace_id,
        spans=graph_spans,
        events=events,
        malformed=malformed,
        has_cycle=has_cycle,
        root_span_id=root,
        capture_level=manifest.capture_mode,
    )
    if agg.initiating_user_id:
        canonical_user_id = repo.resolve_user_identity(
            conn,
            org_id=manifest.organization_id,
            project_id=manifest.project_id,
            observed_value=agg.initiating_user_id,
        )
        agg = replace(
            agg,
            initiating_user_id=canonical_user_id,
            effective_actor_id=(
                canonical_user_id
                if agg.effective_actor_id == agg.initiating_user_id
                else agg.effective_actor_id
            ),
        )
    repo.upsert_agent_execution(
        conn,
        org_id=manifest.organization_id,
        project_id=manifest.project_id,
        agg=_aggregate_pg_row(agg),
    )
    if agg.parent_execution_id:
        repo.insert_execution_link(
            conn,
            org_id=manifest.organization_id,
            project_id=manifest.project_id,
            execution_id=agg.execution_id,
            link_type="parent_execution",
            target_execution_id=agg.parent_execution_id,
            target_trace_id=agg.parent_trace_id,
        )
    if agg.replay_of_execution_id:
        repo.insert_execution_link(
            conn,
            org_id=manifest.organization_id,
            project_id=manifest.project_id,
            execution_id=agg.execution_id,
            link_type="replay_of",
            target_execution_id=agg.replay_of_execution_id,
        )
    for span in graph_spans:
        if span.observation_type == "a2a" and (
            span.a2a_target_execution_id or span.a2a_target_trace_id
        ):
            repo.insert_execution_link(
                conn,
                org_id=manifest.organization_id,
                project_id=manifest.project_id,
                execution_id=agg.execution_id,
                link_type="a2a_invocation",
                target_execution_id=span.a2a_target_execution_id,
                target_trace_id=span.a2a_target_trace_id,
            )
        if span.mcp_role == "server" and span.mcp_request_id:
            peer = next(
                (
                    candidate
                    for candidate in graph_spans
                    if candidate.mcp_role == "client"
                    and candidate.mcp_request_id == span.mcp_request_id
                    and candidate.mcp_server == span.mcp_server
                ),
                None,
            )
            if peer:
                repo.insert_execution_link(
                    conn,
                    org_id=manifest.organization_id,
                    project_id=manifest.project_id,
                    execution_id=agg.execution_id,
                    link_type="mcp_peer",
                    target_span_id=peer.span_id,
                )
    ch.insert_execution_index_rows(
        [
            execution_reducer.execution_index_row(
                manifest.organization_id,
                manifest.project_id,
                agg,
                version=version,
                nano_to_ch=_nano_to_ch,
            )
        ]
    )
    if agg.initiating_user_id:
        repo.refresh_observed_user_from_executions(
            conn,
            org_id=manifest.organization_id,
            project_id=manifest.project_id,
            user_id=agg.initiating_user_id,
            activity_source=agg.invocation_source,
        )
    if agg.session_id:
        repo.refresh_session_from_executions(
            conn,
            org_id=manifest.organization_id,
            project_id=manifest.project_id,
            session_id=agg.session_id,
        )
    if agg.effective_actor_id:
        repo.upsert_invocation_actor(
            conn,
            org_id=manifest.organization_id,
            project_id=manifest.project_id,
            actor_id=agg.effective_actor_id,
            actor_type=agg.effective_actor_type
            or ("user" if agg.initiating_user_id == agg.effective_actor_id else "unknown"),
            initiating_user_id=agg.initiating_user_id,
            invocation_source=agg.invocation_source,
            application_name=agg.application_name,
            client_name=agg.client_name,
        )
    if (
        execution_reducer.is_terminal_execution(agg)
        and agg.execution_type == "agent"
        and agg.agent_id
    ):
        repo.insert_projection_outbox(
            conn,
            org_id=manifest.organization_id,
            project_id=manifest.project_id,
            execution_id=agg.execution_id,
            payload=execution_reducer.projection_outbox_payload(agg),
        )


def _process_logs_manifest(
    settings: Settings,
    store: ObjectStore,
    ch: ClickHouseClient,
    manifest: repo.IngestManifest,
) -> None:
    raw_bytes = store.get(manifest.object_key)
    uncompressed = decompress_if_needed(raw_bytes, manifest.content_encoding, settings)
    req = otlp.parse_logs_export_request(uncompressed, manifest.content_type)
    raw_logs, _rejected = otlp.logs_from_request(req)
    normalized = [normalizer.normalize_log_record(r) for r in raw_logs]
    version = int(time.time() * 1000)
    ch_rows: list[dict[str, Any]] = []
    affected_traces: set[str] = set()

    with pg.connect(settings.database_url, worker=True) as conn:
        for ev in normalized:
            idem = repo.apply_log_identity(
                conn,
                org_id=manifest.organization_id,
                project_id=manifest.project_id,
                trace_id=ev.trace_id,
                log_record_uid=ev.log_record_uid,
                fingerprint=ev.content_fingerprint,
                manifest_id=manifest.id,
            )
            if idem == "conflict":
                repo.insert_quarantine(
                    conn,
                    org_id=manifest.organization_id,
                    project_id=manifest.project_id,
                    reason="log_idempotency_conflict",
                    envelope_digest=manifest.envelope_digest,
                    manifest_id=manifest.id,
                    detail={"trace_id": ev.trace_id},
                )
                repo.mark_manifest_quarantined(conn, manifest.id, "log idempotency conflict")
                return
            if idem == "duplicate":
                continue
            ch_rows.append(_ch_event_row(ev, manifest, version))
            if ev.trace_id:
                affected_traces.add(ev.trace_id)
            cursor_token = f"{ev.trace_id}:log:{ev.event_type}:{version}"
            repo.insert_stream_event(
                conn,
                org_id=manifest.organization_id,
                project_id=manifest.project_id,
                event_type="event.recorded",
                trace_id=ev.trace_id,
                span_id=ev.span_id,
                cursor_token=cursor_token,
                payload={
                    "schema_version": 1,
                    "lifecycle": "event.recorded",
                    "execution_id": ev.execution_id,
                    "event_type": ev.event_type,
                    "observation_type": ev.observation_type,
                    "event_time": _nano_to_iso(ev.event_time_unix_nano),
                    "status": ev.status,
                    "sequence": ev.sequence,
                },
            )

        if ch_rows:
            ch.insert_events_json_each_row(ch_rows)
            for trace_id in affected_traces:
                _recompute_trace(
                    settings,
                    ch,
                    conn,
                    manifest,
                    trace_id,
                    version=version,
                )
        repo.mark_manifest_done(conn, manifest.id)


def process_manifest(
    settings: Settings,
    store: ObjectStore,
    ch: ClickHouseClient,
    manifest: repo.IngestManifest,
) -> None:
    if manifest.envelope_kind == "logs":
        if not store.exists(manifest.object_key):
            with pg.connect(settings.database_url, worker=True) as conn:
                repo.insert_quarantine(
                    conn,
                    org_id=manifest.organization_id,
                    project_id=manifest.project_id,
                    reason="missing_object",
                    envelope_digest=manifest.envelope_digest,
                    manifest_id=manifest.id,
                    detail={"object_key": manifest.object_key},
                )
                repo.mark_manifest_quarantined(conn, manifest.id, "envelope object missing")
            return
        _process_logs_manifest(settings, store, ch, manifest)
        return

    if not store.exists(manifest.object_key):
        with pg.connect(settings.database_url, worker=True) as conn:
            repo.insert_quarantine(
                conn,
                org_id=manifest.organization_id,
                project_id=manifest.project_id,
                reason="missing_object",
                envelope_digest=manifest.envelope_digest,
                manifest_id=manifest.id,
                detail={"object_key": manifest.object_key},
            )
            repo.mark_manifest_quarantined(conn, manifest.id, "envelope object missing")
        return

    raw_bytes = store.get(manifest.object_key)
    uncompressed = decompress_if_needed(raw_bytes, manifest.content_encoding, settings)
    req = otlp.parse_export_request(uncompressed, manifest.content_type)
    raw_spans, _rejected = otlp.spans_from_request(req)
    preprocessed = manifest.content_type.split(";")[0].strip().lower() == "application/json"
    normalized = [
        normalizer.normalize_span(s, payload_preprocessed=preprocessed) for s in raw_spans
    ]
    capture_mode = CaptureMode(manifest.capture_mode)
    version = int(time.time() * 1000)
    ch_rows: list[dict[str, Any]] = []
    ch_edge_rows: list[dict[str, Any]] = []
    ch_event_rows: list[dict[str, Any]] = []
    inserted_spans: list[normalizer.NormalizedSpan] = []
    conflicts = 0
    affected_traces: set[str] = set()

    with pg.connect(settings.database_url, worker=True) as conn:
        for raw, ns in zip(raw_spans, normalized, strict=True):
            idem = repo.apply_span_identity(
                conn,
                org_id=manifest.organization_id,
                project_id=manifest.project_id,
                trace_id=ns.trace_id,
                span_id=ns.span_id,
                fingerprint=ns.content_fingerprint,
                manifest_id=manifest.id,
                is_terminal=ns.is_terminal,
            )
            if idem == "conflict":
                conflicts += 1
                repo.insert_quarantine(
                    conn,
                    org_id=manifest.organization_id,
                    project_id=manifest.project_id,
                    reason="span_idempotency_conflict",
                    envelope_digest=manifest.envelope_digest,
                    manifest_id=manifest.id,
                    detail={"trace_id": ns.trace_id, "span_id": ns.span_id},
                )
                continue
            if idem == "duplicate":
                continue

            try:
                payload_writes = process_capture_for_manifest(
                    settings,
                    store,
                    org_id=manifest.organization_id,
                    project_id=manifest.project_id,
                    mode=capture_mode,
                    encryption_key_ref=manifest.payload_encryption_key_ref,
                    retention_days=manifest.payload_retention_days,
                    ns=ns,
                )
            except ObserveError as exc:
                repo.insert_quarantine(
                    conn,
                    org_id=manifest.organization_id,
                    project_id=manifest.project_id,
                    reason="payload_capture_failed",
                    envelope_digest=manifest.envelope_digest,
                    manifest_id=manifest.id,
                    detail={"error": str(exc), "code": exc.code},
                )
                repo.mark_manifest_quarantined(conn, manifest.id, exc.code)
                return

            for pw in payload_writes:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO observe.payload_refs (
                            payload_id, organization_id, project_id, trace_id, span_id, field_name,
                            digest, object_key, media_type, byte_size, encryption_key_ref,
                            retention_deadline, redaction_state
                        ) VALUES (
                            gen_random_uuid(),%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
                        )
                        ON CONFLICT DO NOTHING
                        """,
                        (
                            manifest.organization_id,
                            manifest.project_id,
                            ns.trace_id,
                            ns.span_id,
                            pw.field_name,
                            pw.digest,
                            pw.object_key,
                            pw.media_type,
                            pw.byte_size,
                            pw.encryption_key_ref,
                            pw.retention_deadline,
                            "redacted" if capture_mode == CaptureMode.REDACTED else "full",
                        ),
                    )

            ch_rows.append(_ch_row(ns, manifest, version))
            edge = _ch_edge_row(ns, manifest, version)
            if edge is not None:
                ch_edge_rows.append(edge)
            for otlp_event in raw.events:
                span_event = normalizer.normalize_span_otlp_event(raw, otlp_event)
                ch_event_rows.append(_ch_event_row(span_event, manifest, version))
            inserted_spans.append(ns)
            affected_traces.add(ns.trace_id)
            cursor_token = f"{ns.trace_id}:{ns.span_id}:{version}"
            repo.insert_stream_event(
                conn,
                org_id=manifest.organization_id,
                project_id=manifest.project_id,
                event_type=_span_lifecycle_event(ns),
                trace_id=ns.trace_id,
                span_id=ns.span_id,
                cursor_token=cursor_token,
                payload={
                    "schema_version": 1,
                    "lifecycle": _span_lifecycle_event(ns),
                    "execution_id": ns.execution_id,
                    "parent_span_id": ns.parent_span_id,
                    "kind": ns.kind,
                    "observation_type": ns.observation_type,
                    "outcome": ns.outcome,
                    "status": ns.status_code,
                    "operation_name": ns.operation_name,
                    "start_time": _nano_to_iso(ns.start_time_unix_nano),
                    "end_time": _nano_to_iso(ns.end_time_unix_nano),
                    "duration_ms": ns.duration_ms,
                    "is_terminal": ns.is_terminal,
                    "retry_attempt": ns.retry_attempt,
                },
            )

        if conflicts:
            repo.mark_manifest_quarantined(conn, manifest.id, f"span conflicts: {conflicts}")
            return

        # Keep the Postgres identity/event transaction open until ClickHouse accepts the
        # normalized rows. A failed analytics write must roll these records back so the
        # durable manifest can be retried without being mistaken for a duplicate.
        if ch_rows:
            ch.insert_spans_json_each_row(ch_rows)
            if ch_edge_rows:
                ch.insert_execution_edges_json_each_row(ch_edge_rows)
            if ch_event_rows:
                ch.insert_events_json_each_row(ch_event_rows)
            ch.insert_trace_index_rows(
                build_trace_index_rows(
                    manifest.organization_id,
                    manifest.project_id,
                    inserted_spans,
                    version=version,
                    nano_to_ch=_nano_to_ch,
                )
            )
            for trace_id in affected_traces:
                _recompute_trace(settings, ch, conn, manifest, trace_id, version=version)

        repo.mark_manifest_done(conn, manifest.id)


def run_worker_once(settings: Settings, store: ObjectStore, ch: ClickHouseClient) -> int:
    from observe.worker.reconcile import reconcile_manifest_objects

    worker_id = str(uuid.uuid4())
    processed = 0
    with pg.connect(settings.database_url, worker=True) as conn:
        repo.release_stale_processing(conn)
        batch = repo.claim_pending_manifests(
            conn,
            worker_id=worker_id,
            batch_size=settings.worker_batch_size,
            max_attempts=settings.worker_max_attempts,
        )
    reconcile_manifest_objects(settings, store, batch=20)
    for manifest in batch:
        try:
            process_manifest(settings, store, ch, manifest)
            processed += 1
        except Exception as exc:  # noqa: BLE001
            log.exception("manifest %s failed", manifest.id)
            with pg.connect(settings.database_url, worker=True) as conn:
                repo.mark_manifest_failed_retry(
                    conn, manifest.id, str(exc), settings.worker_max_attempts
                )
                if manifest.attempt_count + 1 >= settings.worker_max_attempts:
                    repo.insert_quarantine(
                        conn,
                        org_id=manifest.organization_id,
                        project_id=manifest.project_id,
                        reason="normalization_exhausted",
                        envelope_digest=manifest.envelope_digest,
                        manifest_id=manifest.id,
                        detail={"error": str(exc)[:512]},
                    )
    return processed
