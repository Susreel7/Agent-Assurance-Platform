"""SQL for evaluate schema — only module with raw SQL."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from evaluate.db.postgres import PgConn


def _json(v: Any) -> str:
    return json.dumps(v, separators=(",", ":"))


def insert_dataset(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    dataset_key: str,
    display_name: str,
    description: str,
    tags: list[Any],
    actor: str,
) -> UUID:
    ds_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluate.datasets
                (id, organization_id, project_id, dataset_key, display_name, description, tags, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s)
            """,
            (ds_id, org_id, project_id, dataset_key, display_name, description, _json(tags), actor),
        )
    return ds_id


def get_dataset_by_key(
    conn: PgConn, org_id: UUID, project_id: UUID, dataset_key: str
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM evaluate.datasets
            WHERE organization_id = %s AND project_id = %s AND dataset_key = %s
            """,
            (org_id, project_id, dataset_key),
        )
        return cur.fetchone()


def list_datasets(
    conn: PgConn,
    org_id: UUID,
    project_id: UUID,
    *,
    limit: int,
    cursor_created_at: datetime | None = None,
    cursor_id: UUID | None = None,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        if cursor_created_at and cursor_id:
            cur.execute(
                """
                SELECT * FROM evaluate.datasets
                WHERE organization_id = %s AND project_id = %s
                  AND (created_at, id) < (%s, %s)
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (org_id, project_id, cursor_created_at, cursor_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT * FROM evaluate.datasets
                WHERE organization_id = %s AND project_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (org_id, project_id, limit),
            )
        return list(cur.fetchall())


def insert_dataset_revision(
    conn: PgConn,
    *,
    dataset_id: UUID,
    org_id: UUID,
    project_id: UUID,
    revision_number: int,
    manifest_digest: str,
    actor: str,
) -> UUID:
    rev_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluate.dataset_revisions
                (id, dataset_id, organization_id, project_id, revision_number, manifest_digest, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (rev_id, dataset_id, org_id, project_id, revision_number, manifest_digest, actor),
        )
    return rev_id


def latest_dataset_revision_number(conn: PgConn, dataset_id: UUID) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(MAX(revision_number), 0) AS n
            FROM evaluate.dataset_revisions WHERE dataset_id = %s
            """,
            (dataset_id,),
        )
        row = cur.fetchone()
        return int(row["n"]) if row else 0


def get_dataset_revision(conn: PgConn, org_id: UUID, revision_id: UUID) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM evaluate.dataset_revisions
            WHERE id = %s AND organization_id = %s
            """,
            (revision_id, org_id),
        )
        return cur.fetchone()


def insert_example(
    conn: PgConn,
    *,
    revision_id: UUID,
    org_id: UUID,
    project_id: UUID,
    example_key: str,
    ordinal: int,
    split_name: str,
    tags: list[Any],
    metadata: dict[str, Any],
    content_digest: str,
    source_trace_id: str | None,
    dedupe_digest: str | None,
    has_encrypted_payload: bool,
    input_inline: dict[str, Any] | None,
    reference_inline: dict[str, Any] | None,
    ciphertext: bytes | None,
    encryption_key_ref: str | None,
    input_object_ref: str | None,
    reference_object_ref: str | None,
) -> UUID:
    ex_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluate.examples
                (id, dataset_revision_id, organization_id, project_id, example_key, ordinal,
                 split_name, tags, metadata, content_digest, source_trace_id, dedupe_digest,
                 has_encrypted_payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s)
            """,
            (
                ex_id,
                revision_id,
                org_id,
                project_id,
                example_key,
                ordinal,
                split_name,
                _json(tags),
                _json(metadata),
                content_digest,
                source_trace_id,
                dedupe_digest,
                has_encrypted_payload,
            ),
        )
        cur.execute(
            """
            INSERT INTO evaluate.example_bodies
                (example_id, organization_id, input_inline, reference_output_inline,
                 input_object_ref, reference_output_object_ref, encryption_key_ref, ciphertext)
            VALUES (%s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, %s)
            """,
            (
                ex_id,
                org_id,
                _json(input_inline) if input_inline is not None else None,
                _json(reference_inline) if reference_inline is not None else None,
                input_object_ref,
                reference_object_ref,
                encryption_key_ref,
                ciphertext,
            ),
        )
        cur.execute(
            """
            UPDATE evaluate.dataset_revisions
            SET example_count = example_count + 1
            WHERE id = %s
            """,
            (revision_id,),
        )
    return ex_id


def list_examples_for_revision(
    conn: PgConn, org_id: UUID, revision_id: UUID, *, split: str | None = None
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        if split:
            cur.execute(
                """
                SELECT e.*, b.input_inline, b.reference_output_inline,
                       b.input_object_ref, b.reference_output_object_ref,
                       b.encryption_key_ref, b.ciphertext IS NOT NULL AS has_ciphertext
                FROM evaluate.examples e
                JOIN evaluate.example_bodies b ON b.example_id = e.id
                WHERE e.dataset_revision_id = %s AND e.organization_id = %s AND e.split_name = %s
                ORDER BY e.ordinal ASC
                """,
                (revision_id, org_id, split),
            )
        else:
            cur.execute(
                """
                SELECT e.*, b.input_inline, b.reference_output_inline,
                       b.input_object_ref, b.reference_output_object_ref,
                       b.encryption_key_ref, b.ciphertext IS NOT NULL AS has_ciphertext
                FROM evaluate.examples e
                JOIN evaluate.example_bodies b ON b.example_id = e.id
                WHERE e.dataset_revision_id = %s AND e.organization_id = %s
                ORDER BY e.ordinal ASC
                """,
                (revision_id, org_id),
            )
        return list(cur.fetchall())


def get_example_ciphertext(conn: PgConn, org_id: UUID, example_id: UUID) -> bytes | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT ciphertext FROM evaluate.example_bodies
            WHERE example_id = %s AND organization_id = %s
            """,
            (example_id, org_id),
        )
        row = cur.fetchone()
        if not row:
            return None
        raw = row["ciphertext"]
        return bytes(raw) if raw is not None else None


def insert_evaluator(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    evaluator_key: str,
    display_name: str,
    kind: str,
    actor: str,
) -> UUID:
    ev_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluate.evaluators
                (id, organization_id, project_id, evaluator_key, display_name, kind, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (ev_id, org_id, project_id, evaluator_key, display_name, kind, actor),
        )
    return ev_id


