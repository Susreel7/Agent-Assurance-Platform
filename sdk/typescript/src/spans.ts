import {

  context,

  createContextKey,

  type Context,

  type Span,

  SpanStatusCode,

  trace,

} from "@opentelemetry/api";

import { randomUUID } from "node:crypto";



import {

  databaseAttributes,

  generationAttributes,

  retrievalAttributes,

  sdkAttributes,

  toolAttributes,

} from "./attributes.js";

import { applyCapture, type CaptureMode } from "./capture.js";

import { getClient } from "./client.js";

import { recordSpanError } from "./context.js";

import {

  generationRequestAttributes,

  generationResponseAttributes,

  type GenerationResponseDetails,

} from "./generation.js";

import { safeHttpAttributes } from "./safeHttp.js";



function captureMode(): CaptureMode {

  try {

    return getClient().config.captureMode ?? "none";

  } catch {

    return "none";

  }

}



function tracer() {

  try {

    return getClient().tracer;

  } catch {

    return trace.getTracer("aap_trace", "0.1.0");

  }

}



interface ExecutionState {

  id: string;

  sequence: number;

}



const EXECUTION_CONTEXT = createContextKey("aap.execution");



function attributeValue(value: unknown): string | number | boolean {

  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {

    return value;

  }

  return JSON.stringify(value);

}



function setAttrs(span: Span, attrs: Record<string, unknown>) {

  for (const [k, v] of Object.entries(attrs)) {

    if (v !== undefined && v !== null) {

      span.setAttribute(k, attributeValue(v));

    }

  }

}



function mergeExecutionAttrs(attrs: Record<string, unknown>): Record<string, unknown> {

  const activeExecution = context.active().getValue(EXECUTION_CONTEXT) as

    | ExecutionState

    | undefined;

  const merged = { ...attrs };

  const ownExecutionId = merged["aap.execution.id"];

  if (ownExecutionId === undefined && activeExecution) {

    merged["aap.execution.id"] = activeExecution.id;

  } else if (

    ownExecutionId !== undefined &&

    activeExecution &&

    String(ownExecutionId) !== activeExecution.id

  ) {

    merged["aap.execution.parent_id"] ??= activeExecution.id;

  }

  if (activeExecution) {

    activeExecution.sequence += 1;

    merged["aap.observation.sequence"] ??= activeExecution.sequence;

  }

  return merged;

}



function executionContextForMerged(merged: Record<string, unknown>): Context {

  const activeExecution = context.active().getValue(EXECUTION_CONTEXT) as

    | ExecutionState

    | undefined;

  const executionId = merged["aap.execution.id"];

  const shouldAttach =

    executionId !== undefined &&

    (!activeExecution || String(executionId) !== activeExecution.id);

  if (!shouldAttach) {

    return context.active();

  }

  return context.active().setValue(EXECUTION_CONTEXT, {

    id: String(executionId),

    sequence: 0,

  } satisfies ExecutionState);

}



export interface ManualSpanHandle {

  span: Span;

  otelContext: Context;

  /** Run callback with this span active (for nested children). */

  activate: <T>(fn: () => T) => T;

  end: (err?: unknown) => void;

}



/** Start a span that stays open until {@link ManualSpanHandle.end} (streaming, LangChain). */

export function startManualSpan(

  name: string,

  attrs: Record<string, unknown> = {},

  parentContext: Context = context.active(),

): ManualSpanHandle {

  const merged = mergeExecutionAttrs(attrs);

  const span = tracer().startSpan(name, {}, parentContext);

  setAttrs(span, merged);

  const spanContext = trace.setSpan(executionContextForMerged(merged), span);

  let ended = false;



  const end = (err?: unknown) => {

    if (ended) {

      return;

    }

    ended = true;

    if (err !== undefined) {

      recordSpanError(span, err);

    } else {

      markOk(span);

    }

    span.end();

  };



  return {

    span,

    otelContext: spanContext,

    activate: <T>(fn: () => T) => context.with(spanContext, fn),

    end,

  };

}



