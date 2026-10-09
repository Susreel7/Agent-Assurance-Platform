import type { Span } from "@opentelemetry/api";

import { markSpanOk, recordSpanError } from "./context.js";

export interface StreamMetrics {
  firstTokenMs?: number;
  chunks: number;
  outputTokens: number;
  cancelled: boolean;
}

export interface StreamWrapOptions {
  /** When true, end the span after the stream completes, errors, or is cancelled. */
  endSpan?: boolean;
  onChunk?: (chunk: unknown) => void;
}

export async function* wrapAsyncGenerator<T>(
  span: Span,
  stream: AsyncIterable<T>,
  options: StreamWrapOptions = {},
): AsyncGenerator<T> {
  const started = performance.now();
  const metrics: StreamMetrics = { chunks: 0, outputTokens: 0, cancelled: false };
  const endSpan = options.endSpan ?? false;
  let streamError: unknown;
  try {
    for await (const chunk of stream) {
      if (metrics.firstTokenMs === undefined) {
        metrics.firstTokenMs = performance.now() - started;
      }
      metrics.chunks += 1;
      options.onChunk?.(chunk);
      yield chunk;
    }
  } catch (err) {
    streamError = err;
    if (err instanceof Error && (err.name === "AbortError" || err.name === "CancelledError")) {
      metrics.cancelled = true;
    }
    recordSpanError(span, err);
    throw err;
  } finally {
    applyStreamMetrics(span, metrics);
    if (endSpan) {
      if (streamError === undefined) {
        markSpanOk(span);
      }
      span.end();
    }
  }
}

export function wrapReadableStream<T>(
  span: Span,
  stream: ReadableStream<T>,
  reader: ReadableStreamDefaultReader<T>,
  options: StreamWrapOptions = {},
): ReadableStream<T> {
  const started = performance.now();
  const metrics: StreamMetrics = { chunks: 0, outputTokens: 0, cancelled: false };
  const endSpan = options.endSpan ?? false;
  let ended = false;

  const finish = (err?: unknown) => {
    if (ended) {
      return;
    }
    ended = true;
    applyStreamMetrics(span, metrics);
    if (endSpan) {
      if (err !== undefined) {
        recordSpanError(span, err);
      } else {
        markSpanOk(span);
      }
      span.end();
    }
  };

  return new ReadableStream<T>({
    async pull(controller) {
      try {
        const { value, done } = await reader.read();
        if (done) {
          finish();
          controller.close();
          return;
        }
        if (metrics.firstTokenMs === undefined) {
          metrics.firstTokenMs = performance.now() - started;
        }
        metrics.chunks += 1;
        options.onChunk?.(value);
        controller.enqueue(value);
      } catch (err) {
        metrics.cancelled = true;
        finish(err);
        controller.error(err);
      }
    },
    cancel() {
      metrics.cancelled = true;
      finish();
      return reader.cancel();
    },
  });
}

function applyStreamMetrics(span: Span, metrics: StreamMetrics): void {
  if (metrics.firstTokenMs !== undefined) {
    span.setAttribute("gen_ai.response.time_to_first_token_ms", metrics.firstTokenMs);
  }
  span.setAttribute("gen_ai.response.streaming_chunks", metrics.chunks);
  if (metrics.cancelled) {
    span.addEvent("gen_ai.streaming.cancelled");
  }
}
