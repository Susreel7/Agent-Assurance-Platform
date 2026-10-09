"""Shared helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest_json(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def deterministic_sample(*, key: str, salt: str, rate: float) -> bool:
    if rate <= 0:
        return False
    if rate >= 1:
        return True
    h = hashlib.sha256(f"{salt}:{key}".encode()).digest()
    bucket = int.from_bytes(h[:4], "big") % 10_000
    return bucket < int(rate * 10_000)
