import type { ExecutionEvent, ExecutionObservation } from "@/api/types";

export type ExecutionVisualStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "skipped"
  | "retry"
  | "waiting"
  | "unknown";

export type ExecutionGraphItem = {
  id: string;
  parentId: string | null;
  label: string;
  type: string;
  graphVisible?: boolean;
  status: ExecutionVisualStatus;
  durationMs: number | null;
  startTime: string | null;
  source: "observation" | "event";
  observation?: ExecutionObservation;
  event?: ExecutionEvent;
};

const GRAPH_EVENT_MARKERS = [
  "approval",
  "branch",
  "checkpoint",
  "error",
  "failed",
  "interrupt",
  "retry",
  "state",
  "transition",
];

export function normalizeExecutionStatus(value?: string | null): ExecutionVisualStatus {
  const status = (value ?? "").toLowerCase();
  if (["success", "succeeded", "ok", "completed"].includes(status)) return "succeeded";
  if (["error", "failed", "failure", "timed_out", "cancelled"].includes(status)) return "failed";
  if (status.includes("retry")) return "retry";
  if (status.includes("skip")) return "skipped";
  if (status.includes("wait") || status.includes("approval") || status.includes("interrupt")) {
    return "waiting";
  }
  if (status === "open" || status === "running" || status === "started") return "running";
  if (status === "queued" || status === "pending") return "queued";
  return "unknown";
}

function eventType(event: ExecutionEvent): string {
  const name = event.event_type.toLowerCase();
  if (name.includes("retry")) return "retry";
  if (name.includes("state") || name.includes("transition") || name.includes("branch")) {
    return "state_transition";
  }
  if (name.includes("error") || name.includes("fail")) return "error";
  return "event";
}

function eventStatus(event: ExecutionEvent): ExecutionVisualStatus {
  const name = `${event.event_type} ${event.status ?? ""}`.toLowerCase();
  if (name.includes("retry")) return "retry";
  if (name.includes("error") || name.includes("fail")) return "failed";
  if (name.includes("approval") || name.includes("interrupt") || name.includes("wait")) {
    return "waiting";
  }
  if (name.includes("started") || name.includes("queued")) return "running";
  if (
    name.includes("completed") ||
    name.includes("attached") ||
    name.includes("checkpoint") ||
    name.includes("transition") ||
    name.includes("branch")
  ) {
    return "succeeded";
  }
  return normalizeExecutionStatus(event.status);
}

export function isGraphEventType(eventType: string): boolean {
  const name = eventType.toLowerCase();
  return GRAPH_EVENT_MARKERS.some((marker) => name.includes(marker));
}

export function buildExecutionGraphItems(
  observations: ExecutionObservation[],
  events: ExecutionEvent[],
): ExecutionGraphItem[] {
  const observationItems: ExecutionGraphItem[] = observations.map((observation) => ({
    id: observation.span_id,
    parentId: observation.parent_span_id ?? null,
    label: observation.operation_name,
    type: (observation.observation_type ?? observation.kind ?? "unknown").toLowerCase(),
    status: normalizeExecutionStatus(
      observation.is_terminal ? observation.outcome ?? "succeeded" : observation.outcome ?? "running",
    ),
    durationMs: observation.duration_ms ?? null,
    startTime: observation.start_time ?? null,
    source: "observation",
    observation,
  }));

  const knownSpanIds = new Set(observationItems.map((item) => item.id));
  const rootId =
    observationItems.find((item) => !item.parentId || !knownSpanIds.has(item.parentId))?.id ?? null;
  const eventItems = events.map<ExecutionGraphItem>((event, index) => {
    const type = eventType(event);
    const status = eventStatus(event);
    return {
      id: `event:${event.event_uid ?? `${event.event_type}:${index}`}`,
      parentId: event.span_id && knownSpanIds.has(event.span_id) ? event.span_id : rootId,
      label: event.event_type,
      type,
      graphVisible: isGraphEventType(event.event_type),
      status,
      durationMs: null,
      startTime: event.event_time ?? null,
      source: "event",
      event,
    };
  });

  return [...observationItems, ...eventItems].sort((left, right) => {
    const timeOrder = (left.startTime ?? "").localeCompare(right.startTime ?? "");
    if (timeOrder !== 0) return timeOrder;
    return left.source === right.source ? left.id.localeCompare(right.id) : left.source === "observation" ? -1 : 1;
  });
}

export function formatDuration(durationMs?: number | null): string {
  if (durationMs == null) return "—";
  if (durationMs < 1) return `${Math.round(durationMs * 1000)} μs`;
  if (durationMs < 1000) return `${durationMs.toFixed(durationMs < 10 ? 1 : 0)} ms`;
  if (durationMs < 60_000) return `${(durationMs / 1000).toFixed(1)} s`;
  return `${(durationMs / 60_000).toFixed(1)} min`;
}

export function executionTypeLabel(type: string): string {
  return type
    .replaceAll("_", " ")
    .replace(/\b\w/g, (character) => character.toUpperCase());
}
