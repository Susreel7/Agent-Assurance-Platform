"""Reliable, content-free Observe to Operations projection dispatcher."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

import httpx

from observe.config import Settings
from observe.db import postgres as pg
from observe.db import repository as repo

log = logging.getLogger(__name__)


def _environment(value: str | None) -> str:
    normalized = (value or "dev").lower()
    return {
        "development": "dev",
        "prod": "production",
        "production": "production",
        "stage": "staging",
    }.get(normalized, normalized if normalized in {"dev", "test", "staging", "retired"} else "dev")


def _run_report(payload: dict[str, Any]) -> dict[str, Any]:
    execution_id = str(payload["execution_id"])
    agent_id = str(payload["agent_id"])
    try:
        run_id = str(uuid.UUID(execution_id))
        canonical_agent_id = str(uuid.UUID(agent_id))
    except ValueError as exc:
        raise ValueError("Operations projection requires UUID execution_id and agent_id") from exc
    started_at = payload.get("started_at")
    ended_at = payload.get("ended_at")
    if not isinstance(started_at, str) or not isinstance(ended_at, str):
        raise ValueError("terminal Operations projection requires start and end timestamps")
    # Validate before sending so malformed outbox rows are retried and visible.
    datetime.fromisoformat(started_at)
    datetime.fromisoformat(ended_at)
    status = str(payload.get("status") or "failed")
    outcome = {
        "success": "succeeded",
        "error": "failed",
        "partial": "failed",
    }.get(status, status)
    return {
        "run_id": run_id,
        "agent_id": canonical_agent_id,
        "agent_version_id": payload.get("agent_version_id"),
        "environment": _environment(payload.get("environment_id")),
        "started_at": started_at,
        "ended_at": ended_at,
        "outcome": outcome,
        "step_count": int(payload.get("span_count") or 0),
        "tool_call_count": int(payload.get("tool_count") or 0),
        "retry_count": int(payload.get("retry_count") or 0),
        "model": payload.get("model"),
        "tokens_in": int(payload.get("tokens_in") or 0),
        "tokens_out": int(payload.get("tokens_out") or 0),
        "cost_micros": int(payload.get("total_cost_micros") or 0),
        "error_kind": "observe_execution_failed" if outcome == "failed" else None,
        "trace_id": payload.get("trace_id"),
        "reported_by": "observe-projection",
        "tools": [],
        "steps": [],
    }


def dispatch_once(settings: Settings) -> int:
    if not settings.operations_projection_url or not settings.operations_projection_bearer:
        return 0
    worker_id = str(uuid.uuid4())
    with pg.connect(settings.database_url, worker=True) as conn:
        rows = repo.claim_projection_outbox(
            conn,
            worker_id=worker_id,
            limit=settings.operations_projection_batch_size,
        )
    dispatched = 0
    for row in rows:
        try:
            report = _run_report(dict(row["payload"]))
            response = httpx.post(
                settings.operations_projection_url,
                headers={"Authorization": f"Bearer {settings.operations_projection_bearer}"},
                json={"runs": [report]},
                timeout=settings.operations_projection_timeout_seconds,
            )
            response.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            log.warning("Operations projection %s failed: %s", row["id"], exc)
            with pg.connect(settings.database_url, worker=True) as conn:
                repo.mark_projection_retry(
                    conn,
                    outbox_id=int(row["id"]),
                    worker_id=worker_id,
                    error=str(exc),
                )
            continue
        with pg.connect(settings.database_url, worker=True) as conn:
            repo.mark_projection_dispatched(
                conn,
                outbox_id=int(row["id"]),
                worker_id=worker_id,
            )
        dispatched += 1
    return dispatched
