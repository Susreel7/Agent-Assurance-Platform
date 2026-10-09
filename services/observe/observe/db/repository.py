"""SQL for observe schema — only module with raw SQL."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import psycopg

PgConn = psycopg.Connection[dict[str, Any]]


@dataclass(frozen=True, slots=True)
class IngestManifest:
    id: UUID
    organization_id: UUID
    project_id: UUID
    agent_id: UUID | None
    envelope_digest: str
    object_key: str
    content_encoding: str
    content_type: str
    byte_size: int
    span_count: int
    rejected_span_count: int
    capture_mode: str
    status: str
    attempt_count: int
    payload_retention_days: int = 30
    payload_encryption_key_ref: str | None = None
    envelope_kind: str = "traces"
    source_wire_digest: str | None = None
    log_record_count: int = 0


def get_manifest_by_source_wire_digest(
    conn: PgConn,
    org_id: UUID,
    project_id: UUID,
    source_wire_digest: str,
) -> IngestManifest | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, organization_id, project_id, agent_id, envelope_digest, object_key,
                   content_encoding, content_type, byte_size, span_count, rejected_span_count,
                   capture_mode, status, attempt_count, payload_retention_days,
                   payload_encryption_key_ref, envelope_kind, source_wire_digest, log_record_count
            FROM observe.ingest_manifests
            WHERE organization_id = %s AND project_id = %s AND source_wire_digest = %s
            """,
            (org_id, project_id, source_wire_digest),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return IngestManifest(**row)


def get_manifest_by_digest(
    conn: PgConn,
    org_id: UUID,
    project_id: UUID,
    digest: str,
) -> IngestManifest | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, organization_id, project_id, agent_id, envelope_digest, object_key,
                   content_encoding, content_type, byte_size, span_count, rejected_span_count,
                   capture_mode, status, attempt_count, payload_retention_days,
                   payload_encryption_key_ref, envelope_kind, source_wire_digest, log_record_count
            FROM observe.ingest_manifests
            WHERE organization_id = %s AND project_id = %s AND envelope_digest = %s
            """,
            (org_id, project_id, digest),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return IngestManifest(**row)


def insert_manifest(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    agent_id: UUID | None,
    envelope_digest: str,
    object_key: str,
    content_encoding: str,
    content_type: str,
    byte_size: int,
    span_count: int,
    rejected_span_count: int,
    capture_mode: str,
    payload_retention_days: int,
    payload_encryption_key_ref: str | None,
    envelope_kind: str = "traces",
    source_wire_digest: str | None = None,
    log_record_count: int = 0,
) -> UUID:
    manifest_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO observe.ingest_manifests (
                id, organization_id, project_id, agent_id, envelope_digest, object_key,
                content_encoding, content_type, byte_size, span_count, rejected_span_count,
                capture_mode, status, payload_retention_days, payload_encryption_key_ref,
                envelope_kind, source_wire_digest, log_record_count
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s
            )
            """,
            (
                manifest_id,
                org_id,
                project_id,
                agent_id,
                envelope_digest,
                object_key,
                content_encoding,
                content_type,
                byte_size,
                span_count,
                rejected_span_count,
                capture_mode,
                payload_retention_days,
                payload_encryption_key_ref,
                envelope_kind,
                source_wire_digest,
                log_record_count,
            ),
        )
    return manifest_id


def insert_quarantine(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    reason: str,
    envelope_digest: str | None,
    manifest_id: UUID | None,
    detail: dict[str, Any],
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO observe.quarantine_records (
                organization_id, project_id, reason, envelope_digest, manifest_id, detail
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            """,
            (org_id, project_id, reason, envelope_digest, manifest_id, json.dumps(detail)),
        )


def claim_pending_manifests(
    conn: PgConn,
    *,
    worker_id: str,
    batch_size: int,
    max_attempts: int,
) -> list[IngestManifest]:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE observe.ingest_manifests m
            SET status = 'processing',
                locked_by = %s,
                locked_at = now(),
                updated_at = now(),
                attempt_count = attempt_count + 1
            WHERE m.id IN (
                SELECT id FROM observe.ingest_manifests
                WHERE status = 'pending'
                  AND attempt_count < %s
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            )
            RETURNING id, organization_id, project_id, agent_id, envelope_digest, object_key,
                      content_encoding, content_type, byte_size, span_count, rejected_span_count,
                      capture_mode, status, attempt_count, payload_retention_days,
                      payload_encryption_key_ref, envelope_kind, source_wire_digest,
                      log_record_count
            """,
            (worker_id, max_attempts, batch_size),
        )
        rows = cur.fetchall()
    return [IngestManifest(**r) for r in rows]


def release_stale_processing(conn: PgConn, *, stale_seconds: int = 300) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE observe.ingest_manifests
            SET status = 'pending', locked_by = NULL, locked_at = NULL, updated_at = now()
            WHERE status = 'processing'
              AND locked_at < now() - (%s || ' seconds')::interval
            """,
            (stale_seconds,),
        )
        return cur.rowcount


def mark_manifest_done(conn: PgConn, manifest_id: UUID) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE observe.ingest_manifests
            SET status = 'done', normalized_at = now(), updated_at = now(),
                locked_by = NULL, locked_at = NULL, last_error = NULL
            WHERE id = %s
            """,
            (manifest_id,),
        )


def mark_manifest_quarantined(conn: PgConn, manifest_id: UUID, error: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE observe.ingest_manifests
            SET status = 'quarantined', last_error = %s, updated_at = now(),
                locked_by = NULL, locked_at = NULL
            WHERE id = %s
            """,
            (error[:512], manifest_id),
        )


def mark_manifest_failed_retry(
    conn: PgConn, manifest_id: UUID, error: str, max_attempts: int
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE observe.ingest_manifests
            SET status = CASE WHEN attempt_count >= %s THEN 'quarantined' ELSE 'pending' END,
                last_error = %s,
                updated_at = now(),
                locked_by = NULL,
                locked_at = NULL
            WHERE id = %s
            """,
            (max_attempts, error[:512], manifest_id),
        )


