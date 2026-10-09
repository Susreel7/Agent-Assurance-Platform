import { applyCapture, type CaptureMode } from "./capture.js";

const HIDDEN_CONTENT_TYPES = new Set([
  "thinking",
  "reasoning",
  "redacted_thinking",
  "chain_of_thought",
]);

const HIDDEN_FIELD_NAMES = new Set([
  "reasoning",
  "thinking",
  "chain_of_thought",
  "chainOfThought",
  "reasoning_content",
  "reasoningContent",
]);

/** Remove provider hidden-reasoning blocks before capture (never synthesize reasoning). */
export function stripHiddenReasoning(value: unknown): unknown {
  if (value == null || typeof value !== "object") {
    return value;
  }
  if (Array.isArray(value)) {
    return value.map(stripHiddenReasoning);
  }
  const record = value as Record<string, unknown>;
  const out: Record<string, unknown> = {};
  for (const [key, child] of Object.entries(record)) {
    if (HIDDEN_FIELD_NAMES.has(key)) {
      continue;
    }
    out[key] = stripHiddenReasoning(child);
  }
  if (Array.isArray(out.content)) {
    out.content = out.content.filter((block) => {
      if (block == null || typeof block !== "object") {
        return true;
      }
      const type = (block as Record<string, unknown>).type;
      return typeof type !== "string" || !HIDDEN_CONTENT_TYPES.has(type);
    });
  }
  return out;
}

export interface GenerationRequestDetails {
  provider: string;
  model: string;
  operation?: string;
  systemInstructions?: unknown;
  inputMessages?: unknown;
  requestId?: string;
  parameters?: Record<string, unknown>;
}

export function generationRequestAttributes(
  details: GenerationRequestDetails,
  captureMode: CaptureMode,
): Record<string, unknown> {
  const attrs: Record<string, unknown> = {
    "gen_ai.operation.name": details.operation ?? "chat",
    "gen_ai.provider.name": details.provider,
    "gen_ai.request.model": details.model,
    "aap.observation.type": "generation",
  };
  if (details.requestId) {
    attrs["gen_ai.request.id"] = details.requestId;
  }
  if (details.parameters) {
    for (const [key, value] of Object.entries(details.parameters)) {
      if (value !== undefined && value !== null) {
        attrs[`gen_ai.request.${key}`] = value;
      }
    }
  }
  for (const [field, raw] of [
    ["gen_ai.system_instructions", details.systemInstructions],
    ["gen_ai.input.messages", details.inputMessages],
  ] as const) {
    const captured = applyCapture(captureMode, field, stripHiddenReasoning(raw));
    if (captured) {
      Object.assign(attrs, captured);
    }
  }
  return attrs;
}

export interface GenerationResponseDetails {
  responseId?: string;
  model?: string;
  finishReason?: string;
  outputMessages?: unknown;
  toolCalls?: unknown;
  inputTokens?: number;
  outputTokens?: number;
  totalTokens?: number;
}

export function generationResponseAttributes(
  details: GenerationResponseDetails,
  captureMode: CaptureMode,
): Record<string, unknown> {
  const attrs: Record<string, unknown> = {};
  if (details.responseId) {
    attrs["gen_ai.response.id"] = details.responseId;
  }
  if (details.model) {
    attrs["gen_ai.response.model"] = details.model;
  }
  if (details.finishReason) {
    attrs["gen_ai.response.finish_reasons"] = [details.finishReason];
  }
  if (details.inputTokens !== undefined) {
    attrs["gen_ai.usage.input_tokens"] = details.inputTokens;
  }
  if (details.outputTokens !== undefined) {
    attrs["gen_ai.usage.output_tokens"] = details.outputTokens;
  }
  if (details.totalTokens !== undefined) {
    attrs["gen_ai.usage.total_tokens"] = details.totalTokens;
  }
  for (const [field, raw] of [
    ["gen_ai.output.messages", details.outputMessages],
    ["gen_ai.output.tool_calls", details.toolCalls],
  ] as const) {
    const captured = applyCapture(captureMode, field, stripHiddenReasoning(raw));
    if (captured) {
      Object.assign(attrs, captured);
    }
  }
  return attrs;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value != null && typeof value === "object" ? (value as Record<string, unknown>) : null;
}

export function openAIResponseDetails(response: unknown): GenerationResponseDetails {
  const root = asRecord(response);
  if (!root) {
    return {};
  }
  const usage = asRecord(root.usage);
  const choices = Array.isArray(root.choices) ? root.choices : [];
  const first = asRecord(choices[0]);
  const message = first ? asRecord(first.message) : null;
  const finishReason = first?.finish_reason;
  return {
    responseId: typeof root.id === "string" ? root.id : undefined,
    model: typeof root.model === "string" ? root.model : undefined,
    finishReason: typeof finishReason === "string" ? finishReason : undefined,
    outputMessages: message?.content ?? message,
    toolCalls: message?.tool_calls,
    inputTokens: typeof usage?.prompt_tokens === "number" ? usage.prompt_tokens : undefined,
    outputTokens:
      typeof usage?.completion_tokens === "number" ? usage.completion_tokens : undefined,
    totalTokens: typeof usage?.total_tokens === "number" ? usage.total_tokens : undefined,
  };
}

