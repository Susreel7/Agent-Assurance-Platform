"""Context managers and decorators for GenAI span kinds."""

from __future__ import annotations

import functools
import inspect
import json
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from types import TracebackType
from typing import Any, ParamSpec, TypeVar, cast
from urllib.parse import urlsplit

from opentelemetry import trace
from opentelemetry.trace import Span, StatusCode

from aap_trace.attributes import generation_attrs, retrieval_attrs, tool_attrs
from aap_trace.capture import CaptureMode, apply_capture
from aap_trace.client import get_client
from aap_trace.context import (
    attach_execution,
    current_execution_context,
    detach_execution,
    set_span_error,
)

P = ParamSpec("P")
R = TypeVar("R")


def _capture_mode() -> CaptureMode:
    try:
        return get_client().config.capture_mode
    except RuntimeError:
        return CaptureMode.NONE


def _set_attrs(span: Span, attrs: dict[str, Any]) -> None:
    for key, value in attrs.items():
        if value is not None:
            span.set_attribute(key, _otel_attribute_value(value))


def _otel_attribute_value(value: Any) -> Any:
    if isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)) and all(
        isinstance(item, (str, bool, int, float)) for item in value
    ):
        return value
    return json.dumps(value, default=str, separators=(",", ":"), sort_keys=True)


class _SpanCM(AbstractContextManager[Span]):
    def __init__(self, name: str, attrs: dict[str, Any]) -> None:
        self._name = name
        self._attrs = attrs
        self._token: object | None = None
        self._cm: AbstractContextManager[Span] | None = None
        self._span: Span | None = None

    def __enter__(self) -> Span:
        active_execution = current_execution_context()
        execution_id = self._attrs.get("aap.execution.id")
        if execution_id is None and active_execution is not None:
            execution_id = active_execution.execution_id
            self._attrs["aap.execution.id"] = execution_id
        elif (
            execution_id is not None
            and active_execution is not None
            and str(execution_id) != active_execution.execution_id
        ):
            self._attrs.setdefault("aap.execution.parent_id", active_execution.execution_id)
        if active_execution is not None:
            self._attrs.setdefault("aap.observation.sequence", active_execution.next_sequence())

        tracer = _tracer()
        self._cm = tracer.start_as_current_span(self._name)
        span = self._cm.__enter__()
        _set_attrs(span, self._attrs)
        self._span = span
        if execution_id is not None and (
            active_execution is None or str(execution_id) != active_execution.execution_id
        ):
            self._token = attach_execution(str(execution_id))
        return span

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        if self._span and exc is not None:
            set_span_error(self._span, exc)
        try:
            if self._cm is not None:
                return self._cm.__exit__(exc_type, exc, tb)
            return None
        finally:
            if self._token is not None:
                detach_execution(self._token)  # type: ignore[arg-type]


class ManagedSpan:
    """A span whose lifetime can outlive its creating call, such as a response stream."""

    def __init__(
        self,
        name: str,
        attrs: dict[str, Any],
        *,
        parent_span: Span | None = None,
    ) -> None:
        active_execution = current_execution_context()
        execution_id = attrs.get("aap.execution.id")
        if execution_id is None and active_execution is not None:
            execution_id = active_execution.execution_id
            attrs["aap.execution.id"] = execution_id
        elif (
            execution_id is not None
            and active_execution is not None
            and str(execution_id) != active_execution.execution_id
        ):
            attrs.setdefault("aap.execution.parent_id", active_execution.execution_id)
        if active_execution is not None:
            attrs.setdefault("aap.observation.sequence", active_execution.next_sequence())
        parent_context = trace.set_span_in_context(parent_span) if parent_span is not None else None
        self.span = _tracer().start_span(name, context=parent_context)
        _set_attrs(self.span, attrs)
        self._execution_id = str(execution_id) if execution_id is not None else None
        self._lock = threading.Lock()
        self._ended = False

    @contextmanager
    def activate(self) -> Iterator[Span]:
        token: object | None = None
        active_execution = current_execution_context()
        if self._execution_id is not None and (
            active_execution is None or active_execution.execution_id != self._execution_id
        ):
            token = attach_execution(self._execution_id)
        try:
            with trace.use_span(self.span, end_on_exit=False):
                yield self.span
        finally:
            if token is not None:
                detach_execution(token)  # type: ignore[arg-type]

    def finish(self, error: BaseException | None = None) -> None:
        with self._lock:
            if self._ended:
                return
            self._ended = True
        if error is not None:
            set_span_error(self.span, error)
        else:
            self.span.set_status(StatusCode.OK)
        self.span.end()