def apply_span_identity(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    trace_id: str,
    span_id: str,
    fingerprint: str,
    manifest_id: UUID,
    is_terminal: bool,
) -> str:
    """Returns inserted | duplicate | replaced | conflict."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT content_fingerprint, is_terminal FROM observe.span_idempotency
            WHERE organization_id = %s AND project_id = %s AND trace_id = %s AND span_id = %s
            """,
            (org_id, project_id, trace_id, span_id),
        )
        existing = cur.fetchone()
        if existing is None:
            cur.execute(
                """
                INSERT INTO observe.span_idempotency (
                    organization_id, project_id, trace_id, span_id,
                    content_fingerprint, manifest_id, is_terminal
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (org_id, project_id, trace_id, span_id, fingerprint, manifest_id, is_terminal),
            )
            return "inserted"
        if existing["content_fingerprint"] == fingerprint:
            return "duplicate"
        if is_terminal and not existing["is_terminal"]:
            cur.execute(
                """
                UPDATE observe.span_idempotency
                SET content_fingerprint = %s, manifest_id = %s,
                    is_terminal = true, updated_at = now()
                WHERE organization_id = %s AND project_id = %s AND trace_id = %s AND span_id = %s
                """,
                (fingerprint, manifest_id, org_id, project_id, trace_id, span_id),
            )
            return "replaced"
        return "conflict"


def set_trace_metadata_from_graph(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    trace_id: str,
    session_id: str | None,
    service_name: str | None,
    agent_id: str | None,
    agent_name: str | None,
    root_span_id: str | None,
    span_count: int,
    is_malformed: bool,
    has_cycle: bool,
) -> None:
    now = datetime.now(UTC)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO observe.trace_metadata (
                organization_id, project_id, trace_id, session_id, service_name,
                agent_id, agent_name, root_span_id, span_count,
                is_malformed, has_cycle, first_seen_at, last_seen_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (organization_id, project_id, trace_id) DO UPDATE SET
                session_id = COALESCE(EXCLUDED.session_id, observe.trace_metadata.session_id),
                service_name = COALESCE(EXCLUDED.service_name, observe.trace_metadata.service_name),
                agent_id = COALESCE(EXCLUDED.agent_id, observe.trace_metadata.agent_id),
                agent_name = COALESCE(EXCLUDED.agent_name, observe.trace_metadata.agent_name),
                root_span_id = COALESCE(EXCLUDED.root_span_id, observe.trace_metadata.root_span_id),
                span_count = EXCLUDED.span_count,
                is_malformed = EXCLUDED.is_malformed,
                has_cycle = EXCLUDED.has_cycle,
                last_seen_at = EXCLUDED.last_seen_at
            """,
            (
                org_id,
                project_id,
                trace_id,
                session_id,
                service_name,
                agent_id,
                agent_name,
                root_span_id,
                span_count,
                is_malformed,
                has_cycle,
                now,
                now,
            ),
        )


def upsert_session_metadata(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    session_id: str,
    trace_delta: int,
) -> None:
    now = datetime.now(UTC)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO observe.session_metadata (
                organization_id, project_id, session_id, trace_count, first_seen_at, last_seen_at
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (organization_id, project_id, session_id) DO UPDATE SET
                trace_count = observe.session_metadata.trace_count + EXCLUDED.trace_count,
                last_seen_at = EXCLUDED.last_seen_at
            """,
            (org_id, project_id, session_id, trace_delta, now, now),
        )


def insert_stream_event(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    event_type: str,
    trace_id: str | None,
    span_id: str | None,
    cursor_token: str,
    payload: dict[str, Any],
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO observe.stream_events (
                organization_id, project_id, event_type, trace_id, span_id,
                cursor_token, payload
            ) VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING id
            """,
            (
                org_id,
                project_id,
                event_type,
                trace_id,
                span_id,
                cursor_token,
                json.dumps(payload),
            ),
        )
        row = cur.fetchone()
    return int(row["id"]) if row else 0


def list_stream_events(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    after_id: int,
    limit: int,
    trace_id: str | None = None,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, event_type, trace_id, span_id, cursor_token, payload, created_at
            FROM observe.stream_events
            WHERE organization_id = %s
              AND project_id = %s
              AND id > %s
              AND (%s IS NULL OR trace_id = %s)
            ORDER BY id
            LIMIT %s
            """,
            (org_id, project_id, after_id, trace_id, trace_id, limit),
        )
        return list(cur.fetchall())


def manifests_missing_object(conn: PgConn, *, limit: int) -> list[IngestManifest]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, organization_id, project_id, agent_id, envelope_digest, object_key,
                   content_encoding, content_type, byte_size, span_count, rejected_span_count,
                   capture_mode, status, attempt_count, payload_retention_days,
                   payload_encryption_key_ref, envelope_kind, source_wire_digest,
                   log_record_count
            FROM observe.ingest_manifests
            WHERE status IN ('pending', 'processing', 'done')
            ORDER BY created_at
            LIMIT %s
            """,
            (limit,),
        )
        return [IngestManifest(**r) for r in cur.fetchall()]


def upsert_trace_metadata(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    trace_id: str,
    session_id: str | None,
    service_name: str | None,
    agent_id: str | None,
    agent_name: str | None,
    root_span_id: str | None,
    span_delta: int,
    is_malformed: bool,
    has_cycle: bool,
) -> None:
    now = datetime.now(UTC)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO observe.trace_metadata (
                organization_id, project_id, trace_id, session_id, service_name,
                agent_id, agent_name, root_span_id, span_count,
                is_malformed, has_cycle, first_seen_at, last_seen_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (organization_id, project_id, trace_id) DO UPDATE SET
                session_id = COALESCE(EXCLUDED.session_id, observe.trace_metadata.session_id),
                service_name = COALESCE(EXCLUDED.service_name, observe.trace_metadata.service_name),
                agent_id = COALESCE(EXCLUDED.agent_id, observe.trace_metadata.agent_id),
                agent_name = COALESCE(EXCLUDED.agent_name, observe.trace_metadata.agent_name),
                root_span_id = COALESCE(EXCLUDED.root_span_id, observe.trace_metadata.root_span_id),
                span_count = observe.trace_metadata.span_count + EXCLUDED.span_count,
                is_malformed = observe.trace_metadata.is_malformed OR EXCLUDED.is_malformed,
                has_cycle = observe.trace_metadata.has_cycle OR EXCLUDED.has_cycle,
                last_seen_at = EXCLUDED.last_seen_at
            """,
            (
                org_id,
                project_id,
                trace_id,
                session_id,
                service_name,
                agent_id,
                agent_name,
                root_span_id,
                span_delta,
                is_malformed,
                has_cycle,
                now,
                now,
            ),
        )


def count_pending_manifests(conn: PgConn) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*) AS c FROM observe.ingest_manifests
            WHERE status IN ('pending', 'processing')
            """
        )
        row = cur.fetchone()
    return int(row["c"]) if row else 0


def last_manifest_created_at(conn: PgConn) -> datetime | None:
    with conn.cursor() as cur:
        cur.execute("SELECT max(created_at) AS m FROM observe.ingest_manifests")
        row = cur.fetchone()
    if row is None or row["m"] is None:
        return None
    ts = row["m"]
    return ts if isinstance(ts, datetime) else datetime.fromisoformat(str(ts))


