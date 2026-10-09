"""LlamaIndex callback handler stub."""

from __future__ import annotations

from typing import Any

from aap_trace.integrations._optional import require_package
from aap_trace.spans import generation_span, retrieval_span

require_package("llama_index.core", "llama-index")
CallbackManager = require_package("llama_index.core.callbacks", "llama-index")


class AAPLlamaIndexHandler:
    """Minimal handler mapping query and LLM events."""

    def on_event_start(
        self, event_type: str, payload: dict[str, Any] | None = None, **kwargs: Any
    ) -> str:
        payload = payload or {}
        if event_type == "llm":
            cm = generation_span(provider="llama_index", model=str(payload.get("model", "llm")))
            cm.__enter__()
            return "llm"
        if event_type == "query":
            cm = retrieval_span(query=str(payload.get("query", "")))
            cm.__enter__()
            return "query"
        return event_type

    def on_event_end(self, event_type: str, **kwargs: Any) -> None:
        return
