"""First-class LangGraph execution, node, transition, checkpoint and interrupt tracing."""

from __future__ import annotations

import functools
import inspect
from collections.abc import AsyncIterator, Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import Span, Status, StatusCode

from aap_trace.capture import apply_capture
from aap_trace.client import get_client
from aap_trace.context import current_execution_context, set_span_error
from aap_trace.integrations._optional import require_package
from aap_trace.spans import (
    _capture_mode,
    _otel_attribute_value,
    agent_span,
    node_span,
    record_checkpoint,
    record_event,
    record_output_state,
    tool_span,
)

require_package("langgraph", "langgraph")


def _node_metadata(metadata: Mapping[str, Any] | None) -> tuple[str | None, int | None, str]:
    metadata = metadata or {}
    node = metadata.get("langgraph_node")
    raw_step = metadata.get("langgraph_step")
    step = int(raw_step) if isinstance(raw_step, int | str) and str(raw_step).isdigit() else None
    path = str(
        metadata.get("langgraph_path")
        or metadata.get("checkpoint_ns")
        or metadata.get("langgraph_checkpoint_ns")
        or node
        or ""
    )
    return str(node) if node else None, step, path


def _thread_id(metadata: Mapping[str, Any] | None) -> str | None:
    if not metadata:
        return None
    configurable = metadata.get("configurable")
    if isinstance(configurable, Mapping) and configurable.get("thread_id") is not None:
        return str(configurable["thread_id"])
    if metadata.get("thread_id") is not None:
        return str(metadata["thread_id"])
    return None