def insert_payload_ref_from_ingest(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    trace_id: str,
    span_id: str,
    field_name: str,
    digest: str,
    object_key: str,
    byte_size: int,
    encryption_key_ref: str,
    redaction_state: str,
    retention_days: int,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO observe.payload_refs (
                organization_id, project_id, trace_id, span_id, field_name,
                digest, object_key, media_type, byte_size, encryption_key_ref,
                redaction_state, payload_id, retention_deadline
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,gen_random_uuid(),
                now() + make_interval(days => %s)
            )
            ON CONFLICT (organization_id, project_id, trace_id, span_id, field_name, digest)
            DO NOTHING
            """,
            (
                org_id,
                project_id,
                trace_id,
                span_id,
                field_name,
                digest,
                object_key,
                "application/octet-stream",
                byte_size,
                encryption_key_ref,
                redaction_state,
                retention_days,
            ),
        )


def apply_log_identity(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    trace_id: str,
    log_record_uid: str,
    fingerprint: str,
    manifest_id: UUID,
) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT content_fingerprint FROM observe.log_record_idempotency
            WHERE organization_id = %s AND project_id = %s AND trace_id = %s
              AND log_record_uid = %s
            """,
            (org_id, project_id, trace_id, log_record_uid),
        )
        existing = cur.fetchone()
        if existing is None:
            cur.execute(
                """
                INSERT INTO observe.log_record_idempotency (
                    organization_id, project_id, trace_id, log_record_uid,
                    content_fingerprint, manifest_id
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (org_id, project_id, trace_id, log_record_uid, fingerprint, manifest_id),
            )
            return "inserted"
        if existing["content_fingerprint"] == fingerprint:
            return "duplicate"
        return "conflict"


def upsert_agent_execution(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    agg: dict[str, Any],
) -> None:
    now = datetime.now(UTC)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO observe.agent_executions (
                organization_id, project_id, execution_id, execution_type, trace_id,
                root_span_id, parent_execution_id, parent_trace_id, session_id,
                user_session_id, environment_id, agent_id,
                agent_version_id, agent_name, initiating_user_id, effective_actor_id,
                effective_actor_type, invocation_source, application_name, client_name,
                request_id, replay_of_execution_id, replay_reason, repository_ref,
                branch_ref, commit_sha, deployment_name, region_name, runtime_name,
                framework, framework_version, status, start_time, end_time, duration_ms,
                span_count, node_count, generation_count, tool_count, sdk_count,
                error_count, retry_count, input_tokens, output_tokens, total_cost_micros,
                sample_rate, sampling_decision,
                is_live, is_partial, is_malformed, has_cycle, has_late_data, capture_level,
                provider, sdk_name, mcp_server, mcp_tool_count, tags, first_seen_at, last_seen_at
            ) VALUES (
                %(org_id)s, %(project_id)s, %(execution_id)s, %(execution_type)s, %(trace_id)s,
                %(root_span_id)s, %(parent_execution_id)s, %(parent_trace_id)s, %(session_id)s,
                %(user_session_id)s, %(environment_id)s, %(agent_id)s, %(agent_version_id)s,
                %(agent_name)s, %(initiating_user_id)s, %(effective_actor_id)s,
                %(effective_actor_type)s, %(invocation_source)s, %(application_name)s,
                %(client_name)s, %(request_id)s, %(replay_of_execution_id)s, %(replay_reason)s,
                %(repository_ref)s, %(branch_ref)s, %(commit_sha)s, %(deployment_name)s,
                %(region_name)s, %(runtime_name)s, %(framework)s, %(framework_version)s,
                %(status)s, %(start_time)s,
                %(end_time)s, %(duration_ms)s, %(span_count)s, %(node_count)s,
                %(generation_count)s, %(tool_count)s, %(sdk_count)s, %(error_count)s,
                %(retry_count)s, %(input_tokens)s, %(output_tokens)s, %(total_cost_micros)s,
                %(sample_rate)s, %(sampling_decision)s,
                %(is_live)s, %(is_partial)s, %(is_malformed)s, %(has_cycle)s, %(has_late_data)s,
                %(capture_level)s, %(provider)s, %(sdk_name)s, %(mcp_server)s,
                %(mcp_tool_count)s, %(tags)s, %(now)s, %(now)s
            )
            ON CONFLICT (organization_id, project_id, execution_id) DO UPDATE SET
                execution_type = EXCLUDED.execution_type,
                trace_id = EXCLUDED.trace_id,
                root_span_id = COALESCE(
                    EXCLUDED.root_span_id, observe.agent_executions.root_span_id
                ),
                parent_execution_id = COALESCE(
                    EXCLUDED.parent_execution_id, observe.agent_executions.parent_execution_id
                ),
                parent_trace_id = COALESCE(
                    EXCLUDED.parent_trace_id, observe.agent_executions.parent_trace_id
                ),
                session_id = COALESCE(EXCLUDED.session_id, observe.agent_executions.session_id),
                user_session_id = COALESCE(
                    EXCLUDED.user_session_id, observe.agent_executions.user_session_id
                ),
                environment_id = COALESCE(
                    EXCLUDED.environment_id, observe.agent_executions.environment_id
                ),
                agent_id = COALESCE(EXCLUDED.agent_id, observe.agent_executions.agent_id),
                agent_version_id = COALESCE(
                    EXCLUDED.agent_version_id, observe.agent_executions.agent_version_id
                ),
                agent_name = COALESCE(EXCLUDED.agent_name, observe.agent_executions.agent_name),
                initiating_user_id = COALESCE(
                    EXCLUDED.initiating_user_id, observe.agent_executions.initiating_user_id
                ),
                effective_actor_id = COALESCE(
                    EXCLUDED.effective_actor_id, observe.agent_executions.effective_actor_id
                ),
                effective_actor_type = COALESCE(
                    EXCLUDED.effective_actor_type, observe.agent_executions.effective_actor_type
                ),
                invocation_source = COALESCE(
                    EXCLUDED.invocation_source, observe.agent_executions.invocation_source
                ),
                application_name = COALESCE(
                    EXCLUDED.application_name, observe.agent_executions.application_name
                ),
                client_name = COALESCE(EXCLUDED.client_name, observe.agent_executions.client_name),
                request_id = COALESCE(EXCLUDED.request_id, observe.agent_executions.request_id),
                replay_of_execution_id = COALESCE(
                    EXCLUDED.replay_of_execution_id,
                    observe.agent_executions.replay_of_execution_id
                ),
                replay_reason = COALESCE(
                    EXCLUDED.replay_reason, observe.agent_executions.replay_reason
                ),
                repository_ref = COALESCE(
                    EXCLUDED.repository_ref, observe.agent_executions.repository_ref
                ),
                branch_ref = COALESCE(EXCLUDED.branch_ref, observe.agent_executions.branch_ref),
                commit_sha = COALESCE(EXCLUDED.commit_sha, observe.agent_executions.commit_sha),
                deployment_name = COALESCE(
                    EXCLUDED.deployment_name, observe.agent_executions.deployment_name
                ),
                region_name = COALESCE(EXCLUDED.region_name, observe.agent_executions.region_name),
                runtime_name = COALESCE(
                    EXCLUDED.runtime_name, observe.agent_executions.runtime_name
                ),
                framework = COALESCE(EXCLUDED.framework, observe.agent_executions.framework),
                framework_version = COALESCE(
                    EXCLUDED.framework_version, observe.agent_executions.framework_version
                ),
                status = CASE
                    WHEN observe.agent_executions.is_live = false AND EXCLUDED.is_live = true
                    THEN observe.agent_executions.status
                    ELSE EXCLUDED.status
                END,
                start_time = CASE
                    WHEN observe.agent_executions.start_time IS NULL THEN EXCLUDED.start_time
                    WHEN EXCLUDED.start_time IS NULL THEN observe.agent_executions.start_time
                    ELSE LEAST(observe.agent_executions.start_time, EXCLUDED.start_time)
                END,
                end_time = CASE
                    WHEN observe.agent_executions.end_time IS NULL THEN EXCLUDED.end_time
                    WHEN EXCLUDED.end_time IS NULL THEN observe.agent_executions.end_time
                    ELSE GREATEST(observe.agent_executions.end_time, EXCLUDED.end_time)
                END,
                duration_ms = COALESCE(EXCLUDED.duration_ms, observe.agent_executions.duration_ms),
                span_count = GREATEST(observe.agent_executions.span_count, EXCLUDED.span_count),
                node_count = GREATEST(observe.agent_executions.node_count, EXCLUDED.node_count),
                generation_count = GREATEST(
                    observe.agent_executions.generation_count, EXCLUDED.generation_count
                ),
                tool_count = GREATEST(observe.agent_executions.tool_count, EXCLUDED.tool_count),
                sdk_count = GREATEST(observe.agent_executions.sdk_count, EXCLUDED.sdk_count),
                mcp_tool_count = GREATEST(
                    observe.agent_executions.mcp_tool_count, EXCLUDED.mcp_tool_count
                ),
                error_count = GREATEST(observe.agent_executions.error_count, EXCLUDED.error_count),
                retry_count = GREATEST(observe.agent_executions.retry_count, EXCLUDED.retry_count),
                input_tokens = GREATEST(
                    observe.agent_executions.input_tokens, EXCLUDED.input_tokens
                ),
                output_tokens = GREATEST(
                    observe.agent_executions.output_tokens, EXCLUDED.output_tokens
                ),
                total_cost_micros = GREATEST(
                    observe.agent_executions.total_cost_micros, EXCLUDED.total_cost_micros
                ),
                sample_rate = LEAST(observe.agent_executions.sample_rate, EXCLUDED.sample_rate),
                sampling_decision = CASE
                    WHEN observe.agent_executions.sampling_decision = 'sampled'
                      OR EXCLUDED.sampling_decision = 'sampled'
                    THEN 'sampled'
                    ELSE 'recorded'
                END,
                is_live = observe.agent_executions.is_live AND EXCLUDED.is_live,
                is_partial = EXCLUDED.is_partial OR observe.agent_executions.is_partial,
                is_malformed = EXCLUDED.is_malformed OR observe.agent_executions.is_malformed,
                has_cycle = EXCLUDED.has_cycle OR observe.agent_executions.has_cycle,
                has_late_data = EXCLUDED.has_late_data OR observe.agent_executions.has_late_data,
                capture_level = COALESCE(
                    EXCLUDED.capture_level, observe.agent_executions.capture_level
                ),
                provider = COALESCE(EXCLUDED.provider, observe.agent_executions.provider),
                sdk_name = COALESCE(EXCLUDED.sdk_name, observe.agent_executions.sdk_name),
                mcp_server = COALESCE(EXCLUDED.mcp_server, observe.agent_executions.mcp_server),
                tags = (
                    SELECT ARRAY(
                        SELECT DISTINCT value
                        FROM unnest(observe.agent_executions.tags || EXCLUDED.tags) AS value
                        ORDER BY value
                        LIMIT 32
                    )
                ),
                last_seen_at = EXCLUDED.last_seen_at
            """,
            {**agg, "org_id": org_id, "project_id": project_id, "now": now},
        )


