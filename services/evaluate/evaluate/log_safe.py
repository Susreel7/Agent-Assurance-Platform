"""Redact sensitive material from log-oriented strings."""

from __future__ import annotations

import re

_BEARER = re.compile(r"(Bearer\s+)[^\s]+", re.IGNORECASE)
_KEYish = re.compile(
    r'("(password|token|secret|authorization|api_key)"\s*:\s*")[^"]*"', re.IGNORECASE
)


def redact(text: str, *, max_len: int = 512) -> str:
    out = _BEARER.sub(r"\1***", text)
    out = _KEYish.sub(r'\1***"', out)
    if len(out) > max_len:
        return out[: max_len - 3] + "..."
    return out
