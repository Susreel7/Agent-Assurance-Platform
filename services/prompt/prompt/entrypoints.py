"""Process entrypoints."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import uvicorn

from prompt.app import create_app


def run_api() -> None:
    uvicorn.run(create_app(), host="0.0.0.0", port=8095)


def export_openapi() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("openapi.json")
    schema = create_app().openapi()
    out.write_text(json.dumps(schema, indent=2), encoding="utf-8")