_TERMINAL_EXECUTION_STATUSES = (
    "succeeded",
    "failed",
    "timed_out",
    "cancelled",
    "refused",
    "partial",
    "success",
    "error",
)


def refresh_observed_user_from_executions(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    user_id: str,
    activity_source: str | None = None,
) -> None:
    """Idempotent refresh of user counters from agent_executions (not incremental)."""
    now = datetime.now(UTC)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                count(*) FILTER (
                    WHERE status = ANY(%s) AND is_live = false
                ) AS execution_count,
                coalesce(sum(generation_count), 0) AS generation_count,
                coalesce(sum(tool_count), 0) AS tool_count,
                coalesce(sum(sdk_count), 0) AS sdk_count,
                coalesce(sum(mcp_tool_count), 0) AS mcp_tool_count,
                min(first_seen_at) AS first_seen_at
            FROM observe.agent_executions
            WHERE organization_id = %s AND project_id = %s AND initiating_user_id = %s
            """,
            (list(_TERMINAL_EXECUTION_STATUSES), org_id, project_id, user_id),
        )
        agg = cur.fetchone()
        if agg is None:
            return
        execution_count = int(agg["execution_count"] or 0)
        if execution_count == 0 and int(agg["generation_count"] or 0) == 0:
            return
        cur.execute(
            """
            INSERT INTO observe.observed_users (
                organization_id, project_id, user_id, execution_count, generation_count,
                tool_count, sdk_count, mcp_tool_count, first_seen_at, last_seen_at,
                activity_source
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (organization_id, project_id, user_id) DO UPDATE SET
                activity_source = COALESCE(
                    EXCLUDED.activity_source, observe.observed_users.activity_source
                ),
                execution_count = EXCLUDED.execution_count,
                generation_count = EXCLUDED.generation_count,
                tool_count = EXCLUDED.tool_count,
                sdk_count = EXCLUDED.sdk_count,
                mcp_tool_count = EXCLUDED.mcp_tool_count,
                first_seen_at = LEAST(
                    observe.observed_users.first_seen_at, EXCLUDED.first_seen_at
                ),
                last_seen_at = EXCLUDED.last_seen_at
            """,
            (
                org_id,
                project_id,
                user_id,
                execution_count,
                int(agg["generation_count"] or 0),
                int(agg["tool_count"] or 0),
                int(agg["sdk_count"] or 0),
                int(agg["mcp_tool_count"] or 0),
                agg["first_seen_at"] or now,
                now,
                activity_source,
            ),
        )


def resolve_user_identity(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    observed_value: str,
) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT user_id
            FROM observe.user_identity_bindings
            WHERE organization_id = %s AND project_id = %s AND binding_value = %s
            ORDER BY created_at
            LIMIT 1
            """,
            (org_id, project_id, observed_value),
        )
        row = cur.fetchone()
    return str(row["user_id"]) if row else observed_value


