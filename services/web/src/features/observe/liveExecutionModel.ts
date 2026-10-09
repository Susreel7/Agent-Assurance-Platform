import type { ObserveLiveEvent } from "@/api/types";
import {
  isGraphEventType,
  normalizeExecutionStatus,
  type ExecutionGraphItem,
  type ExecutionVisualStatus,
} from "./executionGraphModel";

function lifecycleStatus(event: ObserveLiveEvent): ExecutionVisualStatus {
  if (event.type.endsWith(".started")) return "running";
  if (event.type.endsWith(".failed")) return "failed";
  return normalizeExecutionStatus(event.payload.outcome ?? event.payload.status ?? "succeeded");
}

function eventStatus(event: ObserveLiveEvent): ExecutionVisualStatus {
  const eventType = event.payload.event_type?.toLowerCase() ?? "";
  if (eventType.includes("retry")) return "retry";
  if (eventType.includes("error") || eventType.includes("fail")) return "failed";
  if (eventType.includes("approval") || eventType.includes("interrupt")) return "waiting";
  return normalizeExecutionStatus(event.payload.status);
}

export function applyLiveExecutionEvents(
  baseItems: ExecutionGraphItem[],
  events: ObserveLiveEvent[],
  traceId: string,
): ExecutionGraphItem[] {
  if (events.length === 0) return baseItems;
  const byId = new Map(baseItems.map((item) => [item.id, item]));
  const knownSpanIds = new Set(
    baseItems.filter((item) => item.source === "observation").map((item) => item.id),
  );
  const rootId =
    baseItems.find((item) => !item.parentId || !knownSpanIds.has(item.parentId))?.id ?? null;

  for (const event of events) {
    if (event.trace_id !== traceId) continue;
    if (event.type === "event.recorded") {
      const id = `live-event:${event.cursor}`;
      if (byId.has(id)) continue;
      byId.set(id, {
        id,
        parentId:
          event.span_id && (knownSpanIds.has(event.span_id) || byId.has(event.span_id))
            ? event.span_id
            : rootId,
        label: event.payload.event_type ?? "Event",
        type: (event.payload.observation_type ?? "event").toLowerCase(),
        graphVisible: isGraphEventType(event.payload.event_type ?? "event"),
        status: eventStatus(event),
        durationMs: null,
        startTime: event.payload.event_time ?? event.created_at,
        source: "event",
      });
      continue;
    }
    if (!event.span_id) continue;
    const existing = byId.get(event.span_id);
    const status = lifecycleStatus(event);
    const startTime = event.payload.start_time ?? existing?.startTime ?? event.created_at;
    byId.set(event.span_id, {
      id: event.span_id,
      parentId: event.payload.parent_span_id ?? existing?.parentId ?? null,
      label: event.payload.operation_name ?? existing?.label ?? event.payload.kind ?? "Operation",
      type: (
        event.payload.observation_type ??
        event.payload.kind ??
        existing?.type ??
        "unknown"
      ).toLowerCase(),
      status,
      durationMs: event.payload.duration_ms ?? existing?.durationMs ?? null,
      startTime,
      source: "observation",
      observation: existing?.observation
        ? {
            ...existing.observation,
            parent_span_id:
              event.payload.parent_span_id ?? existing.observation.parent_span_id,
            operation_name:
              event.payload.operation_name ?? existing.observation.operation_name,
            observation_type:
              event.payload.observation_type ?? existing.observation.observation_type,
            kind: event.payload.kind ?? existing.observation.kind,
            outcome: event.payload.outcome ?? existing.observation.outcome,
            start_time: startTime,
            end_time: event.payload.end_time ?? existing.observation.end_time,
            duration_ms: event.payload.duration_ms ?? existing.observation.duration_ms,
            is_terminal:
              event.payload.is_terminal ?? !event.type.endsWith(".started"),
            retry_attempt:
              event.payload.retry_attempt ?? existing.observation.retry_attempt,
          }
        : undefined,
    });
    knownSpanIds.add(event.span_id);
  }

  return [...byId.values()].sort((left, right) => {
    const timeOrder = (left.startTime ?? "").localeCompare(right.startTime ?? "");
    return timeOrder || left.id.localeCompare(right.id);
  });
}
