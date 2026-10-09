import { useMemo, useState } from "react";
import type {
  ExecutionEvent,
  ExecutionObservation,
  ExecutionSummary,
} from "@/api/types";
import { formatTableDate } from "@/lib/dates";
import {
  executionTypeLabel,
  formatDuration,
  normalizeExecutionStatus,
  type ExecutionGraphItem,
} from "./executionGraphModel";

type Props = {
  execution: ExecutionSummary;
  observations: ExecutionObservation[];
  events: ExecutionEvent[];
  selectedItem: ExecutionGraphItem | null;
  onSelect: (id: string) => void;
};

type ActivityTab = "events" | "logs" | "json";
type LevelFilter = "all" | "error" | "retry";

function eventId(event: ExecutionEvent, index: number): string {
  return `event:${event.event_uid ?? `${event.event_type}:${index}`}`;
}

function includesQuery(values: Array<string | number | null | undefined>, query: string): boolean {
  if (!query) return true;
  return values.some((value) => String(value ?? "").toLowerCase().includes(query));
}

function eventLevel(event: ExecutionEvent): "error" | "retry" | "info" {
  const value = `${event.event_type} ${event.status ?? ""}`.toLowerCase();
  if (value.includes("error") || value.includes("fail")) return "error";
  if (value.includes("retry")) return "retry";
  return "info";
}

function levelDot(level: "error" | "retry" | "info"): string {
  if (level === "error") return "bg-risk-solid";
  if (level === "retry") return "bg-warn-solid";
  return "bg-info-solid";
}

