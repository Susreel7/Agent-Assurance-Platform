"""LLM-as-judge through Router with pinned rubric revision."""

from __future__ import annotations

from typing import Any

from evaluate.clients.router import RouterClient
from evaluate.errors import ValidationError


async def run_llm_judge(
    router: RouterClient,
    *,
    config: dict[str, Any],
    authorization: str,
    input_text: str,
    output_text: str,
    reference_text: str | None,
) -> dict[str, Any]:
    model = config.get("model_alias")
    if not isinstance(model, str) or not model:
        raise ValidationError("llm_judge requires model_alias")
    rubric = config.get("rubric", "")
    system = config.get(
        "system_prompt",
        "You are an evaluation judge. Respond with JSON: "
        '{"score": number between 0 and 1, "passed": boolean, "explanation": string}',
    )
    user = (
        f"Rubric:\n{rubric}\n\nInput:\n{input_text}\n\nOutput:\n{output_text}\n"
        f"\nReference:\n{reference_text or '(none)'}\n"
    )
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    chat = await router.chat_completions(body=body, authorization=authorization)
    choices = chat.body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ValidationError("llm judge returned no choices")
    message = choices[0].get("message", {})
    content = message.get("content", "{}")
    import json

    try:
        parsed = json.loads(content if isinstance(content, str) else "{}")
    except json.JSONDecodeError as exc:
        raise ValidationError("llm judge returned non-JSON content") from exc
    if not isinstance(parsed, dict):
        raise ValidationError("llm judge JSON must be object")
    return parsed
