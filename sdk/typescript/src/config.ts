import type { CaptureMode } from "./capture.js";

export interface TraceConfig {
  endpoint: string;
  bearerToken: string;
  organizationId: string;
  projectId: string;
  agentId?: string;
  agentName?: string;
  agentVersion?: string;
  sessionId?: string;
  userId?: string;
  actorId?: string;
  actorType?: string;
  invocationSource?: string;
  applicationName?: string;
  clientName?: string;
  requestId?: string;
  replayOfExecutionId?: string;
  environment?: string;
  serviceName?: string;
  enabled?: boolean;
  captureMode?: CaptureMode;
  tags?: string[];
  metadata?: Record<string, string>;
  scoreBaseUrl?: string;
  otlpTimeoutMillis?: number;
  sampleRate?: number;
}

export function traceConfigFromEnv(overrides: Partial<TraceConfig> = {}): TraceConfig {
  const env = process.env;
  const disabled = (env.OTEL_SDK_DISABLED ?? "false").toLowerCase();
  return {
    endpoint:
      overrides.endpoint ??
      env.OTEL_EXPORTER_OTLP_TRACES_ENDPOINT ??
      env.OTEL_EXPORTER_OTLP_ENDPOINT ??
      "",
    bearerToken:
      overrides.bearerToken ?? env.AAP_WORKLOAD_TOKEN ?? env.AAP_BEARER_TOKEN ?? "",
    organizationId: overrides.organizationId ?? env.AAP_ORGANIZATION_ID ?? "",
    projectId: overrides.projectId ?? env.AAP_PROJECT_ID ?? "",
    agentId: overrides.agentId ?? env.AAP_AGENT_ID,
    agentName: overrides.agentName ?? env.AAP_AGENT_NAME,
    agentVersion: overrides.agentVersion ?? env.AAP_AGENT_VERSION,
    sessionId: overrides.sessionId ?? env.AAP_SESSION_ID ?? env.GEN_AI_CONVERSATION_ID,
    userId: overrides.userId ?? env.AAP_USER_ID,
    actorId: overrides.actorId ?? env.AAP_ACTOR_ID,
    actorType: overrides.actorType ?? env.AAP_ACTOR_TYPE,
    invocationSource: overrides.invocationSource ?? env.AAP_INVOCATION_SOURCE,
    applicationName: overrides.applicationName ?? env.AAP_APPLICATION_NAME,
    clientName: overrides.clientName ?? env.AAP_CLIENT_NAME,
    requestId: overrides.requestId ?? env.AAP_REQUEST_ID,
    replayOfExecutionId:
      overrides.replayOfExecutionId ?? env.AAP_REPLAY_OF_EXECUTION_ID,
    environment:
      overrides.environment ??
      env.DEPLOYMENT_ENVIRONMENT ??
      env.AAP_ENVIRONMENT ??
      "production",
    serviceName: overrides.serviceName ?? env.OTEL_SERVICE_NAME ?? "agent-runtime",
    enabled: overrides.enabled ?? !["true", "1", "yes"].includes(disabled),
    captureMode: (overrides.captureMode ??
      (env.AAP_CAPTURE_MODE as CaptureMode) ??
      "none") as CaptureMode,
    scoreBaseUrl: overrides.scoreBaseUrl ?? env.AAP_SCORE_BASE_URL,
    sampleRate: overrides.sampleRate ?? Number(env.AAP_SAMPLE_RATE ?? "1"),
    ...overrides,
  };
}
