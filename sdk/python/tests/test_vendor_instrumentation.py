from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from aap_trace.integrations.anthropic import instrument_anthropic_client
from aap_trace.integrations.openai import instrument_openai_client


def _openai_client(create: Any) -> Any:
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
    )


def _anthropic_client(create: Any) -> Any:
    return SimpleNamespace(messages=SimpleNamespace(create=create))


def test_openai_stream_span_ends_after_consumption(
    configured_client: Any,
    memory_exporter: InMemorySpanExporter,
) -> None:
    def create(**kwargs: Any) -> Any:
        def chunks() -> Any:
            yield SimpleNamespace(
                id="resp-1",
                model="gpt-test",
                usage=None,
                choices=[
                    SimpleNamespace(
                        finish_reason=None,
                        delta=SimpleNamespace(content="hello ", tool_calls=[]),
                    )
                ],
            )
            yield SimpleNamespace(
                id="resp-1",
                model="gpt-test",
                usage=SimpleNamespace(
                    prompt_tokens=4,
                    completion_tokens=2,
                    prompt_tokens_details=SimpleNamespace(cached_tokens=1),
                    completion_tokens_details=SimpleNamespace(reasoning_tokens=0),
                ),
                choices=[
                    SimpleNamespace(
                        finish_reason="stop",
                        delta=SimpleNamespace(content="world", tool_calls=[]),
                    )
                ],
            )

        return chunks()

    client = instrument_openai_client(_openai_client(create))
    stream = client.chat.completions.create(
        model="gpt-test",
        messages=[{"role": "user", "content": "credential must not be retained"}],
        temperature=0.2,
        stream=True,
    )
    assert memory_exporter.get_finished_spans() == ()
    assert len(list(stream)) == 2
    trace.get_tracer_provider().force_flush()
    span = memory_exporter.get_finished_spans()[0]
    assert span.attributes["aap.observation.type"] == "generation"
    assert span.attributes["gen_ai.response.id"] == "resp-1"
    assert span.attributes["gen_ai.response.streaming_chunks"] == 2
    assert span.attributes["gen_ai.usage.input_tokens"] == 4
    assert "credential" not in str(span.attributes)


def test_openai_stream_error_finishes_span(
    configured_client: Any,
    memory_exporter: InMemorySpanExporter,
) -> None:
    def create(**kwargs: Any) -> Any:
        def chunks() -> Any:
            yield "first"
            raise OSError("connection lost")

        return chunks()

    client = instrument_openai_client(_openai_client(create))
    with pytest.raises(OSError, match="connection lost"):
        list(client.chat.completions.create(model="gpt-test", stream=True))
    trace.get_tracer_provider().force_flush()
    span = memory_exporter.get_finished_spans()[0]
    assert span.status.status_code == StatusCode.ERROR


@pytest.mark.asyncio
async def test_anthropic_async_stream_span_ends_after_consumption(
    configured_client: Any,
    memory_exporter: InMemorySpanExporter,
) -> None:
    async def create(**kwargs: Any) -> Any:
        async def events() -> Any:
            yield SimpleNamespace(
                message=SimpleNamespace(
                    id="msg-1",
                    model="claude-test",
                    content=[],
                    stop_reason=None,
                    usage=SimpleNamespace(input_tokens=5, output_tokens=0),
                ),
                delta=None,
            )
            yield SimpleNamespace(
                message=None,
                delta=SimpleNamespace(text="done", stop_reason="end_turn", usage=None),
            )

        return events()

    client = instrument_anthropic_client(_anthropic_client(create))
    stream = await client.messages.create(
        model="claude-test",
        messages=[{"role": "user", "content": "hello"}],
        stream=True,
    )
    assert memory_exporter.get_finished_spans() == ()
    assert len([event async for event in stream]) == 2
    trace.get_tracer_provider().force_flush()
    span = memory_exporter.get_finished_spans()[0]
    assert span.attributes["gen_ai.response.id"] == "msg-1"
    assert span.attributes["gen_ai.response.streaming_chunks"] == 2
    assert "reasoning" not in str(span.attributes).lower()