export async function withSpan<T>(

  name: string,

  attrs: Record<string, unknown>,

  fn: (span: Span) => Promise<T> | T,

): Promise<T> {

  const merged = mergeExecutionAttrs(attrs);



  return tracer().startActiveSpan(name, async (span) => {

    setAttrs(span, merged);

    try {

      return await context.with(executionContextForMerged(merged), () => fn(span));

    } catch (err) {

      recordSpanError(span, err);

      throw err;

    } finally {

      span.end();

    }

  });

}



export function traceSpan(name = "trace", extra: Record<string, unknown> = {}) {

  return withSpan(name, { "gen_ai.operation.name": "workflow", ...extra }, async () => undefined);

}



export function agentSpan(

  name: string,

  extra: Record<string, unknown> = {},

): <T>(fn: (span: Span) => Promise<T> | T) => Promise<T> {

  const executionId = String(extra["aap.execution.id"] ?? randomUUID());

  const attrs = {

    "gen_ai.operation.name": "invoke_agent",

    "aap.execution.id": executionId,

    "aap.execution.type": "agent",

    "aap.observation.type": "agent",

    ...extra,

  };

  return <T>(fn: (span: Span) => Promise<T> | T) => withSpan(name, attrs, fn);

}



export function nodeSpan(

  name: string,

  inputState?: unknown,

  extra: Record<string, unknown> = {},

): <T>(fn: (span: Span) => Promise<T> | T) => Promise<T> {

  const captured = applyCapture(captureMode(), "aap.node.input_state", inputState) ?? {};

  const attrs = {

    "gen_ai.operation.name": "workflow",

    "aap.observation.type": "node",

    "aap.graph.node.id": name,

    "aap.graph.node.path": name,

    ...captured,

    ...extra,

  };

  return <T>(fn: (span: Span) => Promise<T> | T) => withSpan(name, attrs, fn);

}



export function stateTransitionSpan(

  source: string,

  target: string,

  extra: Record<string, unknown> = {},

): <T>(fn: (span: Span) => Promise<T> | T) => Promise<T> {

  return <T>(fn: (span: Span) => Promise<T> | T) =>

    withSpan(

      `state:${source}->${target}`,

      {

        "gen_ai.operation.name": "workflow",

        "aap.observation.type": "state_transition",

        "aap.state.from": source,

        "aap.state.to": target,

        ...extra,

      },

      fn,

    );

}



export function retrySpan(

  target: string,

  attempt: number,

  extra: Record<string, unknown> = {},

): <T>(fn: (span: Span) => Promise<T> | T) => Promise<T> {

  return <T>(fn: (span: Span) => Promise<T> | T) =>

    withSpan(

      `retry:${target}`,

      {

        "gen_ai.operation.name": "workflow",

        "aap.observation.type": "retry",

        "aap.retry.target": target,

        "aap.retry.attempt": attempt,

        ...extra,

      },

      fn,

    );

}



export function humanApprovalSpan(

  approvalId: string,

  action: string,

  extra: Record<string, unknown> = {},

): <T>(fn: (span: Span) => Promise<T> | T) => Promise<T> {

  return <T>(fn: (span: Span) => Promise<T> | T) =>

    withSpan(

      `approval:${action}`,

      {

        "gen_ai.operation.name": "workflow",

        "aap.observation.type": "human_approval",

        "aap.approval.id": approvalId,

        "aap.approval.action": action,

        ...extra,

      },

      fn,

    );

}



export function recordEvent(eventType: string, attrs: Record<string, unknown> = {}): void {

  const span = trace.getActiveSpan();

  if (!span) return;

  const activeExecution = context.active().getValue(EXECUTION_CONTEXT) as

    | ExecutionState

    | undefined;

  if (activeExecution) activeExecution.sequence += 1;

  span.addEvent(

    eventType,

    Object.fromEntries(

      Object.entries({

        "aap.event.type": eventType,

        "aap.observation.type": "event",

        "aap.execution.id": activeExecution?.id,

        "aap.observation.sequence": activeExecution?.sequence,

        ...attrs,

      })

        .filter(([, value]) => value !== undefined && value !== null)

        .map(([key, value]) => [key, attributeValue(value)]),

    ),

  );

}



