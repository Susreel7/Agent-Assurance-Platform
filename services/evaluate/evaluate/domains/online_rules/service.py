"""Online sampling rules and durable eval jobs."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from evaluate.config import Settings
from evaluate.db import repository as repo
from evaluate.db.postgres import PgConn
from evaluate.errors import NotFoundError, ValidationError
from evaluate.queue.redis_wake import publish_wake
from evaluate.util import deterministic_sample


def create_rule(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    payload: dict[str, Any],
) -> UUID:
    salt = payload.get("sample_hash_salt") or payload["rule_key"]
    return repo.insert_online_rule(
        conn,
        org_id=org_id,
        project_id=project_id,
        rule_key=payload["rule_key"],
        payload={**payload, "sample_hash_salt": salt},
    )


def should_sample_rule(rule: dict[str, Any], trace_id: str) -> bool:
    if not rule.get("enabled", True):
        return False
    open_until = rule.get("circuit_open_until")
    if open_until and isinstance(open_until, datetime) and open_until > datetime.now(UTC):
        return False
    rate = float(rule.get("sample_rate", 0.01))
    salt = str(rule.get("sample_hash_salt", ""))
    return deterministic_sample(key=trace_id, salt=salt, rate=rate)


def ingest_trace_event(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    rule_id: UUID,
    trace_id: str,
    metadata: dict[str, Any],
) -> UUID | None:
    rule = repo.get_online_rule(conn, org_id, project_id, rule_id)
    if not rule:
        raise NotFoundError("online rule not found")
    filt = rule.get("filter") or {}
    if isinstance(filt, dict) and filt.get("environment"):
        if metadata.get("environment") != filt["environment"]:
            return None
    if not should_sample_rule(rule, trace_id):
        return None
    budget = rule.get("budget_usd")
    spent = float(rule.get("spent_usd") or 0)
    if budget is not None and spent >= float(budget):
        raise ValidationError("online rule budget exhausted")
    if isinstance(filt, dict) and filt.get("max_jobs_per_hour") is not None:
        cap = int(filt["max_jobs_per_hour"])
        since = datetime.now(UTC) - timedelta(hours=1)
        if repo.count_online_jobs_since(conn, rule_id, since=since) >= cap:
            return None
    idem = f"online:{rule_id}:{trace_id}"
    job_id = repo.insert_online_eval_job(
        conn,
        rule_id=rule_id,
        org_id=org_id,
        project_id=project_id,
        trace_id=trace_id,
        idempotency_key=idem,
        payload={"trace_id": trace_id, "metadata": metadata},
    )
    if job_id:
        repo.enqueue_job(
            conn,
            org_id=org_id,
            project_id=project_id,
            job_type="online_eval",
            payload={"online_job_id": str(job_id), "rule_id": str(rule_id)},
            idempotency_key=idem,
            max_attempts=settings.worker_max_attempts,
        )
        publish_wake(settings, reason="online")
    return job_id
