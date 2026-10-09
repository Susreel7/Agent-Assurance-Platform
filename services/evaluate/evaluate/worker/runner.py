"""Durable PG job worker — Redis is wake-up only."""

from __future__ import annotations

import asyncio
import logging
import socket
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from evaluate.clients.prompt import PromptClient
from evaluate.clients.router import RouterClient
from evaluate.config import Settings, get_settings
from evaluate.db import repository as repo
from evaluate.db.postgres import connect
from evaluate.evaluators.engine import run_evaluator
from evaluate.log_safe import redact
from evaluate.queue.redis_wake import publish_wake, wait_wake
from evaluate.util import digest_json
from evaluate.worker.alert_dispatch import process_alert_batch
from evaluate.worker.observe_poller import poll_all_projects
from evaluate.worker.online_eval import process_online_eval_job
from evaluate.worker.prompt_resolve import apply_example_to_messages, resolve_pinned_prompts

log = logging.getLogger(__name__)


def _owner_id() -> str:
    return f"{socket.gethostname()}:{int(time.time())}"


def _router_auth(settings: Settings) -> str:
    token = settings.router_worker_bearer or settings.internal_service_token
    return f"Bearer {token}"


async def _run_single_result(
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    experiment_id: UUID,
    result_row: dict[str, Any],
    spec: dict[str, Any],
    prompt: PromptClient | None = None,
    router: RouterClient | None = None,
) -> None:
    prompt = prompt or PromptClient(settings)
    router = router or RouterClient(settings)
    authorization = _router_auth(settings)
    with connect(settings.database_url) as conn:
        exp = repo.get_experiment(conn, org_id, project_id, experiment_id)
        if exp and exp["status"] == "cancelled":
            repo.complete_experiment_result(
                conn,
                result_row["id"],
                status="cancelled",
                trace_id=None,
                output_digest=None,
                latency_ms=None,
                cost_usd=None,
                scores={},
                error_message="cancelled",
            )
            return
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT e.*, b.input_inline, b.reference_output_inline,
                       b.input_object_ref, b.reference_output_object_ref
                FROM evaluate.examples e
                JOIN evaluate.example_bodies b ON b.example_id = e.id
                WHERE e.id = %s AND e.organization_id = %s
                """,
                (result_row["example_id"], org_id),
            )
            example = cur.fetchone()
        if not example:
            repo.complete_experiment_result(
                conn,
                result_row["id"],
                status="failed",
                trace_id=None,
                output_digest=None,
                latency_ms=None,
                cost_usd=None,
                scores={},
                error_message="example missing",
            )
            return
        inp = example.get("input_inline") or {}
        if example.get("input_object_ref"):
            from evaluate.domains.datasets import attachments as att

            inp = att.load_inline_payload(
                conn,
                settings,
                org_id=org_id,
                project_id=project_id,
                storage_ref=str(example["input_object_ref"]),
            )

    try:
        resolved = await resolve_pinned_prompts(
            settings, prompt, org_id=org_id, project_id=project_id, spec=spec
        )
    except Exception as exc:  # noqa: BLE001
        with connect(settings.database_url) as conn:
            repo.complete_experiment_result(
                conn,
                result_row["id"],
                status="failed",
                trace_id=None,
                output_digest=None,
                latency_ms=None,
                cost_usd=None,
                scores={},
                error_message=redact(str(exc)),
            )
        return

    messages = apply_example_to_messages(
        resolved.messages, inp if isinstance(inp, dict) else {"input": inp}
    )
    model = spec.get("model_route_alias") or "default"
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        **(spec.get("model_settings") or {}),
        "metadata": {
            "prompt_digests": resolved.digests,
            "dataset_revision_id": spec.get("dataset_revision_id"),
        },
    }
    started = time.perf_counter()
    try:
        chat = await router.chat_completions(
            body=body,
            authorization=authorization,
            idempotency_key=str(result_row["id"]),
        )
    except Exception as exc:  # noqa: BLE001
        with connect(settings.database_url) as conn:
            repo.complete_experiment_result(
                conn,
                result_row["id"],
                status="failed",
                trace_id=None,
                output_digest=None,
                latency_ms=int((time.perf_counter() - started) * 1000),
                cost_usd=None,
                scores={},
                error_message=redact(str(exc)),
            )
        return
    latency_ms = int((time.perf_counter() - started) * 1000)
    choices = chat.body.get("choices") or []
    content = ""
    if choices:
        content = (choices[0].get("message") or {}).get("content") or ""
    output_digest = digest_json({"content": content})
    trace_link = {
        "traceparent": chat.traceparent,
        "request_id": chat.request_id,
        "prompt_digests": resolved.digests,
    }
    trace_id = chat.trace_id
    span_id = chat.span_id
    scores: dict[str, Any] = {"prompt_digests": resolved.digests}
    eval_ids = spec.get("evaluator_revision_ids") or []
    with connect(settings.database_url) as conn:
        ref_out = example.get("reference_output_inline")
        if example.get("reference_output_object_ref"):
            from evaluate.domains.datasets import attachments as att

            ref_out = att.load_inline_payload(
                conn,
                settings,
                org_id=org_id,
                project_id=project_id,
                storage_ref=str(example["reference_output_object_ref"]),
            )
        for rev_id in eval_ids:
            rev = repo.get_evaluator_revision(conn, org_id, UUID(str(rev_id)))
            if not rev:
                continue
            cfg = rev["config"] if isinstance(rev["config"], dict) else {}
            ctx: dict[str, Any] = {
                "input": inp,
                "output": content,
                "reference": ref_out,
                "latency_ms": latency_ms,
                "cost_usd": None,
                "tool_calls": [],
            }
            try:
                outcome = await run_evaluator(
                    settings,
                    kind=rev["kind"],
                    config=cfg,
                    context=ctx,
                    router=router,
                    authorization=authorization,
                )
                scores[rev["evaluator_key"]] = outcome
            except Exception as exc:  # noqa: BLE001
                scores[rev["evaluator_key"]] = {"score": 0.0, "error": redact(str(exc))}
        repo.complete_experiment_result(
            conn,
            result_row["id"],
            status="completed",
            trace_id=str(trace_id) if trace_id else None,
            span_id=str(span_id) if span_id else None,
            trace_link=trace_link,
            output_digest=output_digest,
            latency_ms=latency_ms,
            cost_usd=None,
            scores=scores,
            error_message=None,
        )


async def process_experiment_job(settings: Settings, payload: dict[str, Any]) -> None:
    experiment_id = UUID(str(payload["experiment_id"]))
    with connect(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM evaluate.experiments WHERE id = %s", (experiment_id,))
            exp = cur.fetchone()
        if not exp:
            return
        org_id = exp["organization_id"]
        project_id = exp["project_id"]
        spec = exp["spec"] if isinstance(exp["spec"], dict) else {}
        repo.update_experiment_status(conn, org_id, experiment_id, "running")
        batch = repo.claim_experiment_results(conn, experiment_id, limit=int(exp["concurrency"]))
    if not batch:
        with connect(settings.database_url) as conn:
            results = repo.list_experiment_results(conn, org_id, experiment_id)
            pending = [r for r in results if r["status"] in ("pending", "running")]
            status = "completed" if not pending else "partial"
            repo.update_experiment_status(
                conn,
                org_id,
                experiment_id,
                status,
                finished_at=datetime.now(UTC) if status == "completed" else None,
                progress={
                    "total": len(results),
                    "completed": len([r for r in results if r["status"] == "completed"]),
                },
            )
        return
    await asyncio.gather(
        *[
            _run_single_result(
                settings,
                org_id=org_id,
                project_id=project_id,
                experiment_id=experiment_id,
                result_row=row,
                spec=spec,
            )
            for row in batch
        ]
    )
    publish_wake(settings, reason="experiment-continue")
    with connect(settings.database_url) as conn:
        repo.enqueue_job(
            conn,
            org_id=org_id,
            project_id=project_id,
            job_type="experiment_run",
            payload={"experiment_id": str(experiment_id)},
            idempotency_key=f"experiment-run-continue:{experiment_id}:{time.time()}",
            max_attempts=settings.worker_max_attempts,
        )


async def process_job(settings: Settings, job: dict[str, Any]) -> None:
    payload = job["payload"] if isinstance(job["payload"], dict) else {}
    if job["job_type"] == "experiment_run":
        await process_experiment_job(settings, payload)
    elif job["job_type"] == "online_eval":
        await process_online_eval_job(settings, payload)
    elif job["job_type"] == "observe_poll":
        await poll_all_projects(settings)
    elif job["job_type"] == "alert_delivery":
        await process_alert_batch(settings)
    else:
        log.warning("unknown job type %s", job["job_type"])


def run_worker_loop(settings: Settings | None = None) -> None:
    s = settings or get_settings()
    owner = _owner_id()
    log.info("evaluate worker starting as %s", owner)
    last_poll = 0.0
    while True:
        now = time.time()
        if now - last_poll >= s.observe_poll_interval_seconds:
            last_poll = now
            try:
                asyncio.run(poll_all_projects(s))
            except Exception as exc:  # noqa: BLE001
                log.error("observe poll failed: %s", redact(str(exc)))
            try:
                asyncio.run(process_alert_batch(s))
            except Exception as exc:  # noqa: BLE001
                log.error("alert batch failed: %s", redact(str(exc)))
        with connect(s.database_url) as conn:
            repo.requeue_expired_jobs(conn)
            job = repo.claim_job(conn, owner=owner, lease_seconds=s.worker_job_lease_seconds)
        if job:
            try:
                asyncio.run(process_job(s, job))
                with connect(s.database_url) as conn:
                    repo.finish_job(conn, job["id"], status="completed")
            except Exception as exc:  # noqa: BLE001
                log.error("job failed: %s", redact(str(exc)))
                with connect(s.database_url) as conn:
                    status = "dead" if job["attempts"] >= job["max_attempts"] else "pending"
                    repo.finish_job(conn, job["id"], status=status, error=redact(str(exc)))
            continue
        woke = wait_wake(s, s.worker_poll_interval_seconds)
        if not woke:
            time.sleep(s.worker_poll_interval_seconds)
