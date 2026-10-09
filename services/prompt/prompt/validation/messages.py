"""Chat message role schema validation."""

from __future__ import annotations

from typing import Any

from prompt.errors import ValidationError

ALLOWED_ROLES = frozenset({"system", "user", "assistant", "tool"})


def validate_messages(messages: Any) -> None:
    if not isinstance(messages, list) or not messages:
        raise ValidationError("prompt messages must be a non-empty list")
    for idx, msg in enumerate(messages):
        if not isinstance(msg, dict):
            raise ValidationError(f"message[{idx}] must be an object")
        role = msg.get("role")
        if role not in ALLOWED_ROLES:
            raise ValidationError(f"message[{idx}] has invalid role: {role!r}")
        content = msg.get("content")
        if content is None:
            raise ValidationError(f"message[{idx}] missing content")
        if not isinstance(content, (str, list)):
            raise ValidationError(f"message[{idx}] content must be string or parts list")
