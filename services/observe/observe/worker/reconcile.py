"""Manifest ↔ object store reconciliation."""

from __future__ import annotations

import logging

from observe.config import Settings
from observe.db import postgres as pg
from observe.db import repository as repo
from observe.providers.object_store.base import ObjectStore

log = logging.getLogger(__name__)


def reconcile_manifest_objects(settings: Settings, store: ObjectStore, *, batch: int = 50) -> int:
    quarantined = 0
    with pg.connect(settings.database_url, worker=True) as conn:
        manifests = repo.manifests_missing_object(conn, limit=batch)
    for manifest in manifests:
        if store.exists(manifest.object_key):
            continue
        with pg.connect(settings.database_url, worker=True) as conn:
            repo.insert_quarantine(
                conn,
                org_id=manifest.organization_id,
                project_id=manifest.project_id,
                reason="missing_object",
                envelope_digest=manifest.envelope_digest,
                manifest_id=manifest.id,
                detail={"object_key": manifest.object_key},
            )
            repo.mark_manifest_quarantined(conn, manifest.id, "object missing at reconcile")
        quarantined += 1
        log.warning("quarantined manifest %s — object missing", manifest.id)
    return quarantined
