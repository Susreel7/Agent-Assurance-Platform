"""Poll Observe evaluate events and enqueue online rule jobs."""

from __future__ import annotations

import logging
from uuid import UUID

from evaluate.clients.observe import ObserveClient
from evaluate.config import Settings
from evaluate.db import repository as repo
from evaluate.db.postgres import connect
from evaluate.domains.online_rules import service as online_service
from evaluate.log_safe import redact
from evaluate.queue.redis_wake import publish_wake

log = logging.getLogger(__name__)


async def poll_observe_for_project(
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
) -> int:
    bearer = settings.observe_worker_bearer or settings.internal_service_token
    client = ObserveClient(settings)
    with connect(settings.database_url) as conn:
        cursor = repo.get_observe_cursor(conn, org_id, project_id)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM evaluate.online_rules
                WHERE organization_id = %s AND project_id = %s AND enabled = TRUE
                """,
                (org_id, project_id),
            )
            rule_rows = list(cur.fetchall())
    data = await client.poll_events(
        org_id=str(org_id),
        project_id=str(project_id),
        cursor=cursor,
        authorization=f"Bearer {bearer}",
    )
    events = data.get("events")
    if not isinstance(events, list):
        return 0
    next_cursor = str(data.get("next_cursor") or cursor)
    enqueued = 0
    for event in events:
        if not isinstance(event, dict):
            continue
        trace_id = str(event.get("trace_id") or "")
        if not trace_id:
            continue
        meta_raw = event.get("metadata")
        metadata: dict[str, object] = meta_raw if isinstance(meta_raw, dict) else {}
        for rule_row in rule_rows:
            try:
                with connect(settings.database_url) as conn:
                    job_id = online_service.ingest_trace_event(
                        conn,
                        settings,
                        org_id=org_id,
                        project_id=project_id,
                        rule_id=rule_row["id"],
                        trace_id=trace_id,
                        metadata={str(k): v for k, v in metadata.items()},
                    )
                if job_id:
                    enqueued += 1
            except Exception as exc:  # noqa: BLE001
                log.debug("poll ingest skipped: %s", redact(str(exc)))
    with connect(settings.database_url) as conn:
        repo.set_observe_cursor(conn, org_id, project_id, next_cursor)
    if enqueued:
        publish_wake(settings, reason="observe-poll")
    return enqueued


async def poll_all_projects(settings: Settings) -> int:
    with connect(settings.database_url) as conn:
        projects = repo.list_online_rule_projects(conn)
    total = 0
    for row in projects:
        total += await poll_observe_for_project(
            settings,
            org_id=row["organization_id"],
            project_id=row["project_id"],
        )
    return total
