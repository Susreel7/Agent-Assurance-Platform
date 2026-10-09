import type { TraceConfig } from "./config.js";

export interface ScoreRecord {
  name: string;
  value: number;
  traceId?: string;
  spanId?: string;
  sessionId?: string;
  comment?: string;
  metadata?: Record<string, string>;
  /** @default "human" */
  source?: "human" | "automated";
}

function scoreTarget(score: ScoreRecord): { targetType: string; targetId: string } {
  if (score.spanId) {
    return { targetType: "span", targetId: score.spanId };
  }
  if (score.traceId) {
    return { targetType: "trace", targetId: score.traceId };
  }
  if (score.sessionId) {
    return { targetType: "session", targetId: score.sessionId };
  }
  throw new Error("score requires traceId, spanId, or sessionId");
}

function scoreBody(score: ScoreRecord): Record<string, unknown> {
  const { targetType, targetId } = scoreTarget(score);
  const body: Record<string, unknown> = {
    target_type: targetType,
    target_id: targetId,
    name: score.name,
    value_type: "numeric",
    value_numeric: score.value,
    source: score.source ?? "human",
  };
  if (score.comment) {
    body.explanation = score.comment;
  }
  if (score.metadata) {
    body.metadata = score.metadata;
  }
  return body;
}

export class ScoreClient {
  private readonly url: string;
  private readonly headers: Record<string, string>;
  private readonly enabled: boolean;
  private readonly timeout: number;

  constructor(private readonly config: TraceConfig) {
    const base = config.scoreBaseUrl ?? config.endpoint.replace(/\/v1\/.*$/, "");
    this.url = `${base.replace(/\/$/, "")}/v1/evaluate/workload/scores`;
    this.headers = {
      Authorization: `Bearer ${config.bearerToken}`,
      "Content-Type": "application/json",
    };
    this.enabled = config.enabled !== false;
    this.timeout = config.otlpTimeoutMillis ?? 10_000;
  }

  async submit(score: ScoreRecord): Promise<void> {
    if (!this.enabled) return;
    const body = scoreBody(score);
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeout);
    try {
      const resp = await fetch(this.url, {
        method: "POST",
        headers: this.headers,
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      if (!resp.ok) {
        throw new Error(`score submit failed: ${resp.status}`);
      }
    } finally {
      clearTimeout(timer);
    }
  }
}
