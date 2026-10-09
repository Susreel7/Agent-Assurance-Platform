import { context, propagation, trace } from "@opentelemetry/api";
import { W3CTraceContextPropagator } from "@opentelemetry/core";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { Resource } from "@opentelemetry/resources";
import { AsyncLocalStorageContextManager } from "@opentelemetry/context-async-hooks";
import {
  BatchSpanProcessor,
  BasicTracerProvider,
  ParentBasedSampler,
  TraceIdRatioBasedSampler,
  type SpanProcessor,
} from "@opentelemetry/sdk-trace-base";
import { NodeTracerProvider } from "@opentelemetry/sdk-trace-node";

import { resourceAttributes } from "./attributes.js";
import type { TraceConfig } from "./config.js";
import { ScoreClient } from "./scores.js";

let globalClient: TraceClient | null = null;

function normalizeEndpoint(endpoint: string): string {
  const base = endpoint.replace(/\/$/, "");
  if (base.endsWith("/v1/traces")) return base;
  if (base.endsWith("/v1")) return `${base}/traces`;
  return `${base}/v1/traces`;
}

export class TraceClient {
  readonly config: TraceConfig;
  private provider: BasicTracerProvider | NodeTracerProvider | null = null;
  private processor: SpanProcessor | null = null;
  readonly scores: ScoreClient;

  constructor(config: TraceConfig) {
    const sampleRate = config.sampleRate ?? 1;
    if (!Number.isFinite(sampleRate) || sampleRate < 0 || sampleRate > 1) {
      throw new RangeError("sampleRate must be between 0 and 1");
    }
    this.config = config;
    this.scores = new ScoreClient(config);
    if (config.enabled !== false && config.endpoint && config.bearerToken) {
      this.initOtel(config);
    }
  }

  private initOtel(config: TraceConfig): void {
    propagation.setGlobalPropagator(new W3CTraceContextPropagator());
    const ctxManager = new AsyncLocalStorageContextManager();
    ctxManager.enable();
    context.setGlobalContextManager(ctxManager);

    const resource = new Resource(
      resourceAttributes({
        organizationId: config.organizationId,
        projectId: config.projectId,
        serviceName: config.serviceName ?? "agent-runtime",
        environment: config.environment ?? "production",
        agentId: config.agentId,
        agentName: config.agentName,
        agentVersion: config.agentVersion,
        metadata: config.metadata,
        sessionId: config.sessionId,
        userId: config.userId,
        actorId: config.actorId,
        actorType: config.actorType,
        invocationSource: config.invocationSource,
        applicationName: config.applicationName,
        clientName: config.clientName,
        requestId: config.requestId,
        replayOfExecutionId: config.replayOfExecutionId,
        tags: config.tags,
        sampleRate: config.sampleRate ?? 1,
      }),
    );

    const exporter = new OTLPTraceExporter({
      url: normalizeEndpoint(config.endpoint),
      headers: { Authorization: `Bearer ${config.bearerToken}` },
      timeoutMillis: config.otlpTimeoutMillis ?? 10_000,
    });

    const provider = new NodeTracerProvider({
      resource,
      sampler: new ParentBasedSampler({
        root: new TraceIdRatioBasedSampler(config.sampleRate ?? 1),
      }),
    });
    const processor = new BatchSpanProcessor(exporter);
    provider.addSpanProcessor(processor);
    provider.register();
    this.provider = provider;
    this.processor = processor;
  }

  get tracer() {
    return trace.getTracer("aap_trace", "0.1.0");
  }

  async flush(): Promise<boolean> {
    if (!this.processor?.forceFlush) return true;
    await this.processor.forceFlush();
    return true;
  }

  async shutdown(): Promise<void> {
    await this.processor?.shutdown();
    await this.provider?.shutdown();
  }
}

export function configure(config: TraceConfig): TraceClient {
  if (globalClient) {
    void globalClient.shutdown();
  }
  globalClient = new TraceClient(config);
  return globalClient;
}

export function getClient(): TraceClient {
  if (!globalClient) throw new Error("configure() has not been called");
  return globalClient;
}

export async function shutdown(): Promise<void> {
  if (globalClient) {
    await globalClient.shutdown();
    globalClient = null;
  }
}
