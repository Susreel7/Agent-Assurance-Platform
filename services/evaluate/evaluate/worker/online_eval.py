"""Online evaluation job processor."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from evaluate.clients.observe import ObserveClient
from evaluate.clients.router import RouterClient
from evaluate.config import Settings
from evaluate.db import repository as repo
from evaluate.db.postgres import connect
from evaluate.domains.scores import service as score_service
from evaluate.domains.scores.schemas import ScoreCreate
from evaluate.evaluators.engine import run_evaluator
from evaluate.log_safe import redact
from evaluate.worker.alert_dispatch import schedule_webhook_action

log = logging.getLogger(__name__)


def _worker_bearer(settings: Settings) -> str:
    return settings.observe_worker_bearer or settings.internal_service_token


async def process_online_eval_job(settings: Settings, payload: dict[str, Any]) -> None:
    job_id = UUID(str(payload["online_job_id"]))
    rule_id = UUID(str(payload["rule_id"]))
    with connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM evaluate.online_eval_jobs WHERE id = %s", (job_id,))
            job = cur.fetchone()
        if not job:
            return
        org_id = job["organization_id"]
        project_id = job["project_id"]
        rule = repo.get_online_rule(conn, org_id, project_id, rule_id)
        if not rule:
            repo.update_online_eval_job(conn, job_id, status="failed", error_message="rule missing")
            return
        running = repo.count_running_online_jobs(conn, rule_id)
        if running >= int(rule.get("max_concurrency") or 1):
            return
        budget = rule.get("budget_usd")
        spent = float(rule.get("spent_usd") or 0)
        if budget is not None and spent >= float(budget):
            repo.update_online_eval_job(conn, job_id, status="skipped", error_message="budget")
            return
        repo.update_online_eval_job(conn, job_id, status="running")

    trace_id = str(job["trace_id"])
    client = ObserveClient(settings)
    trace = await client.get_trace_summary(
        org_id=str(org_id),
        project_id=str(project_id),
        trace_id=trace_id,
        authorization=f"Bearer {_worker_bearer(settings)}",
    )
    output = trace.get("output") or trace.get("output_preview") or ""
    inp = trace.get("input") or trace.get("input_preview") or ""
    span_id = str(trace.get("root_span_id") or trace.get("span_id") or "") or None
    eval_ids = rule.get("evaluator_revision_ids") or []
    router = RouterClient(settings)
    scores_out: dict[str, Any] = {}
    raw_cost = trace.get("cost_usd")
    cost = float(raw_cost) if raw_cost is not None else 0.0
    with connect(settings.database_url) as conn:
        for rev_id_raw in eval_ids:
            rev = repo.get_evaluator_revision(conn, org_id, UUID(str(rev_id_raw)))
            if not rev:
                continue
            cfg = rev["config"] if isinstance(rev["config"], dict) else {}
            ctx: dict[str, Any] = {
                "input": inp,
                "output": output,
                "reference": None,
                "latency_ms": trace.get("latency_ms"),
                "cost_usd": trace.get("cost_usd"),
                "tool_calls": trace.get("tool_names") or [],
            }
            try:
                outcome = await run_evaluator(
                    settings,
                    kind=rev["kind"],
                    config=cfg,
                    context=ctx,
                    router=router,
                    authorization=f"Bearer {settings.router_worker_bearer or _worker_bearer(settings)}",
                )
                scores_out[rev["evaluator_key"]] = outcome
                score_service.create_score(
                    conn,
                    org_id=org_id,
                    project_id=project_id,
                    payload=ScoreCreate(
                        target_type="trace",
                        target_id=trace_id,
                        name=str(rev["evaluator_key"]),
                        value_type="numeric",
                        value_numeric=float(outcome.get("score", 0)),
                        source="automated",
                        evaluator_revision_id=rev["id"],
                    ),
                    actor="evaluate-online",
                )
            except Exception as exc:  # noqa: BLE001
                scores_out[rev["evaluator_key"]] = {"error": redact(str(exc))}
        repo.increment_rule_spend(conn, rule_id, cost)
        repo.update_online_eval_job(conn, job_id, status="completed", span_id=span_id)
        actions = rule.get("actions") or []
        if isinstance(actions, list):
            for action in actions:
                if not isinstance(action, dict):
                    continue
                if action.get("type") == "webhook" and action.get("url"):
                    schedule_webhook_action(
                        conn,
                        settings,
                        org_id=org_id,
                        project_id=project_id,
                        rule_id=rule_id,
                        target=str(action["url"]),
                        payload={"trace_id": trace_id, "scores": scores_out},
                        idempotency_key=f"online:{job_id}:{action['url']}",
                    )
        failures = sum(1 for v in scores_out.values() if isinstance(v, dict) and v.get("error"))
        if failures and failures == len(scores_out) and len(scores_out) > 0:
            repo.open_rule_circuit(
                conn,
                rule_id,
                until=datetime.now(UTC) + timedelta(minutes=5),
            )