def upsert_user_identity_binding(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    user_id: str,
    binding_type: str,
    binding_value: str,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO observe.user_identity_bindings (
                organization_id, project_id, user_id, binding_type, binding_value
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (organization_id, project_id, binding_type, binding_value)
            DO UPDATE SET user_id = EXCLUDED.user_id
            RETURNING id, user_id, binding_type, binding_value, created_at
            """,
            (org_id, project_id, user_id, binding_type, binding_value),
        )
        row = cur.fetchone()
    assert row is not None
    return row


def refresh_session_from_executions(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    session_id: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                min(start_time) AS start_time,
                max(end_time) AS end_time,
                count(*) AS execution_count,
                coalesce(sum(span_count), 0) AS span_count,
                coalesce(sum(node_count), 0) AS node_count,
                coalesce(sum(generation_count), 0) AS generation_count,
                coalesce(sum(tool_count), 0) AS tool_count,
                coalesce(sum(sdk_count), 0) AS sdk_count,
                count(*) FILTER (
                    WHERE status IN ('failed', 'error', 'timed_out', 'refused')
                ) AS error_count,
                coalesce(sum(retry_count), 0) AS retry_count,
                coalesce(sum(total_cost_micros), 0) AS total_cost_micros,
                count(*) FILTER (WHERE replay_of_execution_id IS NOT NULL) AS replay_count,
                bool_or(is_live) AS has_live,
                array_agg(DISTINCT agent_id) FILTER (WHERE agent_id IS NOT NULL) AS agent_ids,
                array_agg(DISTINCT environment_id)
                    FILTER (WHERE environment_id IS NOT NULL) AS environment_ids,
                (array_agg(initiating_user_id ORDER BY start_time)
                    FILTER (WHERE initiating_user_id IS NOT NULL))[1] AS initiating_user_id,
                (array_agg(user_session_id ORDER BY start_time)
                    FILTER (WHERE user_session_id IS NOT NULL))[1] AS user_session_id
            FROM observe.agent_executions
            WHERE organization_id = %s AND project_id = %s AND session_id = %s
            """,
            (org_id, project_id, session_id),
        )
        agg = cur.fetchone()
        if agg is None or int(agg["execution_count"] or 0) == 0:
            return
        start_time = agg["start_time"]
        end_time = agg["end_time"]
        duration_ms = (
            max(0.0, (end_time - start_time).total_seconds() * 1000)
            if start_time is not None and end_time is not None
            else None
        )
        status = (
            "running"
            if bool(agg["has_live"])
            else "failed"
            if int(agg["error_count"] or 0) > 0
            else "succeeded"
        )
        now = datetime.now(UTC)
        cur.execute(
            """
            INSERT INTO observe.session_metadata (
                organization_id, project_id, session_id, user_session_id,
                initiating_user_id, trace_count, execution_count, status,
                environment_ids, agent_ids, start_time, end_time, duration_ms,
                span_count, node_count, generation_count, tool_count, sdk_count,
                error_count, retry_count, total_cost_micros, replay_count,
                first_seen_at, last_seen_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (organization_id, project_id, session_id) DO UPDATE SET
                user_session_id = COALESCE(
                    EXCLUDED.user_session_id, observe.session_metadata.user_session_id
                ),
                initiating_user_id = COALESCE(
                    EXCLUDED.initiating_user_id, observe.session_metadata.initiating_user_id
                ),
                trace_count = EXCLUDED.trace_count,
                execution_count = EXCLUDED.execution_count,
                status = EXCLUDED.status,
                environment_ids = EXCLUDED.environment_ids,
                agent_ids = EXCLUDED.agent_ids,
                start_time = EXCLUDED.start_time,
                end_time = EXCLUDED.end_time,
                duration_ms = EXCLUDED.duration_ms,
                span_count = EXCLUDED.span_count,
                node_count = EXCLUDED.node_count,
                generation_count = EXCLUDED.generation_count,
                tool_count = EXCLUDED.tool_count,
                sdk_count = EXCLUDED.sdk_count,
                error_count = EXCLUDED.error_count,
                retry_count = EXCLUDED.retry_count,
                total_cost_micros = EXCLUDED.total_cost_micros,
                replay_count = EXCLUDED.replay_count,
                last_seen_at = EXCLUDED.last_seen_at
            """,
            (
                org_id,
                project_id,
                session_id,
                agg["user_session_id"],
                agg["initiating_user_id"],
                int(agg["execution_count"]),
                int(agg["execution_count"]),
                status,
                agg["environment_ids"] or [],
                agg["agent_ids"] or [],
                start_time,
                end_time,
                duration_ms,
                int(agg["span_count"] or 0),
                int(agg["node_count"] or 0),
                int(agg["generation_count"] or 0),
                int(agg["tool_count"] or 0),
                int(agg["sdk_count"] or 0),
                int(agg["error_count"] or 0),
                int(agg["retry_count"] or 0),
                int(agg["total_cost_micros"] or 0),
                int(agg["replay_count"] or 0),
                start_time or now,
                now,
            ),
        )


def upsert_invocation_actor(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    actor_id: str,
    actor_type: str,
    initiating_user_id: str | None,
    invocation_source: str | None,
    application_name: str | None,
    client_name: str | None,
) -> None:
    allowed_type = (
        actor_type
        if actor_type
        in {
            "user",
            "agent",
            "service",
            "cli",
            "webhook",
            "scheduled_job",
            "mcp",
            "a2a",
        }
        else "unknown"
    )
    now = datetime.now(UTC)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO observe.invocation_actors (
                organization_id, project_id, actor_id, actor_type, initiating_user_id,
                invocation_source, application_name, client_name, execution_count,
                first_seen_at, last_seen_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1, %s, %s)
            ON CONFLICT (organization_id, project_id, actor_type, actor_id) DO UPDATE SET
                initiating_user_id = COALESCE(
                    EXCLUDED.initiating_user_id, observe.invocation_actors.initiating_user_id
                ),
                invocation_source = COALESCE(
                    EXCLUDED.invocation_source, observe.invocation_actors.invocation_source
                ),
                application_name = COALESCE(
                    EXCLUDED.application_name, observe.invocation_actors.application_name
                ),
                client_name = COALESCE(
                    EXCLUDED.client_name, observe.invocation_actors.client_name
                ),
                execution_count = (
                    SELECT count(*) FROM observe.agent_executions
                    WHERE organization_id = EXCLUDED.organization_id
                      AND project_id = EXCLUDED.project_id
                      AND effective_actor_id = EXCLUDED.actor_id
                      AND coalesce(effective_actor_type, 'unknown') = EXCLUDED.actor_type
                ),
                last_seen_at = EXCLUDED.last_seen_at
            """,
            (
                org_id,
                project_id,
                actor_id,
                allowed_type,
                initiating_user_id,
                invocation_source,
                application_name,
                client_name,
                now,
                now,
            ),
        )


def insert_execution_link(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    execution_id: str,
    link_type: str,
    target_execution_id: str | None = None,
    target_trace_id: str | None = None,
    target_span_id: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO observe.execution_links (
                organization_id, project_id, execution_id, link_type,
                target_execution_id, target_trace_id, target_span_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                org_id,
                project_id,
                execution_id,
                link_type,
                target_execution_id,
                target_trace_id,
                target_span_id,
            ),
        )


def list_execution_links(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    execution_id: str,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, execution_id, link_type, target_execution_id, target_trace_id,
                   target_span_id, created_at, 'outgoing' AS direction
            FROM observe.execution_links
            WHERE organization_id = %s AND project_id = %s AND execution_id = %s
            UNION ALL
            SELECT id, execution_id, link_type, target_execution_id, target_trace_id,
                   target_span_id, created_at, 'incoming' AS direction
            FROM observe.execution_links
            WHERE organization_id = %s AND project_id = %s AND target_execution_id = %s
            ORDER BY created_at, id
            """,
            (org_id, project_id, execution_id, org_id, project_id, execution_id),
        )
        return list(cur.fetchall())