def get_evaluator_by_key(
    conn: PgConn, org_id: UUID, project_id: UUID, evaluator_key: str
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM evaluate.evaluators
            WHERE organization_id = %s AND project_id = %s AND evaluator_key = %s
            """,
            (org_id, project_id, evaluator_key),
        )
        return cur.fetchone()


def insert_evaluator_revision(
    conn: PgConn,
    *,
    evaluator_id: UUID,
    org_id: UUID,
    project_id: UUID,
    revision_number: int,
    config: dict[str, Any],
    config_digest: str,
    actor: str,
) -> UUID:
    rev_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluate.evaluator_revisions
                (id, evaluator_id, organization_id, project_id, revision_number, config, config_digest, created_by)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            """,
            (
                rev_id,
                evaluator_id,
                org_id,
                project_id,
                revision_number,
                _json(config),
                config_digest,
                actor,
            ),
        )
    return rev_id


def get_evaluator_revision(conn: PgConn, org_id: UUID, revision_id: UUID) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT r.*, e.kind, e.evaluator_key
            FROM evaluate.evaluator_revisions r
            JOIN evaluate.evaluators e ON e.id = r.evaluator_id
            WHERE r.id = %s AND r.organization_id = %s
            """,
            (revision_id, org_id),
        )
        return cur.fetchone()


def latest_evaluator_revision_number(conn: PgConn, evaluator_id: UUID) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(MAX(revision_number), 0) AS n
            FROM evaluate.evaluator_revisions WHERE evaluator_id = %s
            """,
            (evaluator_id,),
        )
        row = cur.fetchone()
        return int(row["n"]) if row else 0


def insert_experiment(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    experiment_key: str,
    display_name: str,
    dataset_revision_id: UUID,
    baseline_experiment_id: UUID | None,
    spec: dict[str, Any],
    spec_digest: str,
    seed: int,
    repetitions: int,
    concurrency: int,
    budget_usd: float | None,
    actor: str,
) -> UUID:
    exp_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluate.experiments
                (id, organization_id, project_id, experiment_key, display_name, status,
                 dataset_revision_id, baseline_experiment_id, spec, spec_digest, seed,
                 repetitions, concurrency, budget_usd, created_by)
            VALUES (%s, %s, %s, %s, %s, 'draft', %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s)
            """,
            (
                exp_id,
                org_id,
                project_id,
                experiment_key,
                display_name,
                dataset_revision_id,
                baseline_experiment_id,
                _json(spec),
                spec_digest,
                seed,
                repetitions,
                concurrency,
                budget_usd,
                actor,
            ),
        )
    return exp_id


def get_experiment(
    conn: PgConn, org_id: UUID, project_id: UUID, experiment_id: UUID
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM evaluate.experiments
            WHERE id = %s AND organization_id = %s AND project_id = %s
            """,
            (experiment_id, org_id, project_id),
        )
        return cur.fetchone()


def update_experiment_status(
    conn: PgConn,
    org_id: UUID,
    experiment_id: UUID,
    status: str,
    *,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    cancelled_at: datetime | None = None,
    progress: dict[str, Any] | None = None,
    aggregates: dict[str, Any] | None = None,
) -> None:
    sets = ["status = %s"]
    params: list[Any] = [status]
    if started_at is not None:
        sets.append("started_at = %s")
        params.append(started_at)
    if finished_at is not None:
        sets.append("finished_at = %s")
        params.append(finished_at)
    if cancelled_at is not None:
        sets.append("cancelled_at = %s")
        params.append(cancelled_at)
    if progress is not None:
        sets.append("progress = %s::jsonb")
        params.append(_json(progress))
    if aggregates is not None:
        sets.append("aggregates = %s::jsonb")
        params.append(_json(aggregates))
    params.extend([experiment_id, org_id])
    with conn.cursor() as cur:
        cur.execute(
            f"UPDATE evaluate.experiments SET {', '.join(sets)} WHERE id = %s AND organization_id = %s",
            params,
        )


def insert_experiment_result_rows(
    conn: PgConn,
    rows: list[tuple[UUID, UUID, UUID, UUID, int]],
) -> None:
    with conn.cursor() as cur:
        for exp_id, org_id, project_id, example_id, rep in rows:
            cur.execute(
                """
                INSERT INTO evaluate.experiment_results
                    (id, experiment_id, organization_id, project_id, example_id, repetition_index, status)
                VALUES (%s, %s, %s, %s, %s, %s, 'pending')
                ON CONFLICT DO NOTHING
                """,
                (uuid.uuid4(), exp_id, org_id, project_id, example_id, rep),
            )


def claim_experiment_results(
    conn: PgConn,
    experiment_id: UUID,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM evaluate.experiment_results
            WHERE experiment_id = %s AND status = 'pending'
            ORDER BY created_at ASC
            LIMIT %s
            FOR UPDATE SKIP LOCKED
            """,
            (experiment_id, limit),
        )
        rows = list(cur.fetchall())
        for row in rows:
            cur.execute(
                """
                UPDATE evaluate.experiment_results
                SET status = 'running', updated_at = now()
                WHERE id = %s
                """,
                (row["id"],),
            )
        return rows


def complete_experiment_result(
    conn: PgConn,
    result_id: UUID,
    *,
    status: str,
    trace_id: str | None,
    span_id: str | None = None,
    trace_link: dict[str, Any] | None = None,
    output_digest: str | None,
    latency_ms: int | None,
    cost_usd: float | None,
    scores: dict[str, Any],
    error_message: str | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE evaluate.experiment_results
            SET status = %s, trace_id = %s, span_id = %s, trace_link = %s::jsonb,
                output_digest = %s, latency_ms = %s,
                cost_usd = %s, scores = %s::jsonb, error_message = %s, updated_at = now()
            WHERE id = %s
            """,
            (
                status,
                trace_id,
                span_id,
                _json(trace_link or {}),
                output_digest,
                latency_ms,
                cost_usd,
                _json(scores),
                error_message,
                result_id,
            ),
        )


def list_experiment_results(
    conn: PgConn, org_id: UUID, experiment_id: UUID
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM evaluate.experiment_results
            WHERE experiment_id = %s AND organization_id = %s
            ORDER BY created_at ASC
            """,
            (experiment_id, org_id),
        )
        return list(cur.fetchall())


def cancel_pending_experiment_results(conn: PgConn, experiment_id: UUID) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE evaluate.experiment_results
            SET status = 'cancelled', updated_at = now()
            WHERE experiment_id = %s AND status IN ('pending', 'running')
            """,
            (experiment_id,),
        )
        return cur.rowcount


