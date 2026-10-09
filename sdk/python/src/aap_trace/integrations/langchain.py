"""LangChain BaseCallbackHandler for runs, tools, and LLM calls."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from aap_trace.attributes import generation_attrs
from aap_trace.capture import apply_capture
from aap_trace.client import get_client
from aap_trace.integrations._optional import require_package
from aap_trace.spans import ManagedSpan, record_tool_result, start_managed_span

require_package("langchain_core", "langchain")
_lc_callbacks = require_package("langchain_core.callbacks", "langchain")
_LangChainHandlerBase = _lc_callbacks.BaseCallbackHandler


class AAPLangChainHandler(_LangChainHandlerBase):
    """Maps LangChain callbacks to GenAI spans."""

    def __init__(self) -> None:
        self._spans: dict[UUID, ManagedSpan] = {}

    def _parent(self, parent_run_id: UUID | None) -> Any:
        parent = self._spans.get(parent_run_id) if parent_run_id is not None else None
        return parent.span if parent is not None else None

    def _start(
        self,
        run_id: UUID,
        parent_run_id: UUID | None,
        name: str,
        attrs: dict[str, Any],
    ) -> ManagedSpan:
        attrs["aap.framework.name"] = "langchain"
        attrs["aap.framework.run_id"] = str(run_id)
        if parent_run_id is not None:
            attrs["aap.framework.parent_run_id"] = str(parent_run_id)
        managed = start_managed_span(
            name,
            parent_span=self._parent(parent_run_id),
            **attrs,
        )
        self._spans[run_id] = managed
        return managed

    def _start_generation(
        self,
        serialized: dict[str, Any],
        inputs: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None,
        invocation_params: dict[str, Any] | None = None,
    ) -> None:
        params = invocation_params or {}
        serialized_kwargs = serialized.get("kwargs", {})
        model = (
            params.get("model")
            or params.get("model_name")
            or serialized_kwargs.get("model")
            or serialized_kwargs.get("model_name")
            or serialized.get("name")
            or "llm"
        )
        serialized_id = serialized.get("id")
        provider_hint = (
            serialized_id[-1]
            if isinstance(serialized_id, list) and serialized_id
            else serialized_id
        )
        provider = serialized_kwargs.get("_type") or provider_hint or "langchain"
        attrs = generation_attrs(
            provider=str(provider).lower(),
            model=str(model),
            capture_mode=get_client().config.capture_mode,
            input_messages=inputs,
        )
        attrs.update(
            {
                "aap.observation.type": "generation",
                "gen_ai.request.temperature": params.get("temperature"),
                "gen_ai.request.max_tokens": params.get("max_tokens"),
            }
        )
        self._start(run_id, parent_run_id, f"generation:{model}", attrs)

    def on_llm_start(
        self,
        serialized: dict[str, Any],
        prompts: list[str],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self._start_generation(
            serialized,
            prompts,
            run_id=run_id,
            parent_run_id=parent_run_id,
            invocation_params=kwargs.get("invocation_params"),
        )

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[Any]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self._start_generation(
            serialized,
            messages,
            run_id=run_id,
            parent_run_id=parent_run_id,
            invocation_params=kwargs.get("invocation_params"),
        )

    def on_llm_end(self, response: Any, *, run_id: UUID, **kwargs: Any) -> None:
        managed = self._spans.pop(run_id, None)
        if managed is not None:
            generations = getattr(response, "generations", None)
            if generations:
                captured = apply_capture(
                    get_client().config.capture_mode,
                    "gen_ai.output.messages",
                    generations,
                )
                for key, value in (captured or {}).items():
                    managed.span.set_attribute(key, str(value))
            llm_output = getattr(response, "llm_output", None) or {}
            usage = llm_output.get("token_usage", llm_output.get("usage", {}))
            input_tokens = usage.get("prompt_tokens", usage.get("input_tokens"))
            output_tokens = usage.get("completion_tokens", usage.get("output_tokens"))
            if input_tokens is not None:
                managed.span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
            if output_tokens is not None:
                managed.span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
            managed.finish()

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        managed = self._spans.pop(run_id, None)
        if managed is not None:
            managed.finish(error)

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        name = serialized.get("name", "tool")
        attrs = {
            "gen_ai.operation.name": "execute_tool",
            "aap.observation.type": "tool",
            "gen_ai.tool.name": str(name),
            "gen_ai.tool.type": serialized.get("type", "function"),
            **(
                apply_capture(
                    get_client().config.capture_mode,
                    "gen_ai.tool.call.arguments",
                    kwargs.get("inputs", input_str),
                )
                or {}
            ),
        }
        self._start(run_id, parent_run_id, f"tool:{name}", attrs)

    def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        managed = self._spans.pop(run_id, None)
        if managed is not None:
            record_tool_result(managed.span, output)
            managed.finish()

    def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        managed = self._spans.pop(run_id, None)
        if managed is not None:
            managed.finish(error)

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: dict[str, Any],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        name = kwargs.get("name") or serialized.get("name") or "chain"
        captured = apply_capture(
            get_client().config.capture_mode,
            "aap.chain.input",
            inputs,
        )
        self._start(
            run_id,
            parent_run_id,
            str(name),
            {
                "gen_ai.operation.name": "workflow",
                "aap.observation.type": "chain",
                **(captured or {}),
            },
        )

    def on_chain_end(self, outputs: dict[str, Any], *, run_id: UUID, **kwargs: Any) -> None:
        managed = self._spans.pop(run_id, None)
        if managed is not None:
            captured = apply_capture(
                get_client().config.capture_mode,
                "aap.chain.output",
                outputs,
            )
            for key, value in (captured or {}).items():
                managed.span.set_attribute(key, str(value))
            managed.finish()

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        managed = self._spans.pop(run_id, None)
        if managed is not None:
            managed.finish(error)