export function recordCheckpoint(

  checkpointId: string,

  threadId?: string,

  extra: Record<string, unknown> = {},

): void {

  recordEvent("checkpoint.saved", {

    "aap.observation.type": "checkpoint",

    "aap.checkpoint.id": checkpointId,

    "aap.checkpoint.thread_id": threadId,

    ...extra,

  });

}



export function recordOutputState(span: Span, output: unknown): void {

  setAttrs(span, applyCapture(captureMode(), "aap.node.output_state", output) ?? {});

}



export function recordGenerationOutput(

  span: Span,

  details: GenerationResponseDetails,

): void {

  setAttrs(span, generationResponseAttributes(details, captureMode()));

}



export function generationSpan(

  provider: string,

  model: string,

  input?: unknown,

  extra: Record<string, unknown> = {},

) {

  const attrs = {

    ...generationAttributes(provider, model, captureMode(), input),

    ...extra,

  };

  return (fn: () => Promise<void> | void) => withSpan(`generation:${model}`, attrs, async () => fn());

}



export function startGenerationSpan(

  provider: string,

  model: string,

  input?: unknown,

  extra: Record<string, unknown> = {},

): ManualSpanHandle {

  const attrs = {

    ...generationRequestAttributes({ provider, model, inputMessages: input }, captureMode()),

    ...extra,

  };

  return startManualSpan(`generation:${model}`, attrs);

}



export function toolSpan(name: string, args?: unknown, extra: Record<string, unknown> = {}) {

  const attrs = { ...toolAttributes(name, captureMode(), args), ...extra };

  return (fn: () => Promise<void> | void) => withSpan(`tool:${name}`, attrs, async () => fn());

}



export function startToolSpan(

  name: string,

  args?: unknown,

  extra: Record<string, unknown> = {},

  parentContext: Context = context.active(),

): ManualSpanHandle {

  const attrs = { ...toolAttributes(name, captureMode(), args), ...extra };

  return startManualSpan(`tool:${name}`, attrs, parentContext);

}



export function retrievalSpan(query?: string, extra: Record<string, unknown> = {}) {

  const attrs = { ...retrievalAttributes(query, captureMode()), ...extra };

  return (fn: () => Promise<void> | void) => withSpan("retrieval", attrs, async () => fn());

}



export function httpSpan(

  method: string,

  url: string,

  extra: Record<string, unknown> = {},

) {

  const attrs = { ...safeHttpAttributes(method, url), ...extra };

  return (fn: () => Promise<void> | void) =>

    withSpan(`http:${method.toUpperCase()}`, attrs, async () => fn());

}



export async function observeHttpCall<T>(

  method: string,

  url: string,

  fn: () => Promise<T>,

  options?: {

    peerService?: string;

    statusFromResult?: (result: T) => number | undefined;

  },

): Promise<T> {

  const started = performance.now();

  return withSpan(`http:${method.toUpperCase()}`, safeHttpAttributes(method, url), async (span) => {

    try {

      const result = await fn();

      const status = options?.statusFromResult?.(result);

      setAttrs(span, {

        ...safeHttpAttributes(method, url, {

          statusCode: status,

          peerService: options?.peerService,

          latencyMs: performance.now() - started,

        }),

      });

      markOk(span);

      return result;

    } catch (err) {

      setAttrs(span, {

        ...safeHttpAttributes(method, url, {

          peerService: options?.peerService,

          latencyMs: performance.now() - started,

        }),

      });

      throw err;

    }

  });

}



export function databaseSpan(

  system: string,

  operation: string,

  target: string,

  statement?: unknown,

  extra: Record<string, unknown> = {},

) {

  const attrs = {

    ...databaseAttributes(system, operation, target, captureMode(), statement),

    ...extra,

  };

  return (fn: () => Promise<void> | void) =>

    withSpan(`db:${system}:${operation}`, attrs, async () => fn());

}



