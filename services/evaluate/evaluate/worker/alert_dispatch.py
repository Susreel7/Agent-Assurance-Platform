"""Durable webhook/alert delivery with retries."""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

import httpx

from evaluate.config import Settings
from evaluate.db import repository as repo
from evaluate.db.postgres import connect
from evaluate.log_safe import redact
from evaluate.util import digest_json

log = logging.getLogger(__name__)


async def deliver_webhook(settings: Settings, *, target: str, payload: dict[str, Any]) -> None:
    async with httpx.AsyncClient(timeout=settings.upstream_timeout_seconds) as client:
        resp = await client.post(target, json=payload)
    if resp.status_code >= 400:
        msg = f"webhook status {resp.status_code}"
        raise RuntimeError(msg)


async def process_alert_batch(
    settings: Settings,
    *,
    limit: int = 10,
    organization_id: UUID | None = None,
) -> None:
    with connect(settings.database_url) as conn:
        alerts = repo.claim_pending_alerts(conn, limit=limit, organization_id=organization_id)
    for alert in alerts:
        stored = alert.get("payload")
        if isinstance(stored, dict) and stored:
            payload = dict(stored)
        else:
            payload = {"payload_digest": alert["payload_digest"]}
        payload["action_type"] = alert["action_type"]
        try:
            if alert["action_type"] == "webhook":
                await deliver_webhook(settings, target=str(alert["target"]), payload=payload)
            with connect(settings.database_url) as conn:
                repo.finish_alert_delivery(conn, alert["id"], status="delivered")
        except Exception as exc:  # noqa: BLE001
            log.warning("alert delivery failed: %s", redact(str(exc)))
            if int(alert["attempts"]) >= int(alert["max_attempts"]):
                status = "dead"
            else:
                status = "pending"
            with connect(settings.database_url) as conn:
                repo.finish_alert_delivery(conn, alert["id"], status=status, error=redact(str(exc)))


def schedule_webhook_action(
    conn: Any,
    settings: Settings,
    *,
    org_id: Any,
    project_id: Any,
    rule_id: Any,
    target: str,
    payload: dict[str, Any],
    idempotency_key: str,
) -> None:
    digest = digest_json(payload)
    safe_payload = {
        k: v for k, v in payload.items() if k in ("trace_id", "scores", "rule_id", "event_type")
    }
    repo.enqueue_alert_delivery(
        conn,
        org_id=org_id,
        project_id=project_id,
        rule_id=rule_id,
        action_type="webhook",
        target=target,
        payload_digest=digest,
        payload=safe_payload,
        idempotency_key=idempotency_key,
        max_attempts=settings.worker_max_attempts,
    )