def list_agent_executions_for_user(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    user_id: str,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT execution_id, execution_type, trace_id, root_span_id, parent_execution_id,
                   parent_trace_id, session_id, user_session_id, environment_id, status,
                   agent_id, agent_version_id, agent_name, initiating_user_id,
                   effective_actor_id, effective_actor_type, start_time, end_time, duration_ms,
                   invocation_source, application_name, client_name, request_id,
                   replay_of_execution_id, replay_reason, repository_ref, branch_ref,
                   commit_sha, deployment_name, region_name, runtime_name, framework,
                   framework_version,
                   span_count, node_count, generation_count, tool_count, sdk_count,
                   mcp_tool_count, error_count, retry_count, input_tokens, output_tokens,
                   total_cost_micros, is_live, is_partial, is_malformed, has_cycle,
                   has_late_data, capture_level, provider, sdk_name, mcp_server, tags
            FROM observe.agent_executions
            WHERE organization_id = %s AND project_id = %s AND initiating_user_id = %s
            ORDER BY start_time DESC NULLS LAST, last_seen_at DESC
            LIMIT %s OFFSET %s
            """,
            (org_id, project_id, user_id, limit, offset),
        )
        rows = list(cur.fetchall())
        cur.execute(
            """
            SELECT count(*) AS c FROM observe.agent_executions
            WHERE organization_id = %s AND project_id = %s AND initiating_user_id = %s
            """,
            (org_id, project_id, user_id),
        )
        count_row = cur.fetchone()
        total = int(count_row["c"]) if count_row else 0
    return rows, total


def insert_projection_outbox(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    execution_id: str,
    payload: dict[str, Any],
    event_type: str = "execution.terminal",
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO observe.projection_outbox (
                organization_id, project_id, execution_id, event_type, payload
            ) VALUES (%s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (organization_id, project_id, execution_id, event_type) DO NOTHING
            """,
            (org_id, project_id, execution_id, event_type, json.dumps(payload)),
        )


def claim_projection_outbox(
    conn: PgConn,
    *,
    worker_id: str,
    limit: int,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH candidates AS (
                SELECT id
                FROM observe.projection_outbox
                WHERE dispatched_at IS NULL
                  AND next_attempt_at <= now()
                  AND (locked_at IS NULL OR locked_at < now() - interval '5 minutes')
                ORDER BY created_at
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            )
            UPDATE observe.projection_outbox AS outbox
            SET locked_at = now(), lock_owner = %s
            FROM candidates
            WHERE outbox.id = candidates.id
            RETURNING outbox.*
            """,
            (limit, worker_id),
        )
        return list(cur.fetchall())


def mark_projection_dispatched(conn: PgConn, *, outbox_id: int, worker_id: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE observe.projection_outbox
            SET dispatched_at = now(), locked_at = NULL, lock_owner = NULL, last_error = NULL
            WHERE id = %s AND lock_owner = %s
            """,
            (outbox_id, worker_id),
        )


def mark_projection_retry(
    conn: PgConn,
    *,
    outbox_id: int,
    worker_id: str,
    error: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE observe.projection_outbox
            SET attempt_count = attempt_count + 1,
                next_attempt_at = now() + (
                    LEAST(300, power(2, LEAST(attempt_count, 8))) * interval '1 second'
                ),
                last_error = %s,
                locked_at = NULL,
                lock_owner = NULL
            WHERE id = %s AND lock_owner = %s
            """,
            (error[:2000], outbox_id, worker_id),
        )


def insert_payload_access_audit(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    payload_ref_id: UUID | None,
    trace_id: str | None,
    span_id: str | None,
    field_name: str | None,
    actor_subject: str,
    access_kind: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO observe.payload_access_audit (
                organization_id, project_id, payload_ref_id, trace_id, span_id,
                field_name, actor_subject, access_kind
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                org_id,
                project_id,
                payload_ref_id,
                trace_id,
                span_id,
                field_name,
                actor_subject,
                access_kind,
            ),
        )


def get_agent_execution(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    execution_id: str,
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM observe.agent_executions
            WHERE organization_id = %s AND project_id = %s AND execution_id = %s
            """,
            (org_id, project_id, execution_id),
        )
        return cur.fetchone()


def list_agent_executions(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    limit: int,
    offset: int,
    initiating_user_id: str | None = None,
    session_id: str | None = None,
    status: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    clauses = ["organization_id = %s", "project_id = %s"]
    params: list[Any] = [org_id, project_id]
    if initiating_user_id:
        clauses.append("initiating_user_id = %s")
        params.append(initiating_user_id)
    if session_id:
        clauses.append("session_id = %s")
        params.append(session_id)
    if status:
        clauses.append("status = %s")
        params.append(status)
    where = " AND ".join(clauses)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT execution_id, execution_type, trace_id, root_span_id, parent_execution_id,
                   parent_trace_id, session_id, user_session_id, environment_id, status,
                   agent_id, agent_version_id, agent_name, initiating_user_id,
                   effective_actor_id, effective_actor_type, start_time, end_time, duration_ms,
                   invocation_source, application_name, client_name, request_id,
                   replay_of_execution_id, replay_reason, repository_ref, branch_ref,
                   commit_sha, deployment_name, region_name, runtime_name, framework,
                   framework_version,
                   span_count, node_count, generation_count, tool_count, sdk_count,
                   mcp_tool_count, error_count, retry_count, input_tokens, output_tokens,
                   total_cost_micros, is_live, is_partial, is_malformed, has_cycle,
                   has_late_data, capture_level, provider, sdk_name, mcp_server, tags
            FROM observe.agent_executions
            WHERE {where}
            ORDER BY start_time DESC NULLS LAST, last_seen_at DESC
            LIMIT %s OFFSET %s
            """,
            (*params, limit, offset),
        )
        rows = list(cur.fetchall())
        cur.execute(f"SELECT count(*) AS c FROM observe.agent_executions WHERE {where}", params)
        count_row = cur.fetchone()
        total = int(count_row["c"]) if count_row else 0
    return rows, total


def list_sessions(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    limit: int,
    offset: int,
    initiating_user_id: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    clauses = ["organization_id = %s", "project_id = %s"]
    params: list[Any] = [org_id, project_id]
    if initiating_user_id:
        clauses.append("initiating_user_id = %s")
        params.append(initiating_user_id)
    where = " AND ".join(clauses)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT session_id, user_session_id, display_name, initiating_user_id, status,
                   environment_ids, agent_ids, start_time, end_time, duration_ms,
                   trace_count, execution_count, span_count, node_count,
                   generation_count, tool_count, sdk_count, error_count, retry_count,
                   total_cost_micros, replay_count, first_seen_at, last_seen_at
            FROM observe.session_metadata
            WHERE {where}
            ORDER BY coalesce(start_time, first_seen_at) DESC
            LIMIT %s OFFSET %s
            """,
            (*params, limit, offset),
        )
        rows = list(cur.fetchall())
        cur.execute(
            f"""
            SELECT count(*) AS c FROM observe.session_metadata
            WHERE {where}
            """,
            params,
        )
        count_row = cur.fetchone()
    return rows, int(count_row["c"]) if count_row else 0