export async function observeDatabaseCall<T>(

  system: string,

  operation: string,

  target: string,

  fn: () => Promise<T>,

  options?: { statement?: unknown },

): Promise<T> {

  const started = performance.now();

  return withSpan(

    `db:${system}:${operation}`,

    databaseAttributes(system, operation, target, captureMode(), options?.statement),

    async (span) => {

      try {

        const result = await fn();

        span.setAttribute("db.client.operation.duration_ms", performance.now() - started);

        markOk(span);

        return result;

      } catch (err) {

        span.setAttribute("db.client.operation.duration_ms", performance.now() - started);

        throw err;

      }

    },

  );

}



/** Generic typed observation (unknown/custom integrations). */

export function observationSpan(

  observationType: string,

  name: string,

  extra: Record<string, unknown> = {},

): <T>(fn: (span: Span) => Promise<T> | T) => Promise<T> {

  const attrs = {

    "gen_ai.operation.name": "workflow",

    "aap.observation.type": observationType,

    ...extra,

  };

  return <T>(fn: (span: Span) => Promise<T> | T) => withSpan(name, attrs, fn);

}



export function sdkSpan(

  sdkName: string,

  operation: string,

  args?: unknown,

  extra: Record<string, unknown> = {},

) {

  const attrs = sdkAttributes(sdkName, operation, captureMode(), args, extra);

  return (fn: () => Promise<void> | void) =>

    withSpan(`sdk:${sdkName}:${operation}`, attrs, async () => fn());

}



export function startSdkSpan(

  sdkName: string,

  operation: string,

  args?: unknown,

  extra: Record<string, unknown> = {},

  parentContext: Context = context.active(),

): ManualSpanHandle {

  const attrs = sdkAttributes(sdkName, operation, captureMode(), args, extra);

  return startManualSpan(`sdk:${sdkName}:${operation}`, attrs, parentContext);

}



/** Cursor-style SDK operation helper (`aap.sdk.name=cursor`). */

export function cursorSdkOperation(

  operation: string,

  args?: unknown,

  extra: Record<string, unknown> = {},

) {

  return sdkSpan("cursor", operation, args, extra);

}



export function handoffSpan(target: string, extra: Record<string, unknown> = {}) {

  return (fn: () => Promise<void> | void) =>

    withSpan(

      `handoff:${target}`,

      {
        "gen_ai.operation.name": "handoff",
        "aap.observation.type": "a2a",
        "gen_ai.handoff.target": target,
        ...extra,
      },

      async () => fn(),

    );

}

export function a2aSpan(
  targetAgentId: string,
  options: {
    targetExecutionId?: string;
    targetTraceId?: string;
    protocol?: string;
    extra?: Record<string, unknown>;
  } = {},
) {
  return (fn: () => Promise<void> | void) =>
    withSpan(
      `a2a:${targetAgentId}`,
      {
        "gen_ai.operation.name": "handoff",
        "aap.observation.type": "a2a",
        "aap.a2a.target_agent_id": targetAgentId,
        "aap.a2a.target_execution_id": options.targetExecutionId,
        "aap.a2a.target_trace_id": options.targetTraceId,
        "aap.a2a.protocol": options.protocol ?? "a2a",
        ...options.extra,
      },
      async () => fn(),
    );
}

export function mcpSpan(
  server: string,
  method: string,
  options: {
    role?: "client" | "server";
    requestId?: string;
    arguments?: unknown;
    extra?: Record<string, unknown>;
  } = {},
) {
  const captured = applyCapture(captureMode(), "aap.mcp.arguments", options.arguments) ?? {};
  return (fn: () => Promise<void> | void) =>
    withSpan(
      `mcp:${server}:${method}`,
      {
        "aap.observation.type": "mcp",
        "aap.mcp.server": server,
        "aap.mcp.method": method,
        "aap.mcp.role": options.role ?? "client",
        "aap.mcp.request_id": options.requestId,
        ...captured,
        ...options.extra,
      },
      async () => fn(),
    );
}



export function markOk(span: Span): void {

  span.setStatus({ code: SpanStatusCode.OK });

}