def start_managed_span(
    name: str,
    *,
    parent_span: Span | None = None,
    **attrs: Any,
) -> ManagedSpan:
    """Start an explicitly ended span for streaming and callback integrations."""
    return ManagedSpan(name, attrs, parent_span=parent_span)


def _tracer() -> trace.Tracer:
    try:
        return get_client().tracer
    except RuntimeError:
        return trace.get_tracer("aap_trace", "0.1.0")


def span_scope(name: str, **attrs: Any) -> _SpanCM:
    return _SpanCM(name, attrs)


def trace_span(name: str = "trace", **attrs: Any) -> _SpanCM:
    return _SpanCM(name, {"gen_ai.operation.name": "workflow", **attrs})


def run_span(name: str = "run", **attrs: Any) -> _SpanCM:
    return agent_span(name=name, **attrs)


def workflow_span(name: str = "workflow", **attrs: Any) -> _SpanCM:
    return _SpanCM(
        name,
        {
            "gen_ai.operation.name": "workflow",
            "aap.observation.type": "chain",
            **attrs,
        },
    )


def agent_span(
    name: str = "agent",
    *,
    execution_id: str | None = None,
    execution_type: str = "agent",
    trigger_type: str | None = None,
    **attrs: Any,
) -> _SpanCM:
    execution_id = execution_id or str(uuid.uuid4())
    return _SpanCM(
        name,
        {
            "gen_ai.operation.name": "invoke_agent",
            "aap.execution.id": execution_id,
            "aap.execution.type": execution_type,
            "aap.observation.type": "agent",
            "aap.trigger.type": trigger_type,
            **attrs,
        },
    )


def node_span(
    name: str,
    *,
    node_id: str | None = None,
    node_path: str | None = None,
    graph_name: str | None = None,
    graph_version: str | None = None,
    step: int | None = None,
    attempt: int | None = None,
    iteration: int | None = None,
    input_state: Any | None = None,
    **attrs: Any,
) -> _SpanCM:
    captured = apply_capture(_capture_mode(), "aap.node.input_state", input_state) or {}
    return _SpanCM(
        name,
        {
            "gen_ai.operation.name": "workflow",
            "aap.observation.type": "node",
            "aap.graph.name": graph_name,
            "aap.graph.version": graph_version,
            "aap.graph.node.id": node_id or name,
            "aap.graph.node.path": node_path or node_id or name,
            "aap.graph.step": step,
            "aap.retry.attempt": attempt,
            "aap.graph.iteration": iteration,
            **captured,
            **attrs,
        },
    )


def state_transition_span(
    *,
    source: str,
    target: str,
    branch: str | None = None,
    reason: str | None = None,
    state: Any | None = None,
    **attrs: Any,
) -> _SpanCM:
    captured = apply_capture(_capture_mode(), "aap.state.output", state) or {}
    return _SpanCM(
        f"state:{source}->{target}",
        {
            "gen_ai.operation.name": "workflow",
            "aap.observation.type": "state_transition",
            "aap.state.from": source,
            "aap.state.to": target,
            "aap.graph.branch": branch,
            "aap.state.reason": reason,
            **captured,
            **attrs,
        },
    )


def retry_span(
    *,
    target: str,
    attempt: int,
    reason: str | None = None,
    backoff_ms: float | None = None,
    **attrs: Any,
) -> _SpanCM:
    return _SpanCM(
        f"retry:{target}",
        {
            "gen_ai.operation.name": "workflow",
            "aap.observation.type": "retry",
            "aap.retry.target": target,
            "aap.retry.attempt": attempt,
            "aap.retry.reason": reason,
            "aap.retry.backoff_ms": backoff_ms,
            **attrs,
        },
    )