def get_session(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    session_id: str,
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT session_id, user_session_id, display_name, initiating_user_id, status,
                   environment_ids, agent_ids, start_time, end_time, duration_ms,
                   trace_count, execution_count, span_count, node_count,
                   generation_count, tool_count, sdk_count, error_count, retry_count,
                   total_cost_micros, replay_count, first_seen_at, last_seen_at
            FROM observe.session_metadata
            WHERE organization_id = %s AND project_id = %s AND session_id = %s
            """,
            (org_id, project_id, session_id),
        )
        return cur.fetchone()


def list_session_executions(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    session_id: str,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT *
            FROM observe.agent_executions
            WHERE organization_id = %s AND project_id = %s AND session_id = %s
            ORDER BY start_time, first_seen_at
            LIMIT %s OFFSET %s
            """,
            (org_id, project_id, session_id, limit, offset),
        )
        rows = list(cur.fetchall())
        cur.execute(
            """
            SELECT count(*) AS c FROM observe.agent_executions
            WHERE organization_id = %s AND project_id = %s AND session_id = %s
            """,
            (org_id, project_id, session_id),
        )
        count_row = cur.fetchone()
    return rows, int(count_row["c"]) if count_row else 0


def get_observed_user(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    user_id: str,
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT user_id, display_label, team, activity_source, execution_count,
                   generation_count, tool_count, sdk_count, mcp_tool_count,
                   first_seen_at, last_seen_at
            FROM observe.observed_users
            WHERE organization_id = %s AND project_id = %s AND user_id = %s
            """,
            (org_id, project_id, user_id),
        )
        return cur.fetchone()


def list_observed_users(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    limit: int,
    offset: int,
) -> tuple[list[dict[str, Any]], int]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT user_id, display_label, team, activity_source, execution_count,
                   generation_count, tool_count, sdk_count, mcp_tool_count,
                   first_seen_at, last_seen_at
            FROM observe.observed_users
            WHERE organization_id = %s AND project_id = %s
            ORDER BY last_seen_at DESC
            LIMIT %s OFFSET %s
            """,
            (org_id, project_id, limit, offset),
        )
        rows = list(cur.fetchall())
        cur.execute(
            """
            SELECT count(*) AS c FROM observe.observed_users
            WHERE organization_id = %s AND project_id = %s
            """,
            (org_id, project_id),
        )
        count_row = cur.fetchone()
        total = int(count_row["c"]) if count_row else 0
    return rows, total


def get_payload_ref(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    payload_id: UUID,
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, payload_id, trace_id, span_id, field_name, digest, media_type,
                   byte_size, object_key, encryption_key_ref, redaction_state,
                   retention_deadline, legal_hold, legal_hold_reason, legal_hold_actor,
                   legal_hold_at, retention_deleted_at
            FROM observe.payload_refs
            WHERE organization_id = %s AND project_id = %s
              AND (payload_id = %s OR id = %s)
            LIMIT 1
            """,
            (org_id, project_id, payload_id, payload_id),
        )
        return cur.fetchone()


def set_payload_legal_hold(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    payload_id: UUID,
    enabled: bool,
    actor_subject: str,
    reason: str | None,
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE observe.payload_refs
            SET legal_hold = %s,
                legal_hold_reason = CASE WHEN %s THEN %s ELSE NULL END,
                legal_hold_actor = CASE WHEN %s THEN %s ELSE NULL END,
                legal_hold_at = CASE WHEN %s THEN now() ELSE NULL END
            WHERE organization_id = %s AND project_id = %s
              AND (payload_id = %s OR id = %s)
              AND retention_deleted_at IS NULL
            RETURNING id, payload_id, trace_id, span_id, field_name, digest, media_type,
                      byte_size, object_key, encryption_key_ref, redaction_state,
                      retention_deadline, legal_hold, legal_hold_reason, legal_hold_actor,
                      legal_hold_at, retention_deleted_at
            """,
            (
                enabled,
                enabled,
                reason,
                enabled,
                actor_subject,
                enabled,
                org_id,
                project_id,
                payload_id,
                payload_id,
            ),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute(
            """
            INSERT INTO observe.payload_policy_audit (
                organization_id, project_id, payload_id, action, actor_subject, reason
            ) VALUES (%s,%s,%s,%s,%s,%s)
            """,
            (
                org_id,
                project_id,
                row.get("payload_id") or row["id"],
                "legal_hold_enabled" if enabled else "legal_hold_released",
                actor_subject,
                reason,
            ),
        )
        return row


def claim_expired_payload_objects(
    conn: PgConn,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.id, p.payload_id, p.organization_id, p.project_id, p.object_key
            FROM observe.payload_refs p
            WHERE p.object_key <> ''
              AND p.retention_deleted_at IS NULL
              AND p.legal_hold = false
              AND p.retention_deadline IS NOT NULL
              AND p.retention_deadline <= now()
              AND NOT EXISTS (
                  SELECT 1
                  FROM observe.payload_refs active
                  WHERE active.organization_id = p.organization_id
                    AND active.project_id = p.project_id
                    AND active.object_key = p.object_key
                    AND active.retention_deleted_at IS NULL
                    AND (
                        active.legal_hold = true
                        OR active.retention_deadline IS NULL
                        OR active.retention_deadline > now()
                    )
              )
            ORDER BY p.retention_deadline, p.id
            FOR UPDATE OF p SKIP LOCKED
            LIMIT %s
            """,
            (limit,),
        )
        return list(cur.fetchall())


def mark_payload_object_retention_deleted(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    object_key: str,
) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE observe.payload_refs
            SET object_key = '', retention_deleted_at = now(), redaction_state = 'expired'
            WHERE organization_id = %s AND project_id = %s AND object_key = %s
              AND legal_hold = false AND retention_deleted_at IS NULL
              AND retention_deadline IS NOT NULL AND retention_deadline <= now()
            RETURNING payload_id
            """,
            (org_id, project_id, object_key),
        )
        rows = list(cur.fetchall())
        for row in rows:
            cur.execute(
                """
                INSERT INTO observe.payload_policy_audit (
                    organization_id, project_id, payload_id, action, actor_subject
                ) VALUES (%s,%s,%s,'retention_deleted','observe-retention-worker')
                """,
                (org_id, project_id, row["payload_id"]),
            )
        return len(rows)


def execution_analytics(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                count(*) AS execution_count,
                count(DISTINCT session_id) FILTER (WHERE session_id IS NOT NULL) AS session_count,
                count(DISTINCT initiating_user_id)
                    FILTER (WHERE initiating_user_id IS NOT NULL) AS user_count,
                count(DISTINCT agent_id) FILTER (WHERE agent_id IS NOT NULL) AS agent_count,
                count(*) FILTER (WHERE status = 'succeeded') AS success_count,
                count(*) FILTER (WHERE status = 'failed') AS failed_count,
                avg(duration_ms) FILTER (WHERE duration_ms IS NOT NULL) AS avg_duration_ms,
                percentile_cont(0.50) WITHIN GROUP (ORDER BY duration_ms)
                    FILTER (WHERE duration_ms IS NOT NULL) AS p50_duration_ms,
                percentile_cont(0.90) WITHIN GROUP (ORDER BY duration_ms)
                    FILTER (WHERE duration_ms IS NOT NULL) AS p90_duration_ms,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)
                    FILTER (WHERE duration_ms IS NOT NULL) AS p95_duration_ms,
                percentile_cont(0.99) WITHIN GROUP (ORDER BY duration_ms)
                    FILTER (WHERE duration_ms IS NOT NULL) AS p99_duration_ms,
                coalesce(sum(input_tokens), 0) AS input_tokens,
                coalesce(sum(output_tokens), 0) AS output_tokens,
                coalesce(sum(total_cost_micros), 0) AS total_cost_micros,
                coalesce(sum(error_count), 0) AS error_count,
                coalesce(sum(retry_count), 0) AS retry_count,
                min(start_time) AS population_start,
                max(coalesce(end_time, start_time)) AS population_end,
                min(sample_rate) AS minimum_sample_rate,
                bool_or(sampling_decision <> 'recorded') AS has_sampling
            FROM observe.agent_executions
            WHERE organization_id = %s AND project_id = %s
            """,
            (org_id, project_id),
        )
        row = cur.fetchone() or {}
        cur.execute(
            """
            SELECT count(*) AS actor_count
            FROM observe.invocation_actors
            WHERE organization_id = %s AND project_id = %s
            """,
            (org_id, project_id),
        )
        actor = cur.fetchone()
    row["actor_count"] = int(actor["actor_count"]) if actor else 0
    return row


def execution_breakdown(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    dimension: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    expressions = {
        "agent": "coalesce(nullif(agent_name, ''), nullif(agent_id, ''), 'Unknown')",
        "environment": "coalesce(nullif(environment_id, ''), 'Unknown')",
        "user": "coalesce(nullif(initiating_user_id, ''), 'Unattributed')",
        "source": "coalesce(nullif(invocation_source, ''), 'Unknown')",
        "framework": "coalesce(nullif(framework, ''), 'Unknown')",
        "status": "coalesce(nullif(status, ''), 'unknown')",
    }
    expression = expressions.get(dimension)
    if expression is None:
        raise ValueError(f"unsupported analytics dimension: {dimension}")
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT
                {expression} AS label,
                count(*) AS count,
                count(*) FILTER (WHERE status = 'failed') AS failed_count,
                avg(duration_ms) FILTER (WHERE duration_ms IS NOT NULL) AS avg_duration_ms,
                coalesce(sum(total_cost_micros), 0) AS total_cost_micros
            FROM observe.agent_executions
            WHERE organization_id = %s AND project_id = %s
            GROUP BY label
            ORDER BY count DESC, label
            LIMIT %s
            """,
            (org_id, project_id, limit),
        )
        return list(cur.fetchall())


