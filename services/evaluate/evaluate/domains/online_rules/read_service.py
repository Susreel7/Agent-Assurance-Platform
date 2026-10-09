"""Bounded online rule and alert read APIs."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from evaluate.api.listing import keyset_page
from evaluate.config import Settings
from evaluate.db import repository as repo
from evaluate.db.postgres import PgConn
from evaluate.domains.common_schemas import PagedResponse, PageMeta
from evaluate.domains.online_rules.schemas import AlertOut, OnlineRuleOut
from evaluate.errors import NotFoundError
from evaluate.queue.redis_wake import publish_wake


def list_rules(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[OnlineRuleOut]:
    rows, total, lim, next_cursor = keyset_page(
        settings,
        limit=limit,
        cursor=cursor,
        count=lambda: repo.count_online_rules(conn, org_id, project_id),
        fetch=lambda **kw: repo.list_online_rules(conn, org_id, project_id, **kw),
    )
    return PagedResponse(
        items=[OnlineRuleOut.model_validate(r) for r in rows],
        meta=PageMeta(total=total, limit=lim, next_cursor=next_cursor),
    )


def get_rule(conn: PgConn, org_id: UUID, project_id: UUID, rule_id: UUID) -> OnlineRuleOut:
    row = repo.get_online_rule(conn, org_id, project_id, rule_id)
    if not row:
        raise NotFoundError("online rule not found")
    return OnlineRuleOut.model_validate(row)


def list_alerts(
    conn: PgConn,
    settings: Settings,
    *,
    org_id: UUID,
    project_id: UUID,
    status: str | None,
    rule_id: UUID | None,
    limit: int | None,
    cursor: str | None,
) -> PagedResponse[AlertOut]:
    def count() -> int:
        return repo.count_alert_deliveries(conn, org_id, project_id, status=status, rule_id=rule_id)

    def fetch(**kw: Any) -> list[dict[str, Any]]:
        return repo.list_alert_deliveries(
            conn, org_id, project_id, status=status, rule_id=rule_id, **kw
        )

    rows, total, lim, next_cursor = keyset_page(
        settings, limit=limit, cursor=cursor, count=count, fetch=fetch
    )
    return PagedResponse(
        items=[AlertOut.model_validate(r) for r in rows],
        meta=PageMeta(total=total, limit=lim, next_cursor=next_cursor),
    )


def get_alert(conn: PgConn, org_id: UUID, project_id: UUID, alert_id: UUID) -> AlertOut:
    row = repo.get_alert_delivery(conn, org_id, project_id, alert_id)
    if not row:
        raise NotFoundError("alert not found")
    return AlertOut.model_validate(row)


def retry_alert(
    conn: PgConn,
    settings: Settings,
    org_id: UUID,
    project_id: UUID,
    alert_id: UUID,
) -> AlertOut:
    if not repo.retry_alert_delivery(conn, org_id, project_id, alert_id):
        raise NotFoundError("alert not found")
    publish_wake(settings, reason="alert-retry")
    row = repo.get_alert_delivery(conn, org_id, project_id, alert_id)
    assert row
    return AlertOut.model_validate(row)


def acknowledge_alert(conn: PgConn, org_id: UUID, project_id: UUID, alert_id: UUID) -> AlertOut:
    if not repo.acknowledge_alert_delivery(conn, org_id, project_id, alert_id):
        raise NotFoundError("alert not found")
    row = repo.get_alert_delivery(conn, org_id, project_id, alert_id)
    assert row
    return AlertOut.model_validate(row)