def _has_interrupt(value: Any) -> bool:
    if isinstance(value, Mapping):
        if "__interrupt__" in value:
            return True
        return any(_has_interrupt(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return any(_has_interrupt(item) for item in value)
    return type(value).__name__ == "Interrupt"


def _is_resume(value: Any) -> bool:
    return type(value).__name__ == "Command" and getattr(value, "resume", None) is not None


def wrap_langgraph_node[**P, R](
    node_name: str,
    fn: Callable[P, R],
    *,
    graph_name: str | None = None,
    graph_version: str | None = None,
    node_path: str | None = None,
) -> Callable[P, R]:
    """Wrap sync or async LangGraph node callables while preserving active context."""

    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            state = args[0] if args else kwargs.get("state")
            with node_span(
                node_name,
                node_id=node_name,
                node_path=node_path or node_name,
                graph_name=graph_name,
                graph_version=graph_version,
                input_state=state,
            ) as span:
                result = await fn(*args, **kwargs)
                record_output_state(span, result)
                return cast(R, result)

        return cast(Callable[P, R], async_wrapper)

    @functools.wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        state = args[0] if args else kwargs.get("state")
        with node_span(
            node_name,
            node_id=node_name,
            node_path=node_path or node_name,
            graph_name=graph_name,
            graph_version=graph_version,
            input_state=state,
        ) as span:
            result = fn(*args, **kwargs)
            record_output_state(span, result)
            return result

    return wrapper


def wrap_langgraph_tool(tool_name: str, fn: Callable[..., Any]) -> Callable[..., Any]:
    if inspect.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            with tool_span(name=tool_name, arguments={"args": args, "kwargs": kwargs}):
                return await fn(*args, **kwargs)

        return async_wrapper

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        with tool_span(name=tool_name, arguments={"args": args, "kwargs": kwargs}):
            return fn(*args, **kwargs)

    return wrapper


def on_checkpoint(event: dict[str, Any]) -> None:
    """Compatibility hook for applications that manage their own checkpointer."""
    record_checkpoint(
        checkpoint_id=str(event.get("checkpoint_id", "")),
        thread_id=str(event["thread_id"]) if event.get("thread_id") is not None else None,
        namespace=str(event["namespace"]) if event.get("namespace") is not None else None,
        state=event.get("state"),
    )


@dataclass(slots=True)
class _ActiveNode:
    span: Span
    token: object
    metadata: Mapping[str, Any]


class LangGraphCallbackHandler:
    """Duck-typed LangChain callback handler focused only on LangGraph node runs."""

    raise_error = False
    run_inline = True
    ignore_chain = False
    ignore_agent = False
    ignore_llm = True
    ignore_chat_model = True
    ignore_retriever = True
    ignore_tool = True
    ignore_custom_event = False
    ignore_retry = False

    def __init__(self, *, graph_name: str, graph_version: str | None = None) -> None:
        self.graph_name = graph_name
        self.graph_version = graph_version
        self._active: dict[UUID, _ActiveNode] = {}
        self._ignored: set[UUID] = set()
        self._iterations: dict[str, int] = {}

    def on_chain_start(
        self,
        serialized: dict[str, Any],
        inputs: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        name: str | None = None,
        **kwargs: Any,
    ) -> Any:
        del serialized, tags, kwargs
        if parent_run_id in self._active or parent_run_id in self._ignored:
            self._ignored.add(run_id)
            return None
        node, step, path = _node_metadata(metadata)
        if node is None:
            return None
        iteration = self._iterations.get(node, 0) + 1
        self._iterations[node] = iteration
        attrs = {
            "gen_ai.operation.name": "workflow",
            "aap.observation.type": "node",
            "aap.graph.name": self.graph_name,
            "aap.graph.version": self.graph_version,
            "aap.graph.node.id": node,
            "aap.graph.node.path": path,
            "aap.graph.step": step,
            "aap.graph.iteration": iteration,
            "aap.langgraph.run_id": str(run_id),
        }
        execution = current_execution_context()
        if execution is not None:
            attrs["aap.execution.id"] = execution.execution_id
            attrs["aap.observation.sequence"] = execution.next_sequence()
        captured = apply_capture(_capture_mode(), "aap.node.input_state", inputs)
        if captured:
            attrs.update(captured)
        span = get_client().tracer.start_span(
            name or node,
            attributes={
                key: _otel_attribute_value(value)
                for key, value in attrs.items()
                if value is not None
            },
        )
        token = otel_context.attach(trace.set_span_in_context(span))
        self._active[run_id] = _ActiveNode(
            span=span,
            token=token,
            metadata=metadata or {},
        )
        if iteration > 1:
            record_event(
                "node.retry",
                observation_type="retry",
                **{
                    "aap.retry.target": node,
                    "aap.retry.attempt": iteration,
                },
            )
        triggers = (metadata or {}).get("langgraph_triggers")
        if triggers:
            record_event(
                "state.transition",
                observation_type="state_transition",
                **{
                    "aap.graph.branch": _otel_attribute_value(triggers),
                    "aap.state.to": node,
                },
            )
        if _is_resume(inputs):
            record_event("execution.resumed", observation_type="event")
        return None

    def on_chain_end(
        self,
        outputs: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> Any:
        del parent_run_id, kwargs
        if run_id in self._ignored:
            self._ignored.discard(run_id)
            return None
        active = self._active.pop(run_id, None)
        if active is None:
            return None
        try:
            record_output_state(active.span, outputs)
            if _has_interrupt(outputs):
                active.span.set_attribute("aap.node.status", "waiting")
                active.span.add_event(
                    "approval.requested",
                    {
                        "aap.event.type": "approval.requested",
                        "aap.observation.type": "human_approval",
                    },
                )
            namespace = active.metadata.get("checkpoint_ns") or active.metadata.get(
                "langgraph_checkpoint_ns"
            )
            thread_id = _thread_id(active.metadata)
            if namespace or thread_id:
                record_checkpoint(
                    checkpoint_id=f"{run_id}:{active.metadata.get('langgraph_step', '')}",
                    thread_id=thread_id,
                    namespace=str(namespace or ""),
                )
            active.span.set_status(Status(StatusCode.OK))
        finally:
            active.span.end()
            self._detach(active.token)
        return None

    def on_chain_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> Any:
        del parent_run_id, kwargs
        if run_id in self._ignored:
            self._ignored.discard(run_id)
            return None
        active = self._active.pop(run_id, None)
        if active is None:
            return None
        try:
            set_span_error(active.span, error)
        finally:
            active.span.end()
            self._detach(active.token)
        return None

    @staticmethod
    def _detach(token: object) -> None:
        try:
            otel_context.detach(token)  # type: ignore[arg-type]
        except (RuntimeError, ValueError):
            pass


def _config_with_handler(
    config: Mapping[str, Any] | None,
    handler: LangGraphCallbackHandler,
) -> dict[str, Any]:
    result = dict(config or {})
    callbacks = result.get("callbacks")
    if callbacks is None:
        result["callbacks"] = [handler]
    elif isinstance(callbacks, list):
        result["callbacks"] = [*callbacks, handler]
    else:
        result["callbacks"] = [callbacks, handler]
    return result


class InstrumentedLangGraph:
    """Transparent proxy that instruments invoke, async invoke and both stream forms."""

    def __init__(
        self,
        graph: Any,
        *,
        graph_name: str,
        graph_version: str | None = None,
        agent_name: str | None = None,
    ) -> None:
        self._graph = graph
        self.graph_name = graph_name
        self.graph_version = graph_version
        self.agent_name = agent_name or graph_name
        self.graph_definition = describe_langgraph(graph)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._graph, name)

    def _config(self, config: Mapping[str, Any] | None) -> dict[str, Any]:
        return _config_with_handler(
            config,
            LangGraphCallbackHandler(
                graph_name=self.graph_name,
                graph_version=self.graph_version,
            ),
        )

    def _agent_scope(self) -> Any:
        attrs: dict[str, Any] = {
            "aap.graph.name": self.graph_name,
            "aap.graph.version": self.graph_version,
            "aap.framework.name": "langgraph",
            "aap.graph.node_count": len(self.graph_definition["nodes"]),
            "aap.graph.edge_count": len(self.graph_definition["edges"]),
        }
        captured = apply_capture(
            _capture_mode(),
            "aap.graph.definition",
            self.graph_definition,
        )
        if captured:
            attrs.update(captured)
        return agent_span(self.agent_name, **attrs)

    def invoke(
        self,
        input: Any,
        config: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        with self._agent_scope():
            if _is_resume(input):
                record_event("execution.resumed")
            result = self._graph.invoke(input, self._config(config), **kwargs)
            if _has_interrupt(result):
                record_event("execution.interrupted", observation_type="human_approval")
            return result

    async def ainvoke(
        self,
        input: Any,
        config: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        with self._agent_scope():
            if _is_resume(input):
                record_event("execution.resumed")
            result = await self._graph.ainvoke(input, self._config(config), **kwargs)
            if _has_interrupt(result):
                record_event("execution.interrupted", observation_type="human_approval")
            return result

    def stream(
        self,
        input: Any,
        config: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> Iterator[Any]:
        with self._agent_scope():
            yield from self._graph.stream(input, self._config(config), **kwargs)

    async def astream(
        self,
        input: Any,
        config: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[Any]:
        with self._agent_scope():
            async for item in self._graph.astream(input, self._config(config), **kwargs):
                yield item


def instrument_langgraph(
    graph: Any,
    *,
    graph_name: str,
    graph_version: str | None = None,
    agent_name: str | None = None,
) -> InstrumentedLangGraph:
    return InstrumentedLangGraph(
        graph,
        graph_name=graph_name,
        graph_version=graph_version,
        agent_name=agent_name,
    )


def describe_langgraph(graph: Any) -> dict[str, Any]:
    """Return a bounded static graph contract for architecture visualization."""
    drawable = graph.get_graph()
    raw_nodes = getattr(drawable, "nodes", {})
    node_values = raw_nodes.values() if isinstance(raw_nodes, Mapping) else raw_nodes
    nodes = [
        {
            "id": str(getattr(node, "id", getattr(node, "name", node))),
            "name": str(getattr(node, "name", getattr(node, "id", node))),
        }
        for node in node_values
    ]
    edges = [
        {
            "source": str(getattr(edge, "source", "")),
            "target": str(getattr(edge, "target", "")),
            "conditional": bool(getattr(edge, "conditional", False)),
            "label": str(getattr(edge, "data", "") or ""),
        }
        for edge in getattr(drawable, "edges", [])
    ]
    return {"nodes": nodes[:5000], "edges": edges[:10000]}