def human_approval_span(
    *,
    approval_id: str,
    action: str,
    **attrs: Any,
) -> _SpanCM:
    return _SpanCM(
        f"approval:{action}",
        {
            "gen_ai.operation.name": "workflow",
            "aap.observation.type": "human_approval",
            "aap.approval.id": approval_id,
            "aap.approval.action": action,
            **attrs,
        },
    )


def record_event(event_type: str, **attrs: Any) -> None:
    span = trace.get_current_span()
    if span is None or not span.is_recording():
        return
    active_execution = current_execution_context()
    event_attrs = {
        "aap.event.type": event_type,
        "aap.observation.type": attrs.pop("observation_type", "event"),
        **attrs,
    }
    if active_execution is not None:
        event_attrs["aap.execution.id"] = active_execution.execution_id
        event_attrs["aap.observation.sequence"] = active_execution.next_sequence()
    _set_attrs_event(span, event_type, event_attrs)


def record_error(error: BaseException, **attrs: Any) -> None:
    span = trace.get_current_span()
    if span is None or not span.is_recording():
        return
    set_span_error(span, error)
    record_event(
        "error",
        observation_type="error",
        **{"error.type": type(error).__name__, "error.message": str(error), **attrs},
    )


def record_retry(
    *,
    target: str,
    attempt: int,
    reason: str | None = None,
    backoff_ms: float | None = None,
) -> None:
    record_event(
        "retry.started",
        observation_type="retry",
        **{
            "aap.retry.target": target,
            "aap.retry.attempt": attempt,
            "aap.retry.reason": reason,
            "aap.retry.backoff_ms": backoff_ms,
        },
    )


def record_state_transition(
    *,
    source: str,
    target: str,
    branch: str | None = None,
    reason: str | None = None,
) -> None:
    record_event(
        "state.transition",
        observation_type="state_transition",
        **{
            "aap.state.from": source,
            "aap.state.to": target,
            "aap.graph.branch": branch,
            "aap.state.reason": reason,
        },
    )


def _set_attrs_event(span: Span, name: str, attrs: dict[str, Any]) -> None:
    span.add_event(
        name,
        {key: _otel_attribute_value(value) for key, value in attrs.items() if value is not None},
    )


def record_checkpoint(
    *,
    checkpoint_id: str,
    thread_id: str | None = None,
    namespace: str | None = None,
    state: Any | None = None,
) -> None:
    captured = apply_capture(_capture_mode(), "aap.checkpoint.state", state) or {}
    record_event(
        "checkpoint.saved",
        observation_type="checkpoint",
        **{
            "aap.checkpoint.id": checkpoint_id,
            "aap.checkpoint.thread_id": thread_id,
            "aap.checkpoint.namespace": namespace,
            **captured,
        },
    )


def record_output_state(span: Span, state: Any) -> None:
    captured = apply_capture(_capture_mode(), "aap.node.output_state", state) or {}
    _set_attrs(span, captured)


def record_approval_decision(
    *,
    approval_id: str,
    decision: str,
    actor_id: str | None = None,
) -> None:
    record_event(
        f"approval.{decision}",
        observation_type="human_approval",
        **{
            "aap.approval.id": approval_id,
            "aap.approval.decision": decision,
            "aap.actor.id": actor_id,
            "aap.actor.type": "user" if actor_id else None,
        },
    )


def handoff_span(*, target: str, **attrs: Any) -> _SpanCM:
    return _SpanCM(
        f"handoff:{target}",
        {
            "gen_ai.operation.name": "handoff",
            "aap.observation.type": "a2a",
            "gen_ai.handoff.target": target,
            **attrs,
        },
    )


