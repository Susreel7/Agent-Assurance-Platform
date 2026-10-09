"""Canonical hex IDs for OTLP JSON / protobuf-json wire forms."""

from __future__ import annotations

import base64


def canonical_trace_id(raw: str) -> str:
    return _canonical_id(raw, hex_len=32)


def canonical_span_id(raw: str) -> str:
    return _canonical_id(raw, hex_len=16)


def _canonical_id(raw: str, *, hex_len: int) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if len(text) == hex_len and all(ch in "0123456789abcdefABCDEF" for ch in text):
        return text.lower()
    try:
        decoded = base64.b64decode(text, validate=False)
        if decoded:
            hexed = decoded.hex()
            if len(hexed) == hex_len:
                return hexed
    except Exception:
        pass
    return text[:hex_len] if len(text) > hex_len else text
