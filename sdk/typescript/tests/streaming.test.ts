import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { SpanStatusCode, trace } from "@opentelemetry/api";
import { InMemorySpanExporter } from "@opentelemetry/sdk-trace-base";

import { wrapAsyncGenerator } from "../src/streaming.js";
import { installTestTracerProvider } from "./testHarness.js";

describe("streaming", () => {
  let exporter: InMemorySpanExporter;

  beforeEach(() => {
    exporter = new InMemorySpanExporter();
    installTestTracerProvider(exporter);
  });

  afterEach(() => {
    exporter.reset();
  });

  it("records TTFT and chunks", async () => {
    const tracer = trace.getTracer("test");
    const span = tracer.startSpan("stream");
    async function* gen() {
      yield "a";
      yield "b";
    }
    for await (const chunk of wrapAsyncGenerator(span, gen())) {
      void chunk;
    }
    span.end();
    const finished = exporter.getFinishedSpans()[0]!;
    expect(finished.attributes["gen_ai.response.streaming_chunks"]).toBe(2);
    expect(finished.attributes["gen_ai.response.time_to_first_token_ms"]).toBeDefined();
  });

  it("records cancellation on AbortError", async () => {
    const tracer = trace.getTracer("test");
    const span = tracer.startSpan("stream");
    async function* gen() {
      yield "a";
      const err = new Error("aborted");
      err.name = "AbortError";
      throw err;
    }
    await expect(async () => {
      for await (const chunk of wrapAsyncGenerator(span, gen())) {
        void chunk;
      }
    }).rejects.toThrow("aborted");
    span.end();
    const finished = exporter.getFinishedSpans()[0]!;
    expect(finished.events.some((e) => e.name === "gen_ai.streaming.cancelled")).toBe(true);
  });

  it("endSpan option ends the span when the stream completes", async () => {
    const tracer = trace.getTracer("test");
    const span = tracer.startSpan("stream");
    async function* gen() {
      yield 1;
    }
    for await (const chunk of wrapAsyncGenerator(span, gen(), { endSpan: true })) {
      void chunk;
    }
    const finished = exporter.getFinishedSpans()[0]!;
    expect(finished.status.code).toBe(SpanStatusCode.OK);
    expect(finished.attributes["gen_ai.response.streaming_chunks"]).toBe(1);
  });

  it("endSpan records error status when the stream throws", async () => {
    const tracer = trace.getTracer("test");
    const span = tracer.startSpan("stream");
    async function* gen() {
      yield 1;
      throw new Error("stream failed");
    }
    await expect(async () => {
      for await (const chunk of wrapAsyncGenerator(span, gen(), { endSpan: true })) {
        void chunk;
      }
    }).rejects.toThrow("stream failed");
    const finished = exporter.getFinishedSpans()[0]!;
    expect(finished.status.code).toBe(SpanStatusCode.ERROR);
    expect(finished.attributes["gen_ai.response.streaming_chunks"]).toBe(1);
  });
});