def a2a_span(
    *,
    target_agent_id: str,
    target_execution_id: str | None = None,
    target_trace_id: str | None = None,
    protocol: str = "a2a",
    **attrs: Any,
) -> _SpanCM:
    return _SpanCM(
        f"a2a:{target_agent_id}",
        {
            "gen_ai.operation.name": "handoff",
            "aap.observation.type": "a2a",
            "aap.a2a.target_agent_id": target_agent_id,
            "aap.a2a.target_execution_id": target_execution_id,
            "aap.a2a.target_trace_id": target_trace_id,
            "aap.a2a.protocol": protocol,
            **attrs,
        },
    )


def mcp_span(
    *,
    server: str,
    method: str,
    role: str = "client",
    request_id: str | None = None,
    arguments: Any | None = None,
    **attrs: Any,
) -> _SpanCM:
    captured = apply_capture(_capture_mode(), "aap.mcp.arguments", arguments) or {}
    return _SpanCM(
        f"mcp:{server}:{method}",
        {
            "aap.observation.type": "mcp",
            "aap.mcp.server": server,
            "aap.mcp.method": method,
            "aap.mcp.role": role,
            "aap.mcp.request_id": request_id,
            **captured,
            **attrs,
        },
    )


def generation_span(
    *,
    provider: str,
    model: str,
    operation: str = "chat",
    system_instructions: Any | None = None,
    input_messages: Any | None = None,
    **extra: Any,
) -> _SpanCM:
    attrs = generation_attrs(
        provider=provider,
        model=model,
        operation=operation,
        capture_mode=_capture_mode(),
        system_instructions=system_instructions,
        input_messages=input_messages,
    )
    attrs.update(extra)
    attrs["aap.observation.type"] = "generation"
    return _SpanCM(f"generation:{model}", attrs)


def tool_span(
    *,
    name: str,
    tool_type: str = "function",
    arguments: Any | None = None,
    **extra: Any,
) -> _SpanCM:
    attrs = tool_attrs(
        name=name,
        tool_type=tool_type,
        arguments=arguments,
        capture_mode=_capture_mode(),
    )
    attrs.update(extra)
    attrs["aap.observation.type"] = "tool"
    return _SpanCM(f"tool:{name}", attrs)


def retrieval_span(*, query: str | None = None, **extra: Any) -> _SpanCM:
    attrs = retrieval_attrs(query=query, capture_mode=_capture_mode())
    attrs.update(extra)
    attrs["aap.observation.type"] = "retrieval"
    return _SpanCM("retrieval", attrs)


def sdk_span(
    *,
    sdk_name: str,
    operation: str,
    sdk_version: str | None = None,
    arguments: Any | None = None,
    request_id: str | None = None,
    **extra: Any,
) -> _SpanCM:
    captured = apply_capture(_capture_mode(), "aap.sdk.arguments", arguments) or {}
    return _SpanCM(
        f"sdk:{sdk_name}.{operation}",
        {
            "gen_ai.operation.name": "execute_sdk",
            "aap.observation.type": "sdk",
            "aap.sdk.name": sdk_name,
            "aap.sdk.version": sdk_version,
            "aap.sdk.operation": operation,
            "aap.request.id": request_id,
            **captured,
            **extra,
        },
    )


def cursor_sdk_span(
    operation: str,
    *,
    arguments: Any | None = None,
    sdk_version: str | None = None,
    **extra: Any,
) -> _SpanCM:
    return sdk_span(
        sdk_name="cursor",
        sdk_version=sdk_version,
        operation=operation,
        arguments=arguments,
        **extra,
    )


def record_sdk_result(
    span: Span,
    result: Any,
    *,
    response_id: str | None = None,
) -> None:
    _set_attrs(span, apply_capture(_capture_mode(), "aap.sdk.result", result) or {})
    if response_id is not None:
        span.set_attribute("aap.response.id", response_id)


def record_tool_result(span: Span, result: Any) -> None:
    attrs = tool_attrs(name="", result=result, capture_mode=_capture_mode())
    _set_attrs(
        span,
        {key: value for key, value in attrs.items() if key.startswith("gen_ai.tool.call.result")},
    )


