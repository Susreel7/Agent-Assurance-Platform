"""Deterministic evaluator implementations."""

from __future__ import annotations

import re
from typing import Any

import jsonschema

from evaluate.errors import ValidationError


def eval_exact_match(config: dict[str, Any], *, output: Any, reference: Any) -> dict[str, Any]:
    normalize = bool(config.get("normalize_whitespace", False))
    out_s = str(output)
    ref_s = str(reference)
    if normalize:
        out_s = " ".join(out_s.split())
        ref_s = " ".join(ref_s.split())
    passed = out_s == ref_s
    return {"score": 1.0 if passed else 0.0, "passed": passed}


def eval_regex(config: dict[str, Any], *, output: Any) -> dict[str, Any]:
    pattern = config.get("pattern")
    if not pattern or not isinstance(pattern, str):
        raise ValidationError("regex evaluator requires pattern")
    flags = 0
    if config.get("ignore_case"):
        flags |= re.IGNORECASE
    matched = re.search(pattern, str(output), flags) is not None
    invert = bool(config.get("invert"))
    passed = matched if not invert else not matched
    return {"score": 1.0 if passed else 0.0, "passed": passed}


def eval_json_schema(config: dict[str, Any], *, output: Any) -> dict[str, Any]:
    schema = config.get("schema")
    if not isinstance(schema, dict):
        raise ValidationError("json_schema evaluator requires schema object")
    try:
        jsonschema.validate(instance=output, schema=schema)
    except jsonschema.ValidationError:
        return {"score": 0.0, "passed": False}
    return {"score": 1.0, "passed": True}


def eval_latency_ms(config: dict[str, Any], *, latency_ms: int | None) -> dict[str, Any]:
    if latency_ms is None:
        return {"score": 0.0, "passed": False}
    max_ms = int(config.get("max_ms", 30_000))
    passed = latency_ms <= max_ms
    return {"score": 1.0 if passed else 0.0, "passed": passed, "latency_ms": latency_ms}


def eval_cost_usd(config: dict[str, Any], *, cost_usd: float | None) -> dict[str, Any]:
    if cost_usd is None:
        return {"score": 0.0, "passed": False}
    max_cost = float(config.get("max_usd", 1.0))
    passed = cost_usd <= max_cost
    return {"score": 1.0 if passed else 0.0, "passed": passed, "cost_usd": cost_usd}


def eval_tool_trajectory(config: dict[str, Any], *, tool_calls: list[str] | None) -> dict[str, Any]:
    expected = config.get("expected_tools")
    if not isinstance(expected, list):
        raise ValidationError("tool_trajectory requires expected_tools list")
    actual = tool_calls or []
    passed = actual == [str(x) for x in expected]
    return {"score": 1.0 if passed else 0.0, "passed": passed, "actual": actual}
