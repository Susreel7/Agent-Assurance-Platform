"""Audit read API."""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from prompt.db import repository as repo
from prompt.db.postgres import PgConn
from prompt.domains.audit.schemas import AuditEntryOut, AuditListResponse


def list_audit_events(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    resource_type: str | None,
    action: str | None,
    actor: str | None,
    since: datetime | None,
    until: datetime | None,
    cursor: datetime | None,
    limit: int,
) -> AuditListResponse:
    rows, next_cursor = repo.list_audit(
        conn,
        org_id=org_id,
        project_id=project_id,
        resource_type=resource_type,
        action=action,
        actor=actor,
        since=since,
        until=until,
        cursor_time=cursor,
        limit=limit,
    )
    items = [
        AuditEntryOut(
            id=r["id"],
            action=r["action"],
            resource_type=r["resource_type"],
            resource_id=r["resource_id"],
            actor=r["actor"],
            detail=dict(r.get("detail") or {}),
            created_at=r["created_at"],
        )
        for r in rows
    ]
    return AuditListResponse(items=items, next_cursor=next_cursor)


def export_audit_ndjson(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    resource_type: str | None,
    action: str | None,
    actor: str | None,
    since: datetime | None,
    until: datetime | None,
    limit: int,
) -> str:
    rows, _ = repo.list_audit(
        conn,
        org_id=org_id,
        project_id=project_id,
        resource_type=resource_type,
        action=action,
        actor=actor,
        since=since,
        until=until,
        cursor_time=None,
        limit=limit,
    )
    lines = []
    for r in rows:
        payload = {
            "id": str(r["id"]),
            "action": r["action"],
            "resource_type": r["resource_type"],
            "resource_id": str(r["resource_id"]),
            "actor": r["actor"],
            "detail": dict(r.get("detail") or {}),
            "created_at": r["created_at"].isoformat(),
        }
        lines.append(json.dumps(payload, sort_keys=True))
    return "\n".join(lines) + ("\n" if lines else "")
