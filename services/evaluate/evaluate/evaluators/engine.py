"""Evaluator dispatch."""

from __future__ import annotations

from typing import Any

from evaluate.clients.router import RouterClient
from evaluate.config import Settings
from evaluate.errors import ValidationError
from evaluate.evaluators import deterministic, llm_judge, python_sandbox


async def run_evaluator(
    settings: Settings,
    *,
    kind: str,
    config: dict[str, Any],
    context: dict[str, Any],
    router: RouterClient | None = None,
    authorization: str = "",
) -> dict[str, Any]:
    output = context.get("output")
    reference = context.get("reference")
    if kind == "exact_match":
        return deterministic.eval_exact_match(config, output=output, reference=reference)
    if kind == "regex":
        return deterministic.eval_regex(config, output=output)
    if kind == "json_schema":
        return deterministic.eval_json_schema(config, output=output)
    if kind == "latency_ms":
        return deterministic.eval_latency_ms(config, latency_ms=context.get("latency_ms"))
    if kind == "cost_usd":
        cost = context.get("cost_usd")
        return deterministic.eval_cost_usd(
            config, cost_usd=float(cost) if cost is not None else None
        )
    if kind == "tool_trajectory":
        return deterministic.eval_tool_trajectory(config, tool_calls=context.get("tool_calls"))
    if kind == "python_function":
        source = config.get("source")
        if not isinstance(source, str):
            raise ValidationError("python_function requires source")
        return python_sandbox.run_python_evaluator(settings, source=source, payload=context)
    if kind == "llm_judge":
        if router is None:
            raise ValidationError("llm_judge requires router client")
        return await llm_judge.run_llm_judge(
            router,
            config=config,
            authorization=authorization,
            input_text=str(context.get("input", "")),
            output_text=str(output or ""),
            reference_text=str(reference) if reference is not None else None,
        )
    raise ValidationError(f"unknown evaluator kind: {kind}")
