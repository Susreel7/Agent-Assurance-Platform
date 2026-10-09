"""Edge content capture — strict allowlist for known content fields."""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from collector.config import CaptureMode, Settings

# Only these attribute/event keys are treated as content-bearing at the edge.
CONTENT_ATTR_KEYS: frozenset[str] = frozenset(
    {
        "gen_ai.prompt",
        "gen_ai.completion",
        "gen_ai.input.messages",
        "gen_ai.output.messages",
        "gen_ai.system_instructions",
        "gen_ai.tool.call.arguments",
        "gen_ai.tool.call.result",
        "llm.prompts",
        "llm.completion",
        "input.value",
        "output.value",
        "openinference.input.value",
        "openinference.output.value",
    }
)

_DEFAULT_EMAIL = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
_DEFAULT_PHONE = re.compile(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b")


def digest_value(value: Any) -> str:
    raw = value if isinstance(value, (bytes, bytearray)) else json.dumps(value, default=str)
    if not isinstance(raw, (bytes, bytearray)):
        raw = str(raw).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _compiled_rules(settings: Settings) -> list[tuple[re.Pattern[str], str]]:
    rules: list[tuple[re.Pattern[str], str]] = [
        (_DEFAULT_EMAIL, "[email]"),
        (_DEFAULT_PHONE, "[phone]"),
    ]
    for rule in settings.redaction_regex_rules:
        rules.append((re.compile(rule.pattern), rule.replacement))
    return rules


def redact_text(text: str, settings: Settings) -> str:
    out = text
    for pattern, repl in _compiled_rules(settings):
        out = pattern.sub(repl, out)
    max_preview = settings.redacted_preview_max_bytes
    raw = out.encode("utf-8")
    if len(raw) <= max_preview:
        return out
    return raw[: max_preview - 3].decode("utf-8", errors="ignore") + "..."


def apply_capture(
    mode: CaptureMode,
    field: str,
    value: Any,
    settings: Settings,
) -> dict[str, Any] | None:
    """Return replacement attributes for a content field, or None to strip."""
    if value is None or mode == CaptureMode.NONE:
        return None
    if mode == CaptureMode.DIGEST:
        return {f"{field}.digest": digest_value(value)}
    if mode == CaptureMode.REDACTED:
        preview = redact_text(str(value), settings)
        return {
            f"{field}.digest": digest_value(value),
            f"{field}.preview": preview,
        }
    if mode == CaptureMode.FULL:
        return {field: value, f"{field}.digest": digest_value(value)}
    return None
