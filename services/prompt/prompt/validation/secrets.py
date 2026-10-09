"""Heuristic secret scanning — warnings only, never blocks by default."""

from __future__ import annotations

import re
from typing import Any

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("aws_access_key", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("private_key_block", re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----")),
    ("generic_api_key", re.compile(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*['\"][^'\"]{8,}")),
]


def scan_secrets_in_text(text: str) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    for name, pattern in _PATTERNS:
        if pattern.search(text):
            warnings.append({"kind": name, "message": f"possible {name} pattern detected"})
    return warnings


def scan_secrets_in_content(content: dict[str, Any]) -> list[dict[str, str]]:
    warnings: list[dict[str, str]] = []
    messages = content.get("messages")
    if isinstance(messages, list):
        for msg in messages:
            if isinstance(msg, dict):
                body = msg.get("content")
                if isinstance(body, str):
                    warnings.extend(scan_secrets_in_text(body))
    body_text = content.get("text")
    if isinstance(body_text, str):
        warnings.extend(scan_secrets_in_text(body_text))
    raw = content.get("document")
    if isinstance(raw, str):
        warnings.extend(scan_secrets_in_text(raw))
    return warnings