export function openAIStreamChunkDetails(chunk: unknown): Partial<GenerationResponseDetails> {
  const root = asRecord(chunk);
  if (!root) {
    return {};
  }
  const usage = asRecord(root.usage);
  const choices = Array.isArray(root.choices) ? root.choices : [];
  const first = asRecord(choices[0]);
  const delta = first ? asRecord(first.delta) : null;
  const finishReason = first?.finish_reason;
  const partial: Partial<GenerationResponseDetails> = {};
  if (typeof root.id === "string") {
    partial.responseId = root.id;
  }
  if (typeof root.model === "string") {
    partial.model = root.model;
  }
  if (typeof finishReason === "string") {
    partial.finishReason = finishReason;
  }
  if (delta?.tool_calls) {
    partial.toolCalls = delta.tool_calls;
  }
  if (delta?.content !== undefined) {
    partial.outputMessages = delta.content;
  }
  if (usage) {
    if (typeof usage.prompt_tokens === "number") {
      partial.inputTokens = usage.prompt_tokens;
    }
    if (typeof usage.completion_tokens === "number") {
      partial.outputTokens = usage.completion_tokens;
    }
    if (typeof usage.total_tokens === "number") {
      partial.totalTokens = usage.total_tokens;
    }
  }
  return partial;
}

export function anthropicResponseDetails(response: unknown): GenerationResponseDetails {
  const root = asRecord(response);
  if (!root) {
    return {};
  }
  const usage = asRecord(root.usage);
  const stopReason = root.stop_reason;
  return {
    responseId: typeof root.id === "string" ? root.id : undefined,
    model: typeof root.model === "string" ? root.model : undefined,
    finishReason: typeof stopReason === "string" ? stopReason : undefined,
    outputMessages: root.content,
    inputTokens: typeof usage?.input_tokens === "number" ? usage.input_tokens : undefined,
    outputTokens: typeof usage?.output_tokens === "number" ? usage.output_tokens : undefined,
  };
}

export function anthropicStreamChunkDetails(event: unknown): Partial<GenerationResponseDetails> {
  const root = asRecord(event);
  if (!root) {
    return {};
  }
  const type = root.type;
  if (type === "message_start") {
    const message = asRecord(root.message);
    const usage = message ? asRecord(message.usage) : null;
    return {
      responseId: typeof message?.id === "string" ? message.id : undefined,
      model: typeof message?.model === "string" ? message.model : undefined,
      inputTokens: typeof usage?.input_tokens === "number" ? usage.input_tokens : undefined,
    };
  }
  if (type === "message_delta") {
    const usage = asRecord(root.usage);
    const delta = asRecord(root.delta);
    return {
      finishReason: typeof delta?.stop_reason === "string" ? delta.stop_reason : undefined,
      outputTokens: typeof usage?.output_tokens === "number" ? usage.output_tokens : undefined,
    };
  }
  if (type === "content_block_delta") {
    const delta = asRecord(root.delta);
    const text = delta?.text;
    if (typeof text === "string" && text.length > 0) {
      return { outputMessages: text };
    }
  }
  return {};
}

export function mergeGenerationResponseDetails(
  base: GenerationResponseDetails,
  patch: Partial<GenerationResponseDetails>,
): GenerationResponseDetails {
  return {
    responseId: patch.responseId ?? base.responseId,
    model: patch.model ?? base.model,
    finishReason: patch.finishReason ?? base.finishReason,
    outputMessages: patch.outputMessages ?? base.outputMessages,
    toolCalls: patch.toolCalls ?? base.toolCalls,
    inputTokens: patch.inputTokens ?? base.inputTokens,
    outputTokens: patch.outputTokens ?? base.outputTokens,
    totalTokens: patch.totalTokens ?? base.totalTokens,
  };
}

export function openAIRequestParameters(kwargs: Record<string, unknown>): Record<string, unknown> {
  const allowed = [
    "temperature",
    "top_p",
    "max_tokens",
    "max_completion_tokens",
    "presence_penalty",
    "frequency_penalty",
    "seed",
    "response_format",
    "tool_choice",
    "parallel_tool_calls",
  ] as const;
  const params: Record<string, unknown> = {};
  for (const key of allowed) {
    if (kwargs[key] !== undefined) {
      params[key] = kwargs[key];
    }
  }
  if (Array.isArray(kwargs.tools)) {
    params.tool_count = kwargs.tools.length;
  }
  return params;
}

export function anthropicRequestParameters(kwargs: Record<string, unknown>): Record<string, unknown> {
  const allowed = ["temperature", "top_p", "top_k", "max_tokens", "stop_sequences"] as const;
  const params: Record<string, unknown> = {};
  for (const key of allowed) {
    if (kwargs[key] !== undefined) {
      params[key] = kwargs[key];
    }
  }
  if (Array.isArray(kwargs.tools)) {
    params.tool_count = kwargs.tools.length;
  }
  return params;
}
