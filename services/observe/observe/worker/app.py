"""Normalize worker process loop."""

from __future__ import annotations

import logging
import time

import uvicorn
from fastapi import FastAPI

from observe.clickhouse.client import ClickHouseClient
from observe.clickhouse.migrations_runner import apply_clickhouse_migrations
from observe.config import get_settings
from observe.db.postgres import ping as pg_ping
from observe.health import build_health_router
from observe.migrations.runner import apply_migrations
from observe.providers.object_store.factory import build_object_store
from observe.worker import processor, projection, retention

log = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.run_migrations_on_startup:
        apply_migrations(settings.database_url)

    store = build_object_store(settings)
    ch = ClickHouseClient(settings)
    if settings.run_clickhouse_init_on_startup:
        apply_clickhouse_migrations(settings, ch)
    app = FastAPI(title="Observe Worker", version="0.1.0")
    app.include_router(
        build_health_router(
            check_postgres=True,
            check_clickhouse=True,
            postgres_ping=lambda: pg_ping(settings.database_url),
            clickhouse_ping=ch.ping,
        )
    )

    @app.on_event("startup")
    def _start_loop() -> None:
        import threading

        def loop() -> None:
            last_retention_sweep = 0.0
            while True:
                try:
                    n = processor.run_worker_once(settings, store, ch)
                    if n:
                        log.info("processed %s manifests", n)
                    projected = projection.dispatch_once(settings)
                    if projected:
                        log.info("projected %s executions to Operations", projected)
                    now = time.monotonic()
                    if now - last_retention_sweep >= settings.retention_sweep_interval_seconds:
                        deleted = retention.sweep_expired_payloads(settings, store)
                        last_retention_sweep = now
                        if deleted:
                            log.info("deleted %s expired payloads", deleted)
                except Exception:  # noqa: BLE001
                    log.exception("worker loop error")
                time.sleep(settings.worker_poll_interval_seconds)

        t = threading.Thread(target=loop, name="observe-worker", daemon=True)
        t.start()

    return app


def run_worker_http() -> None:
    uvicorn.run(
        "observe.worker.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=8081,
        log_level="info",
    )
