"""Anthropic messages API wrapper."""

from __future__ import annotations

import asyncio
from typing import Any, cast

from aap_trace.attributes import generation_attrs
from aap_trace.capture import CaptureMode, apply_capture
from aap_trace.client import get_client
from aap_trace.integrations._generation import (
    AnthropicStreamAccumulator,
    apply_anthropic_response,
    request_attributes,
)
from aap_trace.spans import ManagedSpan, start_managed_span
from aap_trace.streaming import wrap_async_stream, wrap_sync_stream


def _capture_mode() -> CaptureMode:
    return get_client().config.capture_mode


def _start_generation(kwargs: dict[str, Any]) -> ManagedSpan:
    model = str(kwargs.get("model", "unknown"))
    mode = _capture_mode()
    attrs = generation_attrs(
        provider="anthropic",
        model=model,
        capture_mode=mode,
        system_instructions=kwargs.get("system"),
        input_messages=kwargs.get("messages"),
    )
    attrs.update(request_attributes(kwargs))
    attrs.update(apply_capture(mode, "gen_ai.request.tools", kwargs.get("tools")) or {})
    attrs["aap.observation.type"] = "generation"
    return start_managed_span(f"generation:{model}", **attrs)


def _sync_stream(handle: ManagedSpan, result: Any) -> Any:
    accumulator = AnthropicStreamAccumulator()

    def gen() -> Any:
        error: BaseException | None = None
        try:
            with handle.activate():
                for event in wrap_sync_stream(handle.span, iter(result)):
                    accumulator.consume(handle.span, event)
                    yield event
        except GeneratorExit:
            raise
        except BaseException as exc:
            error = exc
            raise
        finally:
            accumulator.finish(handle.span, _capture_mode())
            handle.finish(error)

    return gen()


def _async_stream(handle: ManagedSpan, result: Any) -> Any:
    accumulator = AnthropicStreamAccumulator()

    async def gen() -> Any:
        error: BaseException | None = None
        try:
            with handle.activate():
                async for event in wrap_async_stream(handle.span, result.__aiter__()):
                    accumulator.consume(handle.span, event)
                    yield event
        except (GeneratorExit, asyncio.CancelledError):
            raise
        except BaseException as exc:
            error = exc
            raise
        finally:
            accumulator.finish(handle.span, _capture_mode())
            handle.finish(error)

    return gen()


def instrument_anthropic_client(client: Any) -> Any:
    messages = client.messages
    if getattr(messages, "_aap_traced", False):
        return client
    original_create = messages.create

    async def async_create(*args: Any, **kwargs: Any) -> Any:
        handle = _start_generation(kwargs)
        stream = kwargs.get("stream", False)
        try:
            with handle.activate():
                result = await original_create(*args, **kwargs)
        except BaseException as exc:
            handle.finish(exc)
            raise
        if stream and hasattr(result, "__aiter__"):
            return _async_stream(handle, result)
        if stream and hasattr(result, "__iter__"):
            return _sync_stream(handle, result)
        try:
            apply_anthropic_response(handle.span, result, _capture_mode())
            return result
        finally:
            handle.finish()

    def sync_create(*args: Any, **kwargs: Any) -> Any:
        handle = _start_generation(kwargs)
        stream = kwargs.get("stream", False)
        try:
            with handle.activate():
                result = original_create(*args, **kwargs)
        except BaseException as exc:
            handle.finish(exc)
            raise
        if stream and hasattr(result, "__iter__"):
            return _sync_stream(handle, result)
        try:
            apply_anthropic_response(handle.span, result, _capture_mode())
            return result
        finally:
            handle.finish()

    import inspect

    if inspect.iscoroutinefunction(original_create):
        messages.create = cast(Any, async_create)
    else:
        messages.create = cast(Any, sync_create)
    messages._aap_traced = True
    return client