def enqueue_job(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    job_type: str,
    payload: dict[str, Any],
    idempotency_key: str,
    max_attempts: int,
) -> UUID | None:
    job_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluate.jobs
                (id, organization_id, project_id, job_type, status, payload, idempotency_key, max_attempts)
            VALUES (%s, %s, %s, %s, 'pending', %s::jsonb, %s, %s)
            ON CONFLICT (organization_id, project_id, idempotency_key) DO NOTHING
            RETURNING id
            """,
            (job_id, org_id, project_id, job_type, _json(payload), idempotency_key, max_attempts),
        )
        row = cur.fetchone()
        return row["id"] if row else None


def claim_job(conn: PgConn, *, owner: str, lease_seconds: int) -> dict[str, Any] | None:
    now = datetime.now(UTC)
    lease_until = now + timedelta(seconds=lease_seconds)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM evaluate.jobs
            WHERE status IN ('pending', 'leased')
              AND (lease_until IS NULL OR lease_until < %s)
              AND attempts < max_attempts
            ORDER BY created_at ASC
            LIMIT 1
            FOR UPDATE SKIP LOCKED
            """,
            (now,),
        )
        row = cur.fetchone()
        if not row:
            return None
        cur.execute(
            """
            UPDATE evaluate.jobs
            SET status = 'leased', lease_owner = %s, lease_until = %s,
                attempts = attempts + 1, updated_at = now()
            WHERE id = %s
            """,
            (owner, lease_until, row["id"]),
        )
        return row


def finish_job(conn: PgConn, job_id: UUID, *, status: str, error: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE evaluate.jobs
            SET status = %s, last_error = %s, completed_at = now(), updated_at = now(), lease_until = NULL
            WHERE id = %s
            """,
            (status, error, job_id),
        )


def requeue_expired_jobs(conn: PgConn) -> int:
    now = datetime.now(UTC)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE evaluate.jobs
            SET status = 'pending', lease_owner = NULL, lease_until = NULL, updated_at = now()
            WHERE status = 'leased' AND lease_until < %s AND attempts < max_attempts
            """,
            (now,),
        )
        return cur.rowcount


def insert_score(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    target_type: str,
    target_id: str,
    name: str,
    value_type: str,
    value_numeric: float | None,
    value_boolean: bool | None,
    value_categorical: str | None,
    source: str,
    evaluator_revision_id: UUID | None,
    explanation: str | None,
    metadata: dict[str, Any],
    supersedes_score_id: UUID | None,
    actor: str,
) -> UUID:
    score_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluate.scores
                (id, organization_id, project_id, target_type, target_id, name, value_type,
                 value_numeric, value_boolean, value_categorical, source, evaluator_revision_id,
                 explanation, metadata, supersedes_score_id, created_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            """,
            (
                score_id,
                org_id,
                project_id,
                target_type,
                target_id,
                name,
                value_type,
                value_numeric,
                value_boolean,
                value_categorical,
                source,
                evaluator_revision_id,
                explanation,
                _json(metadata),
                supersedes_score_id,
                actor,
            ),
        )
    return score_id


def record_score_correction(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    original_score_id: UUID,
    corrected_score_id: UUID,
    reason: str,
    actor: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluate.score_corrections
                (id, organization_id, project_id, original_score_id, corrected_score_id, reason, actor)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                uuid.uuid4(),
                org_id,
                project_id,
                original_score_id,
                corrected_score_id,
                reason,
                actor,
            ),
        )


def list_scores_for_target(
    conn: PgConn, org_id: UUID, project_id: UUID, target_type: str, target_id: str
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM evaluate.scores
            WHERE organization_id = %s AND project_id = %s AND target_type = %s AND target_id = %s
            ORDER BY created_at DESC
            """,
            (org_id, project_id, target_type, target_id),
        )
        return list(cur.fetchall())


def insert_online_rule(
    conn: PgConn, *, org_id: UUID, project_id: UUID, rule_key: str, payload: dict[str, Any]
) -> UUID:
    rule_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluate.online_rules
                (id, organization_id, project_id, rule_key, filter, sample_rate, sample_hash_salt,
                 evaluator_revision_ids, budget_usd, max_concurrency, actions)
            VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                rule_id,
                org_id,
                project_id,
                rule_key,
                _json(payload.get("filter", {})),
                payload.get("sample_rate", 0.01),
                payload.get("sample_hash_salt", rule_key),
                payload.get("evaluator_revision_ids", []),
                payload.get("budget_usd"),
                payload.get("max_concurrency", 2),
                _json(payload.get("actions", [])),
            ),
        )
        cur.execute(
            """
            INSERT INTO evaluate.online_rule_cursors (rule_id, organization_id, project_id)
            VALUES (%s, %s, %s)
            """,
            (rule_id, org_id, project_id),
        )
    return rule_id


def get_online_rule(
    conn: PgConn, org_id: UUID, project_id: UUID, rule_id: UUID
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM evaluate.online_rules
            WHERE id = %s AND organization_id = %s AND project_id = %s
            """,
            (rule_id, org_id, project_id),
        )
        return cur.fetchone()


def insert_online_eval_job(
    conn: PgConn,
    *,
    rule_id: UUID,
    org_id: UUID,
    project_id: UUID,
    trace_id: str,
    idempotency_key: str,
    payload: dict[str, Any],
) -> UUID | None:
    job_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluate.online_eval_jobs
                (id, rule_id, organization_id, project_id, trace_id, status, idempotency_key, payload)
            VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s::jsonb)
            ON CONFLICT (organization_id, project_id, idempotency_key) DO NOTHING
            RETURNING id
            """,
            (job_id, rule_id, org_id, project_id, trace_id, idempotency_key, _json(payload)),
        )
        row = cur.fetchone()
        return row["id"] if row else None


def insert_annotation_queue(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    queue_key: str,
    display_name: str,
    item_filter: dict[str, Any],
    rubric: dict[str, Any],
    reviewers_required: int,
    actor: str,
) -> UUID:
    qid = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluate.annotation_queues
                (id, organization_id, project_id, queue_key, display_name, item_filter, rubric,
                 reviewers_required, created_by)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s)
            """,
            (
                qid,
                org_id,
                project_id,
                queue_key,
                display_name,
                _json(item_filter),
                _json(rubric),
                reviewers_required,
                actor,
            ),
        )
    return qid


def get_annotation_queue(
    conn: PgConn, org_id: UUID, project_id: UUID, queue_id: UUID
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM evaluate.annotation_queues
            WHERE id = %s AND organization_id = %s AND project_id = %s
            """,
            (queue_id, org_id, project_id),
        )
        return cur.fetchone()


def insert_annotation_item(
    conn: PgConn,
    *,
    queue_id: UUID,
    org_id: UUID,
    project_id: UUID,
    item_type: str,
    reference_id: str,
    pairwise_reference_id: str | None,
    metadata: dict[str, Any],
) -> UUID:
    item_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluate.annotation_items
                (id, queue_id, organization_id, project_id, item_type, reference_id,
                 pairwise_reference_id, status, metadata)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'open', %s::jsonb)
            ON CONFLICT DO NOTHING
            RETURNING id
            """,
            (
                item_id,
                queue_id,
                org_id,
                project_id,
                item_type,
                reference_id,
                pairwise_reference_id,
                _json(metadata),
            ),
        )
        row = cur.fetchone()
        return row["id"] if row else item_id


def claim_annotation_item(
    conn: PgConn,
    *,
    item_id: UUID,
    org_id: UUID,
    assignee: str,
    lease_seconds: int,
    expected_version: int,
) -> bool:
    lease_until = datetime.now(UTC) + timedelta(seconds=lease_seconds)
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE evaluate.annotation_assignments
            SET lease_until = %s, version = version + 1
            WHERE item_id = %s AND assignee = %s AND version = %s
            RETURNING id
            """,
            (lease_until, item_id, assignee, expected_version),
        )
        if cur.fetchone():
            return True
        cur.execute(
            """
            INSERT INTO evaluate.annotation_assignments
                (id, item_id, organization_id, project_id, assignee, lease_until, version)
            SELECT %s, i.id, i.organization_id, i.project_id, %s, %s, 1
            FROM evaluate.annotation_items i
            WHERE i.id = %s AND i.organization_id = %s AND i.status = 'open'
            ON CONFLICT (item_id, assignee) DO NOTHING
            RETURNING id
            """,
            (uuid.uuid4(), assignee, lease_until, item_id, org_id),
        )
        return cur.fetchone() is not None


