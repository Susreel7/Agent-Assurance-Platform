"""Graceful handling when optional integration dependencies are missing."""

from __future__ import annotations

import importlib
import importlib.util
from typing import Any


def missing_package_message(extra: str) -> str:
    return f"Install aap-trace[{extra}] to use this integration."


def require_package(name: str, extra: str) -> Any:
    if importlib.util.find_spec(name) is None:
        raise ImportError(missing_package_message(extra))
    return importlib.import_module(name)
