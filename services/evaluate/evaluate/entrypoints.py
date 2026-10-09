"""Process entrypoints."""

from __future__ import annotations

import uvicorn

from evaluate.app import create_app
from evaluate.config import get_settings
from evaluate.worker.runner import run_worker_loop


def run_api() -> None:
    settings = get_settings()
    uvicorn.run(create_app(), host="0.0.0.0", port=settings.api_port)


def run_worker() -> None:
    run_worker_loop()


def export_openapi() -> None:
    import json
    import sys

    schema = create_app().openapi()
    json.dump(schema, sys.stdout, indent=2)
    sys.stdout.write("\n")
