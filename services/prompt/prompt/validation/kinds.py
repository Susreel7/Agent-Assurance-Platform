"""Per-artifact-kind structure validation."""

from __future__ import annotations

from typing import Any

from prompt.config import ARTIFACT_KINDS
from prompt.errors import PayloadTooLargeError, ValidationError
from prompt.validation.messages import validate_messages
from prompt.validation.variables import (
    collect_variables_from_content,
    validate_variables_against_schema,
)


def validate_kind_structure(
    kind: str,
    content: dict[str, Any],
    *,
    input_schema: dict[str, Any] | None,
    max_body_bytes: int,
) -> set[str]:
    if kind not in ARTIFACT_KINDS:
        raise ValidationError(f"unsupported artifact kind: {kind}")

    encoded_len = len(str(content).encode("utf-8"))
    if encoded_len > max_body_bytes:
        raise PayloadTooLargeError(f"content exceeds max_body_bytes ({max_body_bytes})")

    if kind == "prompt":
        if "messages" not in content:
            raise ValidationError("prompt artifacts require messages")
        validate_messages(content["messages"])
    elif kind == "rule":
        if not isinstance(content.get("rules"), list) or not content["rules"]:
            raise ValidationError("rule artifacts require non-empty rules list")
    elif kind == "skill":
        if not isinstance(content.get("steps"), list) or not content["steps"]:
            raise ValidationError("skill artifacts require non-empty steps list")
    elif kind == "context":
        if not isinstance(content.get("document"), str) or not content["document"].strip():
            raise ValidationError("context artifacts require non-empty document string")

    variables = collect_variables_from_content(content)
    validate_variables_against_schema(variables, input_schema)
    return variables