def http_span(
    *,
    method: str,
    url: str | None = None,
    route: str | None = None,
    server: str | None = None,
    **extra: Any,
) -> _SpanCM:
    """Create HTTP telemetry without recording query strings, credentials, or headers."""
    scheme: str | None = None
    port: int | None = None
    if url:
        parsed = urlsplit(url)
        scheme = parsed.scheme or None
        server = server or parsed.hostname
        port = parsed.port
    return _SpanCM(
        f"http:{method.upper()} {route or server or 'request'}",
        {
            "gen_ai.operation.name": "http",
            "aap.observation.type": "http",
            "http.request.method": method.upper(),
            "http.route": route,
            "url.scheme": scheme,
            "server.address": server,
            "server.port": port,
            **extra,
        },
    )


def database_span(
    *,
    system: str,
    operation: str,
    namespace: str | None = None,
    statement: Any | None = None,
    **extra: Any,
) -> _SpanCM:
    captured = apply_capture(_capture_mode(), "db.query.text", statement) or {}
    return _SpanCM(
        f"db:{system}.{operation}",
        {
            "gen_ai.operation.name": "database",
            "aap.observation.type": "database",
            "db.system.name": system,
            "db.operation.name": operation,
            "db.namespace": namespace,
            **captured,
            **extra,
        },
    )


def observation_span(
    observation_type: str,
    name: str,
    *,
    input_value: Any | None = None,
    **attrs: Any,
) -> _SpanCM:
    captured = apply_capture(_capture_mode(), "aap.observation.input", input_value) or {}
    return _SpanCM(
        name,
        {
            "gen_ai.operation.name": observation_type,
            "aap.observation.type": observation_type,
            **captured,
            **attrs,
        },
    )


def traced(name: str | None = None, **attrs: Any) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        span_name = name or fn.__name__

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                with workflow_span(span_name, **attrs):
                    result = await fn(*args, **kwargs)
                    return cast(R, result)

            return cast(Callable[P, R], async_wrapper)

        @functools.wraps(fn)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with workflow_span(span_name, **attrs):
                return fn(*args, **kwargs)

        return cast(Callable[P, R], sync_wrapper)

    return decorator


def _typed_decorator(
    factory: Callable[[], AbstractContextManager[Span]],
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                with factory():
                    return cast(R, await fn(*args, **kwargs))

            return cast(Callable[P, R], async_wrapper)

        @functools.wraps(fn)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with factory():
                return fn(*args, **kwargs)

        return cast(Callable[P, R], sync_wrapper)

    return decorator


def observe_agent(name: str, **attrs: Any) -> Callable[[Callable[P, R]], Callable[P, R]]:
    return _typed_decorator(lambda: agent_span(name, **attrs))


def observe_node(name: str, **attrs: Any) -> Callable[[Callable[P, R]], Callable[P, R]]:
    return _typed_decorator(lambda: node_span(name, **attrs))


def observe_tool(
    name: str,
    *,
    tool_type: str = "function",
    **attrs: Any,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    return _typed_decorator(lambda: tool_span(name=name, tool_type=tool_type, **attrs))


def observe_generation(
    *,
    provider: str,
    model: str,
    **attrs: Any,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    return _typed_decorator(lambda: generation_span(provider=provider, model=model, **attrs))


def observe(
    observation_type: str,
    name: str | None = None,
    **attrs: Any,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    def decorate(fn: Callable[P, R]) -> Callable[P, R]:
        return _typed_decorator(
            lambda: observation_span(observation_type, name or fn.__name__, **attrs)
        )(fn)

    return decorate


def end_span(span: ManagedSpan | Span, error: BaseException | None = None) -> None:
    if isinstance(span, ManagedSpan):
        span.finish(error)
        return
    if error is not None:
        set_span_error(span, error)
    span.end()


@contextmanager
def record_output(span: Span, output_messages: Any) -> Iterator[None]:
    """Attach captured output messages when the generation completes."""
    try:
        yield
    finally:
        mode = _capture_mode()
        captured = generation_attrs(
            provider="",
            model="",
            capture_mode=mode,
            output_messages=output_messages,
        )
        _set_attrs(span, {k: v for k, v in captured.items() if k.startswith("gen_ai.output")})
        span.set_status(StatusCode.OK)
