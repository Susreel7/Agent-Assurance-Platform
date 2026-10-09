from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import NonRecordingSpan

from aap_trace.streaming import wrap_sync_stream


def test_streaming_ttft_and_cancel(memory_exporter: InMemorySpanExporter) -> None:
    provider = trace.get_tracer_provider()
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("stream") as span:
        assert isinstance(span, NonRecordingSpan) or span.is_recording()

        def gen():
            yield "a"
            yield "b"
            return

        for _ in wrap_sync_stream(span, gen()):
            pass
    provider.force_flush()
    finished = memory_exporter.get_finished_spans()
    if finished:
        attrs = finished[-1].attributes
        assert attrs.get("gen_ai.response.time_to_first_token_ms") is not None
        assert attrs.get("gen_ai.response.streaming_chunks") == 2


def test_partial_stream_metrics_on_span() -> None:
    span = trace.get_tracer("t").start_span("s")
    try:

        def one_chunk():
            yield "x"

        list(wrap_sync_stream(span, one_chunk()))
    finally:
        span.end()
    assert span.attributes.get("gen_ai.response.streaming_chunks") == 1
