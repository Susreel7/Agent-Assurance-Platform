import { context, propagation, trace, type Context, SpanStatusCode } from "@opentelemetry/api";

export interface SpanIdentity {
  traceId: string;
  spanId: string;
}

export function currentSpanIdentity(): SpanIdentity | null {
  const span = trace.getActiveSpan();
  if (!span) return null;
  const ctx = span.spanContext();
  if (!ctx.traceId) return null;
  return { traceId: ctx.traceId, spanId: ctx.spanId };
}

export function injectHeaders(carrier: Record<string, string>): void {
  propagation.inject(context.active(), carrier);
}

export function extractHeaders(carrier: Record<string, string>): Context {
  return propagation.extract(context.active(), carrier);
}

export function injectMcpContext(
  message: Record<string, unknown>,
  metadataKey = "_meta",
): void {
  const carrier: Record<string, string> = {};
  injectHeaders(carrier);
  const existing = message[metadataKey];
  const metadata =
    existing && typeof existing === "object" && !Array.isArray(existing)
      ? (existing as Record<string, unknown>)
      : {};
  for (const key of ["traceparent", "tracestate", "baggage"]) {
    if (carrier[key]) metadata[key] = carrier[key];
  }
  message[metadataKey] = metadata;
}

export function extractMcpContext(
  message: Record<string, unknown>,
  metadataKey = "_meta",
): Context {
  const raw = message[metadataKey];
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return extractHeaders({});
  const carrier: Record<string, string> = {};
  for (const [key, value] of Object.entries(raw)) {
    if (
      ["traceparent", "tracestate", "baggage"].includes(key) &&
      typeof value === "string"
    ) {
      carrier[key] = value;
    }
  }
  return extractHeaders(carrier);
}

export function recordSpanError(span: ReturnType<typeof trace.getActiveSpan>, err: unknown): void {
  if (!span) return;
  span.recordException(err instanceof Error ? err : new Error(String(err)));
  span.setStatus({ code: SpanStatusCode.ERROR, message: String(err) });
}

export function markSpanOk(span: NonNullable<ReturnType<typeof trace.getActiveSpan>>): void {
  span.setStatus({ code: SpanStatusCode.OK });
}
