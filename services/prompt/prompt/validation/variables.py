"""Jinja-style variable validation without template execution."""

from __future__ import annotations

import re
from typing import Any

from prompt.errors import ValidationError

_VAR_PATTERN = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_\.]*)\s*\}\}")
_FORBIDDEN = re.compile(r"\{%|\{#|%\}|\#\}")


def extract_variable_names(text: str) -> set[str]:
    if _FORBIDDEN.search(text):
        raise ValidationError("control-flow Jinja constructs are not allowed")
    return set(_VAR_PATTERN.findall(text))


def collect_variables_from_content(content: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    messages = content.get("messages")
    if isinstance(messages, list):
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            body = msg.get("content")
            if isinstance(body, str):
                names |= extract_variable_names(body)
    text = content.get("text")
    if isinstance(text, str):
        names |= extract_variable_names(text)
    document = content.get("document")
    if isinstance(document, str):
        names |= extract_variable_names(document)
    return names


def validate_variables_against_schema(
    variable_names: set[str],
    input_schema: dict[str, Any] | None,
) -> None:
    if not variable_names:
        return
    if input_schema is None:
        raise ValidationError("content uses variables but input_schema is missing")
    props = input_schema.get("properties")
    if not isinstance(props, dict):
        raise ValidationError("input_schema must declare properties for each variable")
    missing = sorted(
        name.split(".")[0] for name in variable_names if name.split(".")[0] not in props
    )
    if missing:
        raise ValidationError(
            f"variables missing from input_schema.properties: {', '.join(missing)}"
        )
