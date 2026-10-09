"""Delete expired payload objects while preserving legal holds."""

from __future__ import annotations

import logging

from observe.config import Settings
from observe.db import postgres as pg
from observe.db import repository as repo
from observe.providers.object_store.base import ObjectStore

log = logging.getLogger(__name__)


def sweep_expired_payloads(
    settings: Settings,
    store: ObjectStore,
    *,
    limit: int | None = None,
) -> int:
    deleted = 0
    batch_size = limit or settings.retention_sweep_batch_size
    with pg.connect(settings.database_url, worker=True) as conn:
        rows = repo.claim_expired_payload_objects(conn, limit=batch_size)
        processed_keys: set[str] = set()
        for row in rows:
            object_key = str(row["object_key"])
            if object_key in processed_keys:
                continue
            processed_keys.add(object_key)
            try:
                store.delete(object_key)
            except Exception:  # noqa: BLE001
                log.exception("failed to delete expired payload object %s", object_key)
                continue
            deleted += repo.mark_payload_object_retention_deleted(
                conn,
                org_id=row["organization_id"],
                project_id=row["project_id"],
                object_key=object_key,
            )
    return deleted