def get_assignment_version(conn: PgConn, item_id: UUID, assignee: str) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT version FROM evaluate.annotation_assignments
            WHERE item_id = %s AND assignee = %s
            """,
            (item_id, assignee),
        )
        row = cur.fetchone()
        return int(row["version"]) if row else 0


def insert_annotation_submission(
    conn: PgConn,
    *,
    item_id: UUID,
    org_id: UUID,
    project_id: UUID,
    assignee: str,
    action: str,
    scores: dict[str, Any],
    comments: str,
    rubric_version: int,
) -> UUID:
    sub_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluate.annotation_submissions
                (id, item_id, organization_id, project_id, assignee, action, scores, comments, rubric_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
            """,
            (
                sub_id,
                item_id,
                org_id,
                project_id,
                assignee,
                action,
                _json(scores),
                comments,
                rubric_version,
            ),
        )
        if action == "submit":
            cur.execute(
                """
                UPDATE evaluate.annotation_items SET status = 'completed' WHERE id = %s AND organization_id = %s
                """,
                (item_id, org_id),
            )
        elif action == "skip":
            cur.execute(
                """
                UPDATE evaluate.annotation_items SET status = 'skipped' WHERE id = %s AND organization_id = %s
                """,
                (item_id, org_id),
            )
    return sub_id


def list_annotation_submissions(conn: PgConn, item_id: UUID) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM evaluate.annotation_submissions WHERE item_id = %s ORDER BY created_at ASC
            """,
            (item_id,),
        )
        return list(cur.fetchall())


def insert_release_gate(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    gate_key: str,
    baseline_experiment_id: UUID | None,
    thresholds: dict[str, Any],
    actor: str,
) -> UUID:
    gid = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluate.release_gates
                (id, organization_id, project_id, gate_key, baseline_experiment_id, thresholds, created_by)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s)
            """,
            (gid, org_id, project_id, gate_key, baseline_experiment_id, _json(thresholds), actor),
        )
    return gid


def get_release_gate(
    conn: PgConn, org_id: UUID, project_id: UUID, gate_id: UUID
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM evaluate.release_gates
            WHERE id = %s AND organization_id = %s AND project_id = %s
            """,
            (gate_id, org_id, project_id),
        )
        return cur.fetchone()


def insert_release_gate_evaluation(
    conn: PgConn,
    *,
    gate_id: UUID,
    org_id: UUID,
    project_id: UUID,
    candidate_experiment_id: UUID,
    passed: bool,
    detail: dict[str, Any],
) -> UUID:
    eid = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluate.release_gate_evaluations
                (id, gate_id, organization_id, project_id, candidate_experiment_id, passed, detail)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (eid, gate_id, org_id, project_id, candidate_experiment_id, passed, _json(detail)),
        )
    return eid


def insert_object_ref(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    purpose: str,
    storage_ref: str,
    encryption_key_ref: str,
    content_digest: str,
    size_bytes: int,
    mime_type: str,
) -> UUID:
    oid = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluate.object_refs
                (id, organization_id, project_id, purpose, storage_ref, encryption_key_ref,
                 content_digest, size_bytes, mime_type)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                oid,
                org_id,
                project_id,
                purpose,
                storage_ref,
                encryption_key_ref,
                content_digest,
                size_bytes,
                mime_type,
            ),
        )
    return oid


def get_object_ref(
    conn: PgConn, org_id: UUID, project_id: UUID, ref_id: UUID
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM evaluate.object_refs
            WHERE id = %s AND organization_id = %s AND project_id = %s
            """,
            (ref_id, org_id, project_id),
        )
        return cur.fetchone()


def get_observe_cursor(conn: PgConn, org_id: UUID, project_id: UUID) -> str:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT poll_cursor FROM evaluate.observe_ingest_cursors
            WHERE organization_id = %s AND project_id = %s
            """,
            (org_id, project_id),
        )
        row = cur.fetchone()
        return str(row["poll_cursor"]) if row else ""


def set_observe_cursor(conn: PgConn, org_id: UUID, project_id: UUID, cursor: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluate.observe_ingest_cursors (organization_id, project_id, poll_cursor, updated_at)
            VALUES (%s, %s, %s, now())
            ON CONFLICT (organization_id, project_id)
            DO UPDATE SET poll_cursor = EXCLUDED.poll_cursor, updated_at = now()
            """,
            (org_id, project_id, cursor),
        )


def list_online_rule_projects(conn: PgConn) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT organization_id, project_id
            FROM evaluate.online_rules WHERE enabled = TRUE
            """
        )
        return list(cur.fetchall())


def count_running_online_jobs(conn: PgConn, rule_id: UUID) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS c FROM evaluate.online_eval_jobs
            WHERE rule_id = %s AND status = 'running'
            """,
            (rule_id,),
        )
        row = cur.fetchone()
        return int(row["c"]) if row else 0


def get_online_eval_job(conn: PgConn, org_id: UUID, job_id: UUID) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM evaluate.online_eval_jobs
            WHERE id = %s AND organization_id = %s
            """,
            (job_id, org_id),
        )
        return cur.fetchone()


def update_online_eval_job(
    conn: PgConn,
    job_id: UUID,
    *,
    status: str,
    span_id: str | None = None,
    error_message: str | None = None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE evaluate.online_eval_jobs
            SET status = %s, span_id = %s, error_message = %s, updated_at = now()
            WHERE id = %s
            """,
            (status, span_id, error_message, job_id),
        )


def increment_rule_spend(conn: PgConn, rule_id: UUID, amount: float) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE evaluate.online_rules
            SET spent_usd = spent_usd + %s, updated_at = now()
            WHERE id = %s
            """,
            (amount, rule_id),
        )


def open_rule_circuit(conn: PgConn, rule_id: UUID, *, until: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE evaluate.online_rules SET circuit_open_until = %s, updated_at = now() WHERE id = %s
            """,
            (until, rule_id),
        )


