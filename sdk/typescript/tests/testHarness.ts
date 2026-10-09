import { context, propagation, trace } from "@opentelemetry/api";
import { W3CTraceContextPropagator } from "@opentelemetry/core";
import { AsyncLocalStorageContextManager } from "@opentelemetry/context-async-hooks";
import {
  BasicTracerProvider,
  InMemorySpanExporter,
  SimpleSpanProcessor,
} from "@opentelemetry/sdk-trace-base";

/** Install an in-memory tracer provider for unit tests (stable across test cases). */
export function installTestTracerProvider(
  exporter: InMemorySpanExporter,
): BasicTracerProvider {
  const ctxManager = new AsyncLocalStorageContextManager();
  ctxManager.enable();
  context.setGlobalContextManager(ctxManager);
  propagation.setGlobalPropagator(new W3CTraceContextPropagator());
  const provider = new BasicTracerProvider();
  provider.addSpanProcessor(new SimpleSpanProcessor(exporter));
  // registerGlobal only succeeds once per process; always refresh the proxy delegate.
  trace.setGlobalTracerProvider(provider);
  const globalProvider = trace.getTracerProvider();
  if (
    typeof (globalProvider as { setDelegate?: (p: BasicTracerProvider) => void }).setDelegate ===
    "function"
  ) {
    (globalProvider as { setDelegate: (p: BasicTracerProvider) => void }).setDelegate(provider);
  }
  return provider;
}
