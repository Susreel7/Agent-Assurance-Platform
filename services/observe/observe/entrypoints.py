"""Process entrypoints: ingest, worker, query."""

from __future__ import annotations

import logging

import uvicorn

logging.basicConfig(level=logging.INFO)


def run_ingest() -> None:
    uvicorn.run(
        "observe.ingest.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=8080,
        log_level="info",
    )


def run_worker() -> None:
    from observe.worker.app import run_worker_http

    run_worker_http()


def run_query() -> None:
    uvicorn.run(
        "observe.query.app:create_app",
        factory=True,
        host="0.0.0.0",
        port=8082,
        log_level="info",
    )
