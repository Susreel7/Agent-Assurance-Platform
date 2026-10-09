"""Evaluator versioning and dry-run."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from evaluate.clients.router import RouterClient
from evaluate.config import EVALUATOR_KINDS, Settings
from evaluate.db import repository as repo
from evaluate.db.postgres import PgConn
from evaluate.errors import NotFoundError, ValidationError
from evaluate.evaluators.engine import run_evaluator
from evaluate.util import digest_json


def create_evaluator(
    conn: PgConn,
    *,
    org_id: UUID,
    project_id: UUID,
    evaluator_key: str,
    display_name: str,
    kind: str,
    config: dict[str, Any],
    actor: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if kind not in EVALUATOR_KINDS:
        raise ValidationError(f"unsupported evaluator kind: {kind}")
    existing = repo.get_evaluator_by_key(conn, org_id, project_id, evaluator_key)
    if existing:
        ev_id = existing["id"]
    else:
        ev_id = repo.insert_evaluator(
            conn,
            org_id=org_id,
            project_id=project_id,
            evaluator_key=evaluator_key,
            display_name=display_name,
            kind=kind,
            actor=actor,
        )
        existing = repo.get_evaluator_by_key(conn, org_id, project_id, evaluator_key)
    assert existing is not None
    rev_num = repo.latest_evaluator_revision_number(conn, ev_id) + 1
    config_digest = digest_json(config)
    rev_id = repo.insert_evaluator_revision(
        conn,
        evaluator_id=ev_id,
        org_id=org_id,
        project_id=project_id,
        revision_number=rev_num,
        config=config,
        config_digest=config_digest,
        actor=actor,
    )
    rev = repo.get_evaluator_revision(conn, org_id, rev_id)
    assert rev is not None
    return existing, rev


async def dry_run(
    settings: Settings,
    *,
    conn: PgConn,
    org_id: UUID,
    revision_id: UUID | None,
    kind: str | None,
    config: dict[str, Any] | None,
    context: dict[str, Any],
    authorization: str,
) -> dict[str, Any]:
    if revision_id:
        rev = repo.get_evaluator_revision(conn, org_id, revision_id)
        if not rev:
            raise NotFoundError("evaluator revision not found")
        kind = rev["kind"]
        cfg = rev["config"] if isinstance(rev["config"], dict) else {}
    else:
        if not kind or config is None:
            raise ValidationError("kind and config required without revision_id")
        cfg = config
    router = RouterClient(settings)
    return await run_evaluator(
        settings,
        kind=str(kind),
        config=cfg if isinstance(cfg, dict) else {},
        context=context,
        router=router,
        authorization=authorization,
    )