def observe_pipeline_metrics(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                count(*) FILTER (WHERE status = 'pending') AS pending_manifests,
                count(*) FILTER (WHERE status = 'processing') AS processing_manifests,
                count(*) FILTER (WHERE status = 'quarantined') AS quarantined_manifests,
                count(*) FILTER (
                    WHERE status = 'done' AND created_at >= now() - interval '24 hours'
                ) AS processed_24h,
                max(created_at) AS last_manifest_at
            FROM observe.ingest_manifests
            WHERE organization_id = %s AND project_id = %s
            """,
            (org_id, project_id),
        )
        metrics = cur.fetchone() or {}
        cur.execute(
            """
            SELECT count(*) AS pending_projections
            FROM observe.projection_outbox
            WHERE organization_id = %s AND project_id = %s AND dispatched_at IS NULL
            """,
            (org_id, project_id),
        )
        projection = cur.fetchone()
        cur.execute(
            """
            SELECT
                count(*) FILTER (WHERE is_partial) AS partial_executions,
                count(*) FILTER (WHERE is_malformed OR has_cycle) AS malformed_executions,
                count(*) FILTER (WHERE has_late_data) AS late_executions
            FROM observe.agent_executions
            WHERE organization_id = %s AND project_id = %s
            """,
            (org_id, project_id),
        )
        integrity = cur.fetchone() or {}
    metrics.update(integrity)
    metrics["pending_projections"] = int(projection["pending_projections"]) if projection else 0
    return metrics


def get_sampling_policy(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT organization_id, project_id, head_sample_rate, tail_keep_errors,
                   tail_keep_retries, tail_keep_high_latency, high_latency_ms,
                   max_traces_per_minute, revision, updated_by, updated_at
            FROM observe.sampling_policies
            WHERE organization_id = %s AND project_id = %s
            """,
            (org_id, project_id),
        )
        row = cur.fetchone()
    if row:
        return row
    return {
        "organization_id": org_id,
        "project_id": project_id,
        "head_sample_rate": 1.0,
        "tail_keep_errors": True,
        "tail_keep_retries": True,
        "tail_keep_high_latency": True,
        "high_latency_ms": 10000.0,
        "max_traces_per_minute": None,
        "revision": 0,
        "updated_by": None,
        "updated_at": None,
    }


def upsert_sampling_policy(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    head_sample_rate: float,
    tail_keep_errors: bool,
    tail_keep_retries: bool,
    tail_keep_high_latency: bool,
    high_latency_ms: float,
    max_traces_per_minute: int | None,
    updated_by: str | None,
) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO observe.sampling_policies (
                organization_id, project_id, head_sample_rate, tail_keep_errors,
                tail_keep_retries, tail_keep_high_latency, high_latency_ms,
                max_traces_per_minute, updated_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (organization_id, project_id) DO UPDATE SET
                head_sample_rate = EXCLUDED.head_sample_rate,
                tail_keep_errors = EXCLUDED.tail_keep_errors,
                tail_keep_retries = EXCLUDED.tail_keep_retries,
                tail_keep_high_latency = EXCLUDED.tail_keep_high_latency,
                high_latency_ms = EXCLUDED.high_latency_ms,
                max_traces_per_minute = EXCLUDED.max_traces_per_minute,
                revision = observe.sampling_policies.revision + 1,
                updated_by = EXCLUDED.updated_by,
                updated_at = now()
            RETURNING organization_id, project_id, head_sample_rate, tail_keep_errors,
                      tail_keep_retries, tail_keep_high_latency, high_latency_ms,
                      max_traces_per_minute, revision, updated_by, updated_at
            """,
            (
                org_id,
                project_id,
                head_sample_rate,
                tail_keep_errors,
                tail_keep_retries,
                tail_keep_high_latency,
                high_latency_ms,
                max_traces_per_minute,
                updated_by,
            ),
        )
        row = cur.fetchone()
    if row is None:
        raise RuntimeError("sampling policy upsert returned no row")
    return row
