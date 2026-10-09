import { applyCapture, type CaptureMode } from "./capture.js";
import { generationRequestAttributes } from "./generation.js";

export function resourceAttributes(cfg: {
  organizationId: string;
  projectId: string;
  serviceName: string;
  environment: string;
  agentId?: string;
  agentName?: string;
  agentVersion?: string;
  metadata?: Record<string, string>;
  sessionId?: string;
  userId?: string;
  actorId?: string;
  actorType?: string;
  invocationSource?: string;
  applicationName?: string;
  clientName?: string;
  requestId?: string;
  replayOfExecutionId?: string;
  tags?: string[];
  sampleRate?: number;
}): Record<string, string> {
  const attrs: Record<string, string> = {
    "service.name": cfg.serviceName,
    "deployment.environment": cfg.environment,
    "aap.organization.id": cfg.organizationId,
    "aap.project.id": cfg.projectId,
    "aap.environment.id": cfg.environment,
    "aap.organization_id": cfg.organizationId,
    "aap.project_id": cfg.projectId,
  };
  if (cfg.agentId) attrs["gen_ai.agent.id"] = cfg.agentId;
  if (cfg.agentName) attrs["gen_ai.agent.name"] = cfg.agentName;
  if (cfg.agentVersion) {
    attrs["gen_ai.agent.version"] = cfg.agentVersion;
    attrs["aap.agent.version_id"] = cfg.agentVersion;
  }
  if (cfg.sessionId) {
    attrs["gen_ai.conversation.id"] = cfg.sessionId;
    attrs["aap.user.session_id"] = cfg.sessionId;
  }
  if (cfg.userId) {
    attrs["enduser.id"] = cfg.userId;
    attrs["aap.user.id"] = cfg.userId;
  }
  if (cfg.actorId) attrs["aap.actor.id"] = cfg.actorId;
  if (cfg.actorType) attrs["aap.actor.type"] = cfg.actorType;
  if (cfg.invocationSource) attrs["aap.invocation.source"] = cfg.invocationSource;
  if (cfg.applicationName) attrs["aap.invocation.application"] = cfg.applicationName;
  if (cfg.clientName) attrs["aap.invocation.client"] = cfg.clientName;
  if (cfg.requestId) attrs["aap.request.id"] = cfg.requestId;
  if (cfg.replayOfExecutionId) {
    attrs["aap.replay.of_execution_id"] = cfg.replayOfExecutionId;
  }
  if (cfg.sampleRate !== undefined) attrs["aap.sampling.rate"] = String(cfg.sampleRate);
  if (cfg.tags?.length) attrs["aap.tags"] = cfg.tags.join(",");
  if (cfg.metadata) {
    for (const [k, v] of Object.entries(cfg.metadata)) {
      attrs[`aap.metadata.${k}`] = v;
    }
  }
  return attrs;
}

export function generationAttributes(
  provider: string,
  model: string,
  captureMode: CaptureMode,
  input?: unknown,
): Record<string, unknown> {
  return generationRequestAttributes(
    { provider, model, inputMessages: input },
    captureMode,
  );
}

export function toolAttributes(
  name: string,
  captureMode: CaptureMode,
  args?: unknown,
): Record<string, unknown> {
  const attrs: Record<string, unknown> = {
    "gen_ai.operation.name": "execute_tool",
    "aap.observation.type": "tool",
    "gen_ai.tool.name": name,
    "gen_ai.tool.type": "function",
  };
  const captured = applyCapture(captureMode, "gen_ai.tool.call.arguments", args);
  if (captured) Object.assign(attrs, captured);
  return attrs;
}

export function retrievalAttributes(
  query: string | undefined,
  captureMode: CaptureMode,
): Record<string, unknown> {
  const attrs: Record<string, unknown> = {
    "gen_ai.operation.name": "retrieval",
    "aap.observation.type": "retrieval",
  };
  const captured = applyCapture(captureMode, "gen_ai.retrieval.query", query);
  if (captured) {
    Object.assign(attrs, captured);
  } else if (query !== undefined && captureMode === "none") {
    attrs["gen_ai.retrieval.query.length"] = query.length;
  }
  return attrs;
}

export function databaseAttributes(
  system: string,
  operation: string,
  target: string,
  captureMode: CaptureMode,
  statement?: unknown,
): Record<string, unknown> {
  const attrs: Record<string, unknown> = {
    "gen_ai.operation.name": "database",
    "aap.observation.type": "database",
    "db.system": system,
    "db.operation": operation,
    "db.name": target,
  };
  const captured = applyCapture(captureMode, "db.statement", statement);
  if (captured) {
    Object.assign(attrs, captured);
  }
  return attrs;
}

export function sdkAttributes(
  sdkName: string,
  operation: string,
  captureMode: CaptureMode,
  args?: unknown,
  extra?: Record<string, unknown>,
): Record<string, unknown> {
  const attrs: Record<string, unknown> = {
    "gen_ai.operation.name": "sdk",
    "aap.observation.type": "sdk",
    "aap.sdk.name": sdkName,
    "aap.sdk.operation": operation,
    ...extra,
  };
  const captured = applyCapture(captureMode, "aap.sdk.arguments", args);
  if (captured) {
    Object.assign(attrs, captured);
  }
  return attrs;
}