def count_online_jobs_since(conn: PgConn, rule_id: UUID, *, since: datetime) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS c FROM evaluate.online_eval_jobs
            WHERE rule_id = %s AND created_at >= %s
            """,
            (rule_id, since),
        )
        row = cur.fetchone()
        return int(row["c"]) if row else 0


def enqueue_alert_delivery(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    rule_id: UUID | None,
    action_type: str,
    target: str,
    payload_digest: str,
    payload: dict[str, Any],
    idempotency_key: str,
    max_attempts: int,
) -> UUID | None:
    aid = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO evaluate.alert_deliveries
                (id, organization_id, project_id, rule_id, action_type, target,
                 payload_digest, payload, status, max_attempts, idempotency_key)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, 'pending', %s, %s)
            ON CONFLICT (organization_id, project_id, idempotency_key) DO NOTHING
            RETURNING id
            """,
            (
                aid,
                org_id,
                project_id,
                rule_id,
                action_type,
                target,
                payload_digest,
                _json(payload),
                max_attempts,
                idempotency_key,
            ),
        )
        row = cur.fetchone()
        return row["id"] if row else None


def claim_pending_alerts(
    conn: PgConn,
    *,
    limit: int,
    organization_id: UUID | None = None,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        if organization_id is not None:
            cur.execute(
                """
                SELECT * FROM evaluate.alert_deliveries
                WHERE status = 'pending' AND attempts < max_attempts
                  AND organization_id = %s
                ORDER BY created_at ASC
                LIMIT %s
                FOR UPDATE SKIP LOCKED
                """,
                (organization_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT * FROM evaluate.alert_deliveries
                WHERE status = 'pending' AND attempts < max_attempts
                ORDER BY created_at ASC
                LIMIT %s
                FOR UPDATE SKIP LOCKED
                """,
                (limit,),
            )
        rows = list(cur.fetchall())
        updated: list[dict[str, Any]] = []
        for row in rows:
            cur.execute(
                """
                UPDATE evaluate.alert_deliveries
                SET attempts = attempts + 1, updated_at = now()
                WHERE id = %s
                RETURNING *
                """,
                (row["id"],),
            )
            fresh = cur.fetchone()
            if fresh:
                updated.append(fresh)
        return updated


def finish_alert_delivery(
    conn: PgConn, alert_id: UUID, *, status: str, error: str | None = None
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE evaluate.alert_deliveries
            SET status = %s, last_error = %s, updated_at = now(),
                delivered_at = CASE WHEN %s = 'delivered' THEN now() ELSE delivered_at END
            WHERE id = %s
            """,
            (status, error, status, alert_id),
        )


def count_datasets(conn: PgConn, org_id: UUID, project_id: UUID, *, q: str | None = None) -> int:
    with conn.cursor() as cur:
        if q:
            pattern = f"%{q}%"
            cur.execute(
                """
                SELECT COUNT(*) AS c FROM evaluate.datasets
                WHERE organization_id = %s AND project_id = %s
                  AND (dataset_key ILIKE %s OR display_name ILIKE %s)
                """,
                (org_id, project_id, pattern, pattern),
            )
        else:
            cur.execute(
                """
                SELECT COUNT(*) AS c FROM evaluate.datasets
                WHERE organization_id = %s AND project_id = %s
                """,
                (org_id, project_id),
            )
        row = cur.fetchone()
        return int(row["c"]) if row else 0


def search_datasets(
    conn: PgConn,
    org_id: UUID,
    project_id: UUID,
    *,
    q: str | None,
    limit: int,
    cursor_created_at: datetime | None = None,
    cursor_id: UUID | None = None,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        pattern = f"%{q}%" if q else None
        if pattern and cursor_created_at and cursor_id:
            cur.execute(
                """
                SELECT * FROM evaluate.datasets
                WHERE organization_id = %s AND project_id = %s
                  AND (dataset_key ILIKE %s OR display_name ILIKE %s)
                  AND (created_at, id) < (%s, %s)
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (org_id, project_id, pattern, pattern, cursor_created_at, cursor_id, limit),
            )
        elif pattern:
            cur.execute(
                """
                SELECT * FROM evaluate.datasets
                WHERE organization_id = %s AND project_id = %s
                  AND (dataset_key ILIKE %s OR display_name ILIKE %s)
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (org_id, project_id, pattern, pattern, limit),
            )
        elif cursor_created_at and cursor_id:
            cur.execute(
                """
                SELECT * FROM evaluate.datasets
                WHERE organization_id = %s AND project_id = %s
                  AND (created_at, id) < (%s, %s)
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (org_id, project_id, cursor_created_at, cursor_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT * FROM evaluate.datasets
                WHERE organization_id = %s AND project_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (org_id, project_id, limit),
            )
        return list(cur.fetchall())


def get_dataset(
    conn: PgConn, org_id: UUID, project_id: UUID, dataset_id: UUID
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM evaluate.datasets
            WHERE id = %s AND organization_id = %s AND project_id = %s
            """,
            (dataset_id, org_id, project_id),
        )
        return cur.fetchone()


def count_dataset_revisions(conn: PgConn, org_id: UUID, dataset_id: UUID) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS c FROM evaluate.dataset_revisions
            WHERE dataset_id = %s AND organization_id = %s
            """,
            (dataset_id, org_id),
        )
        row = cur.fetchone()
        return int(row["c"]) if row else 0


def list_dataset_revisions(
    conn: PgConn,
    org_id: UUID,
    dataset_id: UUID,
    *,
    limit: int,
    cursor_created_at: datetime | None = None,
    cursor_id: UUID | None = None,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        if cursor_created_at and cursor_id:
            cur.execute(
                """
                SELECT * FROM evaluate.dataset_revisions
                WHERE dataset_id = %s AND organization_id = %s
                  AND (created_at, id) < (%s, %s)
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (dataset_id, org_id, cursor_created_at, cursor_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT * FROM evaluate.dataset_revisions
                WHERE dataset_id = %s AND organization_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (dataset_id, org_id, limit),
            )
        return list(cur.fetchall())


_EXAMPLE_SUMMARY_COLS = """
    e.id, e.dataset_revision_id, e.organization_id, e.project_id, e.example_key,
    e.ordinal, e.split_name, e.tags, e.metadata, e.content_digest, e.source_trace_id,
    e.dedupe_digest, e.has_encrypted_payload, e.created_at,
    (b.input_object_ref IS NOT NULL) AS has_input_object,
    (b.reference_output_object_ref IS NOT NULL) AS has_reference_object
"""


def count_examples(
    conn: PgConn,
    org_id: UUID,
    revision_id: UUID,
    *,
    split: str | None = None,
    q: str | None = None,
) -> int:
    with conn.cursor() as cur:
        clauses = ["e.dataset_revision_id = %s", "e.organization_id = %s"]
        params: list[Any] = [revision_id, org_id]
        if split:
            clauses.append("e.split_name = %s")
            params.append(split)
        if q:
            clauses.append("e.example_key ILIKE %s")
            params.append(f"%{q}%")
        cur.execute(
            f"SELECT COUNT(*) AS c FROM evaluate.examples e WHERE {' AND '.join(clauses)}",
            params,
        )
        row = cur.fetchone()
        return int(row["c"]) if row else 0


def list_example_summaries(
    conn: PgConn,
    org_id: UUID,
    revision_id: UUID,
    *,
    split: str | None,
    q: str | None,
    limit: int,
    cursor_ordinal: int | None = None,
    cursor_id: UUID | None = None,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        clauses = ["e.dataset_revision_id = %s", "e.organization_id = %s"]
        params: list[Any] = [revision_id, org_id]
        if split:
            clauses.append("e.split_name = %s")
            params.append(split)
        if q:
            clauses.append("e.example_key ILIKE %s")
            params.append(f"%{q}%")
        if cursor_ordinal is not None and cursor_id:
            clauses.append("(e.ordinal, e.id) > (%s, %s)")
            params.extend([cursor_ordinal, cursor_id])
        params.append(limit)
        cur.execute(
            f"""
            SELECT {_EXAMPLE_SUMMARY_COLS}
            FROM evaluate.examples e
            LEFT JOIN evaluate.example_bodies b ON b.example_id = e.id
            WHERE {" AND ".join(clauses)}
            ORDER BY e.ordinal ASC, e.id ASC
            LIMIT %s
            """,
            params,
        )
        return list(cur.fetchall())


def get_example_summary(
    conn: PgConn, org_id: UUID, revision_id: UUID, example_id: UUID
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT {_EXAMPLE_SUMMARY_COLS}
            FROM evaluate.examples e
            LEFT JOIN evaluate.example_bodies b ON b.example_id = e.id
            WHERE e.id = %s AND e.dataset_revision_id = %s AND e.organization_id = %s
            """,
            (example_id, revision_id, org_id),
        )
        return cur.fetchone()


def count_experiments(conn: PgConn, org_id: UUID, project_id: UUID, *, q: str | None) -> int:
    with conn.cursor() as cur:
        if q:
            pattern = f"%{q}%"
            cur.execute(
                """
                SELECT COUNT(*) AS c FROM evaluate.experiments
                WHERE organization_id = %s AND project_id = %s
                  AND (experiment_key ILIKE %s OR display_name ILIKE %s)
                """,
                (org_id, project_id, pattern, pattern),
            )
        else:
            cur.execute(
                """
                SELECT COUNT(*) AS c FROM evaluate.experiments
                WHERE organization_id = %s AND project_id = %s
                """,
                (org_id, project_id),
            )
        row = cur.fetchone()
        return int(row["c"]) if row else 0


def list_experiments(
    conn: PgConn,
    org_id: UUID,
    project_id: UUID,
    *,
    q: str | None,
    limit: int,
    cursor_created_at: datetime | None = None,
    cursor_id: UUID | None = None,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        pattern = f"%{q}%" if q else None
        if pattern and cursor_created_at and cursor_id:
            cur.execute(
                """
                SELECT * FROM evaluate.experiments
                WHERE organization_id = %s AND project_id = %s
                  AND (experiment_key ILIKE %s OR display_name ILIKE %s)
                  AND (created_at, id) < (%s, %s)
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (org_id, project_id, pattern, pattern, cursor_created_at, cursor_id, limit),
            )
        elif pattern:
            cur.execute(
                """
                SELECT * FROM evaluate.experiments
                WHERE organization_id = %s AND project_id = %s
                  AND (experiment_key ILIKE %s OR display_name ILIKE %s)
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (org_id, project_id, pattern, pattern, limit),
            )
        elif cursor_created_at and cursor_id:
            cur.execute(
                """
                SELECT * FROM evaluate.experiments
                WHERE organization_id = %s AND project_id = %s
                  AND (created_at, id) < (%s, %s)
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (org_id, project_id, cursor_created_at, cursor_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT * FROM evaluate.experiments
                WHERE organization_id = %s AND project_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (org_id, project_id, limit),
            )
        return list(cur.fetchall())


def get_experiment_by_key(
    conn: PgConn, org_id: UUID, project_id: UUID, experiment_key: str
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM evaluate.experiments
            WHERE organization_id = %s AND project_id = %s AND experiment_key = %s
            """,
            (org_id, project_id, experiment_key),
        )
        return cur.fetchone()


def get_evaluator(
    conn: PgConn, org_id: UUID, project_id: UUID, evaluator_id: UUID
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT * FROM evaluate.evaluators
            WHERE id = %s AND organization_id = %s AND project_id = %s
            """,
            (evaluator_id, org_id, project_id),
        )
        return cur.fetchone()


def count_evaluators(conn: PgConn, org_id: UUID, project_id: UUID, *, q: str | None) -> int:
    with conn.cursor() as cur:
        if q:
            pattern = f"%{q}%"
            cur.execute(
                """
                SELECT COUNT(*) AS c FROM evaluate.evaluators
                WHERE organization_id = %s AND project_id = %s
                  AND (evaluator_key ILIKE %s OR display_name ILIKE %s)
                """,
                (org_id, project_id, pattern, pattern),
            )
        else:
            cur.execute(
                """
                SELECT COUNT(*) AS c FROM evaluate.evaluators
                WHERE organization_id = %s AND project_id = %s
                """,
                (org_id, project_id),
            )
        row = cur.fetchone()
        return int(row["c"]) if row else 0


def list_evaluators(
    conn: PgConn,
    org_id: UUID,
    project_id: UUID,
    *,
    q: str | None,
    limit: int,
    cursor_created_at: datetime | None = None,
    cursor_id: UUID | None = None,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        pattern = f"%{q}%" if q else None
        if pattern and cursor_created_at and cursor_id:
            cur.execute(
                """
                SELECT * FROM evaluate.evaluators
                WHERE organization_id = %s AND project_id = %s
                  AND (evaluator_key ILIKE %s OR display_name ILIKE %s)
                  AND (created_at, id) < (%s, %s)
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (org_id, project_id, pattern, pattern, cursor_created_at, cursor_id, limit),
            )
        elif pattern:
            cur.execute(
                """
                SELECT * FROM evaluate.evaluators
                WHERE organization_id = %s AND project_id = %s
                  AND (evaluator_key ILIKE %s OR display_name ILIKE %s)
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (org_id, project_id, pattern, pattern, limit),
            )
        elif cursor_created_at and cursor_id:
            cur.execute(
                """
                SELECT * FROM evaluate.evaluators
                WHERE organization_id = %s AND project_id = %s
                  AND (created_at, id) < (%s, %s)
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (org_id, project_id, cursor_created_at, cursor_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT * FROM evaluate.evaluators
                WHERE organization_id = %s AND project_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (org_id, project_id, limit),
            )
        return list(cur.fetchall())


def count_evaluator_revisions(conn: PgConn, org_id: UUID, evaluator_id: UUID) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS c FROM evaluate.evaluator_revisions
            WHERE evaluator_id = %s AND organization_id = %s
            """,
            (evaluator_id, org_id),
        )
        row = cur.fetchone()
        return int(row["c"]) if row else 0


def list_evaluator_revisions(
    conn: PgConn,
    org_id: UUID,
    evaluator_id: UUID,
    *,
    limit: int,
    cursor_created_at: datetime | None = None,
    cursor_id: UUID | None = None,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        if cursor_created_at and cursor_id:
            cur.execute(
                """
                SELECT r.*, e.kind, e.evaluator_key
                FROM evaluate.evaluator_revisions r
                JOIN evaluate.evaluators e ON e.id = r.evaluator_id
                WHERE r.evaluator_id = %s AND r.organization_id = %s
                  AND (r.created_at, r.id) < (%s, %s)
                ORDER BY r.created_at DESC, r.id DESC
                LIMIT %s
                """,
                (evaluator_id, org_id, cursor_created_at, cursor_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT r.*, e.kind, e.evaluator_key
                FROM evaluate.evaluator_revisions r
                JOIN evaluate.evaluators e ON e.id = r.evaluator_id
                WHERE r.evaluator_id = %s AND r.organization_id = %s
                ORDER BY r.created_at DESC, r.id DESC
                LIMIT %s
                """,
                (evaluator_id, org_id, limit),
            )
        return list(cur.fetchall())


def count_scores(
    conn: PgConn,
    org_id: UUID,
    project_id: UUID,
    *,
    target_type: str | None,
    target_id: str | None,
    name: str | None,
    source: str | None,
) -> int:
    clauses = ["organization_id = %s", "project_id = %s"]
    params: list[Any] = [org_id, project_id]
    if target_type:
        clauses.append("target_type = %s")
        params.append(target_type)
    if target_id:
        clauses.append("target_id = %s")
        params.append(target_id)
    if name:
        clauses.append("name = %s")
        params.append(name)
    if source:
        clauses.append("source = %s")
        params.append(source)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) AS c FROM evaluate.scores WHERE {' AND '.join(clauses)}",
            params,
        )
        row = cur.fetchone()
        return int(row["c"]) if row else 0


def list_scores(
    conn: PgConn,
    org_id: UUID,
    project_id: UUID,
    *,
    target_type: str | None,
    target_id: str | None,
    name: str | None,
    source: str | None,
    limit: int,
    cursor_created_at: datetime | None = None,
    cursor_id: UUID | None = None,
) -> list[dict[str, Any]]:
    clauses = ["organization_id = %s", "project_id = %s"]
    params: list[Any] = [org_id, project_id]
    if target_type:
        clauses.append("target_type = %s")
        params.append(target_type)
    if target_id:
        clauses.append("target_id = %s")
        params.append(target_id)
    if name:
        clauses.append("name = %s")
        params.append(name)
    if source:
        clauses.append("source = %s")
        params.append(source)
    if cursor_created_at and cursor_id:
        clauses.append("(created_at, id) < (%s, %s)")
        params.extend([cursor_created_at, cursor_id])
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, organization_id, project_id, target_type, target_id, name, value_type,
                   value_numeric, value_boolean, value_categorical, source, evaluator_revision_id,
                   explanation, metadata, supersedes_score_id, created_at, created_by
            FROM evaluate.scores
            WHERE {" AND ".join(clauses)}
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            params,
        )
        return list(cur.fetchall())


def get_score(
    conn: PgConn, org_id: UUID, project_id: UUID, score_id: UUID
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, organization_id, project_id, target_type, target_id, name, value_type,
                   value_numeric, value_boolean, value_categorical, source, evaluator_revision_id,
                   explanation, metadata, supersedes_score_id, created_at, created_by
            FROM evaluate.scores
            WHERE id = %s AND organization_id = %s AND project_id = %s
            """,
            (score_id, org_id, project_id),
        )
        return cur.fetchone()


def count_online_rules(conn: PgConn, org_id: UUID, project_id: UUID) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS c FROM evaluate.online_rules
            WHERE organization_id = %s AND project_id = %s
            """,
            (org_id, project_id),
        )
        row = cur.fetchone()
        return int(row["c"]) if row else 0


def list_online_rules(
    conn: PgConn,
    org_id: UUID,
    project_id: UUID,
    *,
    limit: int,
    cursor_created_at: datetime | None = None,
    cursor_id: UUID | None = None,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        if cursor_created_at and cursor_id:
            cur.execute(
                """
                SELECT id, organization_id, project_id, rule_key, enabled, filter, sample_rate,
                       evaluator_revision_ids, budget_usd, max_concurrency, spent_usd,
                       circuit_open_until, created_at, updated_at
                FROM evaluate.online_rules
                WHERE organization_id = %s AND project_id = %s
                  AND (created_at, id) < (%s, %s)
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (org_id, project_id, cursor_created_at, cursor_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT id, organization_id, project_id, rule_key, enabled, filter, sample_rate,
                       evaluator_revision_ids, budget_usd, max_concurrency, spent_usd,
                       circuit_open_until, created_at, updated_at
                FROM evaluate.online_rules
                WHERE organization_id = %s AND project_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (org_id, project_id, limit),
            )
        return list(cur.fetchall())


def count_alert_deliveries(
    conn: PgConn,
    org_id: UUID,
    project_id: UUID,
    *,
    status: str | None,
    rule_id: UUID | None,
) -> int:
    clauses = ["organization_id = %s", "project_id = %s"]
    params: list[Any] = [org_id, project_id]
    if status:
        clauses.append("status = %s")
        params.append(status)
    if rule_id:
        clauses.append("rule_id = %s")
        params.append(rule_id)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) AS c FROM evaluate.alert_deliveries WHERE {' AND '.join(clauses)}",
            params,
        )
        row = cur.fetchone()
        return int(row["c"]) if row else 0


def list_alert_deliveries(
    conn: PgConn,
    org_id: UUID,
    project_id: UUID,
    *,
    status: str | None,
    rule_id: UUID | None,
    limit: int,
    cursor_created_at: datetime | None = None,
    cursor_id: UUID | None = None,
) -> list[dict[str, Any]]:
    clauses = ["organization_id = %s", "project_id = %s"]
    params: list[Any] = [org_id, project_id]
    if status:
        clauses.append("status = %s")
        params.append(status)
    if rule_id:
        clauses.append("rule_id = %s")
        params.append(rule_id)
    if cursor_created_at and cursor_id:
        clauses.append("(created_at, id) < (%s, %s)")
        params.extend([cursor_created_at, cursor_id])
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, organization_id, project_id, rule_id, action_type, target, payload_digest,
                   status, attempts, max_attempts, last_error, delivered_at, acknowledged_at,
                   created_at, updated_at,
                   payload->>'trace_id' AS payload_trace_id
            FROM evaluate.alert_deliveries
            WHERE {" AND ".join(clauses)}
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            params,
        )
        return list(cur.fetchall())


def get_alert_delivery(
    conn: PgConn, org_id: UUID, project_id: UUID, alert_id: UUID
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, organization_id, project_id, rule_id, action_type, target, payload_digest,
                   status, attempts, max_attempts, last_error, delivered_at, acknowledged_at,
                   created_at, updated_at,
                   payload->>'trace_id' AS payload_trace_id
            FROM evaluate.alert_deliveries
            WHERE id = %s AND organization_id = %s AND project_id = %s
            """,
            (alert_id, org_id, project_id),
        )
        return cur.fetchone()


def retry_alert_delivery(conn: PgConn, org_id: UUID, project_id: UUID, alert_id: UUID) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE evaluate.alert_deliveries
            SET status = 'pending', attempts = 0, last_error = NULL, updated_at = now()
            WHERE id = %s AND organization_id = %s AND project_id = %s
            RETURNING id
            """,
            (alert_id, org_id, project_id),
        )
        return cur.fetchone() is not None


def acknowledge_alert_delivery(
    conn: PgConn, org_id: UUID, project_id: UUID, alert_id: UUID
) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE evaluate.alert_deliveries
            SET acknowledged_at = now(), updated_at = now()
            WHERE id = %s AND organization_id = %s AND project_id = %s
            RETURNING id
            """,
            (alert_id, org_id, project_id),
        )
        return cur.fetchone() is not None


def count_annotation_queues(conn: PgConn, org_id: UUID, project_id: UUID) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS c FROM evaluate.annotation_queues
            WHERE organization_id = %s AND project_id = %s
            """,
            (org_id, project_id),
        )
        row = cur.fetchone()
        return int(row["c"]) if row else 0


def list_annotation_queues(
    conn: PgConn,
    org_id: UUID,
    project_id: UUID,
    *,
    limit: int,
    cursor_created_at: datetime | None = None,
    cursor_id: UUID | None = None,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        if cursor_created_at and cursor_id:
            cur.execute(
                """
                SELECT * FROM evaluate.annotation_queues
                WHERE organization_id = %s AND project_id = %s
                  AND (created_at, id) < (%s, %s)
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (org_id, project_id, cursor_created_at, cursor_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT * FROM evaluate.annotation_queues
                WHERE organization_id = %s AND project_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (org_id, project_id, limit),
            )
        return list(cur.fetchall())


def count_annotation_items(
    conn: PgConn,
    org_id: UUID,
    project_id: UUID,
    *,
    queue_id: UUID | None,
    status: str | None,
) -> int:
    clauses = ["organization_id = %s", "project_id = %s"]
    params: list[Any] = [org_id, project_id]
    if queue_id:
        clauses.append("queue_id = %s")
        params.append(queue_id)
    if status:
        clauses.append("status = %s")
        params.append(status)
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) AS c FROM evaluate.annotation_items WHERE {' AND '.join(clauses)}",
            params,
        )
        row = cur.fetchone()
        return int(row["c"]) if row else 0


def list_annotation_items(
    conn: PgConn,
    org_id: UUID,
    project_id: UUID,
    *,
    queue_id: UUID | None,
    status: str | None,
    limit: int,
    cursor_created_at: datetime | None = None,
    cursor_id: UUID | None = None,
) -> list[dict[str, Any]]:
    clauses = ["organization_id = %s", "project_id = %s"]
    params: list[Any] = [org_id, project_id]
    if queue_id:
        clauses.append("queue_id = %s")
        params.append(queue_id)
    if status:
        clauses.append("status = %s")
        params.append(status)
    if cursor_created_at and cursor_id:
        clauses.append("(created_at, id) < (%s, %s)")
        params.extend([cursor_created_at, cursor_id])
    params.append(limit)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, queue_id, organization_id, project_id, item_type, reference_id,
                   pairwise_reference_id, status, metadata, created_at
            FROM evaluate.annotation_items
            WHERE {" AND ".join(clauses)}
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            params,
        )
        return list(cur.fetchall())


def get_annotation_item(
    conn: PgConn, org_id: UUID, project_id: UUID, item_id: UUID
) -> dict[str, Any] | None:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, queue_id, organization_id, project_id, item_type, reference_id,
                   pairwise_reference_id, status, metadata, created_at
            FROM evaluate.annotation_items
            WHERE id = %s AND organization_id = %s AND project_id = %s
            """,
            (item_id, org_id, project_id),
        )
        return cur.fetchone()


def count_release_gates(conn: PgConn, org_id: UUID, project_id: UUID) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS c FROM evaluate.release_gates
            WHERE organization_id = %s AND project_id = %s
            """,
            (org_id, project_id),
        )
        row = cur.fetchone()
        return int(row["c"]) if row else 0


def list_release_gates(
    conn: PgConn,
    org_id: UUID,
    project_id: UUID,
    *,
    limit: int,
    cursor_created_at: datetime | None = None,
    cursor_id: UUID | None = None,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        if cursor_created_at and cursor_id:
            cur.execute(
                """
                SELECT * FROM evaluate.release_gates
                WHERE organization_id = %s AND project_id = %s
                  AND (created_at, id) < (%s, %s)
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (org_id, project_id, cursor_created_at, cursor_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT * FROM evaluate.release_gates
                WHERE organization_id = %s AND project_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (org_id, project_id, limit),
            )
        return list(cur.fetchall())


def count_release_gate_evaluations(conn: PgConn, org_id: UUID, gate_id: UUID) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS c FROM evaluate.release_gate_evaluations
            WHERE gate_id = %s AND organization_id = %s
            """,
            (gate_id, org_id),
        )
        row = cur.fetchone()
        return int(row["c"]) if row else 0


def list_release_gate_evaluations(
    conn: PgConn,
    org_id: UUID,
    gate_id: UUID,
    *,
    limit: int,
    cursor_created_at: datetime | None = None,
    cursor_id: UUID | None = None,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        if cursor_created_at and cursor_id:
            cur.execute(
                """
                SELECT id, gate_id, organization_id, project_id, candidate_experiment_id,
                       passed, detail, created_at
                FROM evaluate.release_gate_evaluations
                WHERE gate_id = %s AND organization_id = %s
                  AND (created_at, id) < (%s, %s)
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (gate_id, org_id, cursor_created_at, cursor_id, limit),
            )
        else:
            cur.execute(
                """
                SELECT id, gate_id, organization_id, project_id, candidate_experiment_id,
                       passed, detail, created_at
                FROM evaluate.release_gate_evaluations
                WHERE gate_id = %s AND organization_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT %s
                """,
                (gate_id, org_id, limit),
            )
        return list(cur.fetchall())
