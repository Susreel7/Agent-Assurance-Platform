"""Deterministic canonicalization and digests."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_content(content: dict[str, Any]) -> str:
    return sha256_hex(canonical_json(content).encode("utf-8"))


def digest_schema(schema: dict[str, Any] | None) -> str | None:
    if schema is None:
        return None
    return sha256_hex(canonical_json(schema).encode("utf-8"))


def digest_config(config: dict[str, Any] | None) -> str | None:
    if config is None:
        return None
    return sha256_hex(canonical_json(config).encode("utf-8"))
