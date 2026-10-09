from __future__ import annotations

import importlib
import sys
from importlib.machinery import ModuleSpec
from types import ModuleType, SimpleNamespace
from typing import Any
from uuid import uuid4

from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter


def test_langchain_callback_lifetimes_and_parentage(
    configured_client: Any,
    memory_exporter: InMemorySpanExporter,
    monkeypatch: Any,
) -> None:
    callbacks = ModuleType("langchain_core.callbacks")
    callbacks.__spec__ = ModuleSpec("langchain_core.callbacks", loader=None)
    callbacks.BaseCallbackHandler = type("BaseCallbackHandler", (), {})  # type: ignore[attr-defined]
    core = ModuleType("langchain_core")
    core.__spec__ = ModuleSpec("langchain_core", loader=None)
    core.callbacks = callbacks  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "langchain_core", core)
    monkeypatch.setitem(sys.modules, "langchain_core.callbacks", callbacks)
    sys.modules.pop("aap_trace.integrations.langchain", None)
    module = importlib.import_module("aap_trace.integrations.langchain")
    handler = module.AAPLangChainHandler()

    chain_id = uuid4()
    llm_id = uuid4()
    tool_id = uuid4()
    handler.on_chain_start({"name": "planner"}, {"task": "fix"}, run_id=chain_id)
    handler.on_llm_start(
        {"name": "ChatModel", "kwargs": {"model": "gpt-test"}},
        ["fix dependency"],
        run_id=llm_id,
        parent_run_id=chain_id,
    )
    handler.on_tool_start(
        {"name": "filesystem.write"},
        '{"path":"safe.py"}',
        run_id=tool_id,
        parent_run_id=llm_id,
    )
    assert memory_exporter.get_finished_spans() == ()
    handler.on_tool_end("updated", run_id=tool_id)
    handler.on_llm_end(
        SimpleNamespace(
            generations=[[SimpleNamespace(text="done")]],
            llm_output={"token_usage": {"prompt_tokens": 5, "completion_tokens": 2}},
        ),
        run_id=llm_id,
    )
    handler.on_chain_end({"result": "done"}, run_id=chain_id)
    trace.get_tracer_provider().force_flush()

    spans = {span.name: span for span in memory_exporter.get_finished_spans()}
    assert spans["generation:gpt-test"].parent is not None
    assert spans["generation:gpt-test"].parent.span_id == spans["planner"].context.span_id
    assert spans["tool:filesystem.write"].parent is not None
    assert (
        spans["tool:filesystem.write"].parent.span_id
        == spans["generation:gpt-test"].context.span_id
    )
