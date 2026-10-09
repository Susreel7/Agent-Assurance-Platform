"""Content capture policy aligned with Observe ingest contract."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from typing import Any


class CaptureMode(StrEnum):
    NONE = "none"
    DIGEST = "digest"
    REDACTED = "redacted"
    FULL = "full"


_EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_PHONE = re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b")


def digest_value(value: Any) -> str:
    raw = value if isinstance(value, (bytes, bytearray)) else json.dumps(value, default=str)
    if not isinstance(raw, (bytes, bytearray)):
        raw = str(raw).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def redact_text(text: str, *, max_preview: int = 256) -> str:
    out = _EMAIL.sub("[email]", text)
    out = _PHONE.sub("[phone]", out)
    if len(out) > max_preview:
        return out[: max_preview - 3] + "..."
    return out


def apply_capture(mode: CaptureMode, field: str, value: Any) -> dict[str, Any] | None:
    """Return attribute/event payload for a content field, or None to omit."""
    if value is None or mode == CaptureMode.NONE:
        return None
    if mode == CaptureMode.DIGEST:
        return {f"{field}.digest": digest_value(value)}
    if mode == CaptureMode.REDACTED:
        preview = redact_text(str(value))
        return {
            f"{field}.digest": digest_value(value),
            f"{field}.preview": preview,
        }
    if mode == CaptureMode.FULL:
        return {field: value, f"{field}.digest": digest_value(value)}
    return None