export function ExecutionActivityPanel({
  execution,
  observations,
  events,
  selectedItem,
  onSelect,
}: Props) {
  const [expanded, setExpanded] = useState(true);
  const [tab, setTab] = useState<ActivityTab>("events");
  const [query, setQuery] = useState("");
  const [level, setLevel] = useState<LevelFilter>("all");
  const normalizedQuery = query.trim().toLowerCase();

  const visibleEvents = useMemo(
    () =>
      events
        .map((event, index) => ({ event, id: eventId(event, index), level: eventLevel(event) }))
        .filter(
          ({ event, level: eventLevelValue }) =>
            (level === "all" || eventLevelValue === level) &&
            includesQuery(
              [
                event.event_type,
                event.status,
                event.span_id,
                event.tool_name,
                event.model,
                event.sdk_name,
                ...Object.entries(event.attributes ?? {}).flat(),
              ],
              normalizedQuery,
            ),
        ),
    [events, level, normalizedQuery],
  );

  const visibleOperations = useMemo(
    () =>
      observations.filter((observation) => {
        const status = normalizeExecutionStatus(observation.outcome);
        const matchesLevel =
          level === "all" ||
          (level === "error" && status === "failed") ||
          (level === "retry" && observation.retry_attempt > 0);
        return (
          matchesLevel &&
          includesQuery(
            [
              observation.operation_name,
              observation.observation_type,
              observation.outcome,
              observation.tool_name,
              observation.model,
              observation.sdk_name,
              observation.span_id,
            ],
            normalizedQuery,
          )
        );
      }),
    [level, normalizedQuery, observations],
  );

  const rawValue = selectedItem?.observation ?? selectedItem?.event ?? execution;
  const exportActivity = () => {
    const content = JSON.stringify({ execution, observations, events }, null, 2);
    const url = URL.createObjectURL(new Blob([content], { type: "application/json" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${execution.execution_id}-activity.json`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  return (
    <section className="border-t border-line-200 bg-bg-panel" aria-label="Execution activity">
      <div className="flex min-h-10 flex-wrap items-center justify-between gap-2 border-b border-line-200 px-3">
        <div className="flex h-10 items-center gap-3">
          <button
            type="button"
            className="font-medium text-ink-900 hover:text-info-fg"
            onClick={() => setExpanded((value) => !value)}
            aria-expanded={expanded}
          >
            {expanded ? "▾" : "▸"} Activity
          </button>
          <span className="text-micro text-ink-400">
            {events.length} events · {observations.length} operations
          </span>
        </div>
        {expanded ? (
          <div className="flex items-center gap-2">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search activity"
              aria-label="Search execution activity"
              className="h-7 w-48 border border-line-200 bg-bg-panel px-2 text-xs outline-none focus:border-info-fg"
            />
            <select
              value={level}
              onChange={(event) => setLevel(event.target.value as LevelFilter)}
              aria-label="Filter activity level"
              className="h-7 border border-line-200 bg-bg-panel px-2 text-xs text-ink-600"
            >
              <option value="all">All levels</option>
              <option value="error">Errors</option>
              <option value="retry">Retries</option>
            </select>
            <button
              type="button"
              onClick={exportActivity}
              className="h-7 border border-line-200 px-2 text-xs text-ink-600 hover:bg-bg-hover"
            >
              Export
            </button>
          </div>
        ) : null}
      </div>

      {expanded ? (
        <>
          <div className="flex h-9 items-end border-b border-line-200 bg-bg-sunk px-2" role="tablist">
            {(["events", "logs", "json"] as const).map((value) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={tab === value}
                onClick={() => setTab(value)}
                className={`h-full border-b-2 px-3 text-xs font-medium ${
                  tab === value
                    ? "border-info-fg text-info-fg"
                    : "border-transparent text-ink-400 hover:text-ink-700"
                }`}
              >
                {value === "logs" ? "Operation log" : executionTypeLabel(value)}
              </button>
            ))}
          </div>

          {tab === "events" ? (
            <div className="max-h-72 overflow-auto">
              <table className="w-full min-w-[760px] text-left text-xs">
                <thead className="sticky top-0 bg-bg-sunk text-micro uppercase tracking-wide text-ink-400">
                  <tr>
                    <th className="px-3 py-2 font-medium">Time</th>
                    <th className="px-3 py-2 font-medium">Level</th>
                    <th className="px-3 py-2 font-medium">Event</th>
                    <th className="px-3 py-2 font-medium">Context</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleEvents.map(({ event, id, level: eventLevelValue }) => (
                    <tr
                      key={id}
                      className="cursor-pointer border-t border-line-100 hover:bg-bg-hover"
                      onClick={() => onSelect(id)}
                    >
                      <td className="whitespace-nowrap px-3 py-2 font-mono-data text-micro text-ink-400">
                        {event.event_time ? formatTableDate(event.event_time) : "—"}
                      </td>
                      <td className="px-3 py-2">
                        <span className="inline-flex items-center gap-2 uppercase text-ink-500">
                          <span className={`h-1.5 w-1.5 rounded-full ${levelDot(eventLevelValue)}`} />
                          {eventLevelValue}
                        </span>
                      </td>
                      <td className="px-3 py-2 font-medium text-ink-800">{event.event_type}</td>
                      <td className="max-w-xl truncate px-3 py-2 font-mono-data text-micro text-ink-500">
                        {event.tool_name ??
                          event.model ??
                          event.sdk_operation ??
                          event.mcp_method ??
                          event.span_id ??
                          "execution"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {visibleEvents.length === 0 ? (
                <p className="p-4 text-xs text-ink-400">No events match the current filter.</p>
              ) : null}
            </div>
          ) : null}

          {tab === "logs" ? (
            <div className="max-h-72 overflow-auto">
              <table className="w-full min-w-[820px] text-left text-xs">
                <thead className="sticky top-0 bg-bg-sunk text-micro uppercase tracking-wide text-ink-400">
                  <tr>
                    <th className="px-3 py-2 font-medium">Started</th>
                    <th className="px-3 py-2 font-medium">Type</th>
                    <th className="px-3 py-2 font-medium">Operation</th>
                    <th className="px-3 py-2 font-medium">Outcome</th>
                    <th className="px-3 py-2 text-right font-medium">Duration</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleOperations.map((observation) => (
                    <tr
                      key={observation.span_id}
                      className="cursor-pointer border-t border-line-100 hover:bg-bg-hover"
                      onClick={() => onSelect(observation.span_id)}
                    >
                      <td className="whitespace-nowrap px-3 py-2 font-mono-data text-micro text-ink-400">
                        {observation.start_time ? formatTableDate(observation.start_time) : "—"}
                      </td>
                      <td className="px-3 py-2 uppercase text-ink-400">
                        {executionTypeLabel(
                          observation.observation_type ?? observation.kind ?? "operation",
                        )}
                      </td>
                      <td className="px-3 py-2 font-medium text-ink-800">
                        {observation.operation_name}
                      </td>
                      <td className="px-3 py-2 text-ink-500">
                        {executionTypeLabel(observation.outcome ?? "unknown")}
                      </td>
                      <td className="px-3 py-2 text-right font-mono-data text-ink-500">
                        {formatDuration(observation.duration_ms)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {visibleOperations.length === 0 ? (
                <p className="p-4 text-xs text-ink-400">No operations match the current filter.</p>
              ) : null}
            </div>
          ) : null}

          {tab === "json" ? (
            <div className="max-h-80 overflow-auto bg-[#fbfcfd] p-3">
              <p className="mb-2 text-micro text-ink-400">
                {selectedItem
                  ? `Selected ${executionTypeLabel(selectedItem.type)} metadata`
                  : "Execution metadata"}
                . Protected prompt and output content remains lazy-loaded in the inspector.
              </p>
              <pre className="whitespace-pre-wrap break-words font-mono text-[11px] leading-5 text-ink-700">
                {JSON.stringify(rawValue, null, 2)}
              </pre>
            </div>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
