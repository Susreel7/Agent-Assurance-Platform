import { useMemo, useState } from "react";
import { Badge } from "@/components/StateBadge";
import {
  executionTypeLabel,
  formatDuration,
  type ExecutionGraphItem,
  type ExecutionVisualStatus,
} from "./executionGraphModel";
import { analyzeExecutionTimeline, type TimelineSpan } from "./executionTimelineModel";

type Props = {
  items: ExecutionGraphItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
};

const barClass: Record<ExecutionVisualStatus, string> = {
  queued: "bg-mute-solid/50",
  running: "bg-info-solid",
  succeeded: "bg-ink-500",
  failed: "bg-risk-solid",
  skipped: "bg-mute-solid/40",
  retry: "bg-warn-solid",
  waiting: "bg-warn-solid/60",
  unknown: "bg-ink-300",
};

function position(time: number, start: number, duration: number): number {
  return duration > 0 ? ((time - start) / duration) * 100 : 0;
}

function TimelineMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="border-r border-line-200 px-3 py-2 last:border-r-0">
      <p className="text-micro uppercase tracking-wide text-ink-400">{label}</p>
      <p className="mt-0.5 font-mono-data text-xs font-semibold text-ink-900">{value}</p>
    </div>
  );
}

function Bar({
  span,
  startMs,
  durationMs,
  selected,
  highlightCritical,
  onSelect,
}: {
  span: TimelineSpan;
  startMs: number;
  durationMs: number;
  selected: boolean;
  highlightCritical: boolean;
  onSelect: (id: string) => void;
}) {
  const left = position(span.startMs, startMs, durationMs);
  const width = Math.max((span.durationMs / Math.max(durationMs, 1)) * 100, 0.25);
  const faded = highlightCritical && !span.isCritical;
  return (
    <button
      type="button"
      className={`absolute top-1/2 h-3 -translate-y-1/2 border transition-opacity ${
        barClass[span.status]
      } ${
        selected
          ? "z-20 border-info-fg ring-2 ring-info-fg/20"
          : span.isCritical
            ? "z-10 border-ink-900"
            : "border-transparent"
      } ${faded ? "opacity-20" : "opacity-90 hover:opacity-100"}`}
      style={{ left: `${left}%`, width: `${width}%` }}
      onClick={() => onSelect(span.id)}
      title={`${span.label} · ${formatDuration(span.durationMs)} · self ${formatDuration(span.selfMs)}`}
      aria-label={`Inspect ${span.label}`}
    />
  );
}

export function ExecutionTimeline({ items, selectedId, onSelect }: Props) {
  const [criticalOnly, setCriticalOnly] = useState(false);
  const [query, setQuery] = useState("");
  const observations = useMemo(
    () => items.flatMap((item) => (item.observation ? [item.observation] : [])),
    [items],
  );
  const events = useMemo(
    () => items.filter((item) => item.source === "event" && item.startTime),
    [items],
  );
  const analysis = useMemo(() => analyzeExecutionTimeline(observations), [observations]);
  const normalizedQuery = query.trim().toLowerCase();
  const visibleSpans = analysis.spans.filter(
    (span) =>
      (!criticalOnly || span.isCritical) &&
      (!normalizedQuery ||
        span.label.toLowerCase().includes(normalizedQuery) ||
        span.type.includes(normalizedQuery)),
  );
  const bottlenecks = analysis.spans.filter((span) => span.selfMs > 0);
  bottlenecks.sort((left, right) => right.selfMs - left.selfMs);
  const topBottlenecks = bottlenecks.slice(0, 3);

  if (analysis.spans.length === 0) {
    return <p className="p-6 text-xs text-ink-400">No timed observations are available.</p>;
  }

  return (
    <div className="h-full min-h-0 overflow-auto">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line-200 px-3 py-2">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Filter timeline…"
            aria-label="Filter execution timeline"
            className="h-7 w-48 border border-line-200 bg-bg-panel px-2 text-xs outline-none focus:border-info-fg"
          />
          <button
            type="button"
            aria-pressed={criticalOnly}
            onClick={() => setCriticalOnly((value) => !value)}
            className={`h-7 border px-2 text-xs ${
              criticalOnly
                ? "border-info-fg bg-info-bg text-info-fg"
                : "border-line-200 text-ink-500 hover:bg-bg-hover"
            }`}
          >
            Estimated critical path
          </button>
        </div>
        <span
          className="text-micro text-ink-400"
          title="The path is inferred from parentage and timing. Explicit causal links improve accuracy."
        >
          timing-derived · {analysis.maxParallelism}× peak concurrency
        </span>
      </div>

      <div className="flex overflow-x-auto border-b border-line-200 bg-bg-sunk">
        <TimelineMetric label="Elapsed" value={formatDuration(analysis.durationMs)} />
        <TimelineMetric label="Critical path" value={`≈ ${formatDuration(analysis.criticalPathMs)}`} />
        <TimelineMetric label="Observed work" value={formatDuration(analysis.observedMs)} />
        <TimelineMetric label="Peak concurrency" value={`${analysis.maxParallelism}×`} />
      </div>

      <div className="grid grid-cols-1 border-b border-line-200 lg:grid-cols-[minmax(0,1fr)_240px]">
        <div className="min-w-0 overflow-auto">
          <div className="min-w-[920px]">
            <div className="grid h-8 grid-cols-[220px_minmax(680px,1fr)] border-b border-line-200 bg-bg-sunk">
              <div className="border-r border-line-200 px-3 py-2 text-micro uppercase tracking-wide text-ink-400">
                Operation
              </div>
              <div className="relative">
                {[0, 25, 50, 75, 100].map((tick) => (
                  <div
                    key={tick}
                    className="absolute inset-y-0 border-l border-line-200"
                    style={{ left: `${tick}%` }}
                  >
                    <span className="ml-1 font-mono-data text-micro text-ink-400">
                      {formatDuration((analysis.durationMs * tick) / 100)}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {events.length > 0 ? (
              <div className="grid h-8 grid-cols-[220px_minmax(680px,1fr)] border-b border-line-200 bg-bg-panel">
                <div className="border-r border-line-200 px-3 py-2 text-micro text-ink-400">
                  Events ({events.length})
                </div>
                <div className="relative bg-[linear-gradient(to_right,var(--tw-gradient-stops))]">
                  {events.map((event) => {
                    const eventMs = Date.parse(event.startTime ?? "");
                    if (!Number.isFinite(eventMs)) return null;
                    return (
                      <button
                        key={event.id}
                        type="button"
                        className={`absolute top-1 h-6 w-px ${
                          event.status === "failed"
                            ? "bg-risk-solid"
                            : event.status === "retry"
                              ? "bg-warn-solid"
                              : "bg-info-solid"
                        }`}
                        style={{
                          left: `${position(eventMs, analysis.startMs, analysis.durationMs)}%`,
                        }}
                        onClick={() => onSelect(event.id)}
                        title={event.label}
                        aria-label={`Inspect event ${event.label}`}
                      />
                    );
                  })}
                </div>
              </div>
            ) : null}

            {visibleSpans.map((span) => (
              <div
                key={span.id}
                className={`grid h-8 grid-cols-[220px_minmax(680px,1fr)] border-b border-line-100 ${
                  selectedId === span.id ? "bg-info-bg" : "bg-bg-panel hover:bg-bg-hover"
                }`}
              >
                <button
                  type="button"
                  className="flex min-w-0 items-center gap-2 border-r border-line-200 px-2 text-left"
                  style={{ paddingLeft: `${8 + Math.min(span.depth, 8) * 10}px` }}
                  onClick={() => onSelect(span.id)}
                >
                  <span
                    className={`h-1.5 w-1.5 shrink-0 rounded-full ${barClass[span.status]}`}
                  />
                  <span className="min-w-0 flex-1 truncate text-xs text-ink-700">
                    {span.label}
                  </span>
                  <span className="shrink-0 font-mono-data text-micro text-ink-400">
                    {formatDuration(span.durationMs)}
                  </span>
                </button>
                <div className="relative">
                  {[0, 25, 50, 75, 100].map((tick) => (
                    <span
                      key={tick}
                      className="absolute inset-y-0 border-l border-line-100"
                      style={{ left: `${tick}%` }}
                    />
                  ))}
                  <Bar
                    span={span}
                    startMs={analysis.startMs}
                    durationMs={analysis.durationMs}
                    selected={selectedId === span.id}
                    highlightCritical={criticalOnly}
                    onSelect={onSelect}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>

        <aside className="border-t border-line-200 bg-bg-panel p-3 lg:border-l lg:border-t-0">
          <p className="text-xs font-semibold text-ink-900">Latency contributors</p>
          <p className="mt-1 text-micro leading-4 text-ink-400">
            Self time excludes direct child coverage. Nested and parallel work is not double-counted.
          </p>
          <div className="mt-3 space-y-2">
            {topBottlenecks.map((span, index) => (
              <button
                key={span.id}
                type="button"
                onClick={() => onSelect(span.id)}
                className="block w-full border border-line-200 p-2 text-left hover:bg-bg-hover"
              >
                <div className="flex items-center gap-2">
                  <span className="font-mono-data text-micro text-ink-400">{index + 1}</span>
                  <span className="min-w-0 flex-1 truncate text-xs font-medium text-ink-800">
                    {span.label}
                  </span>
                  {span.isCritical ? <Badge label="Path" tone="info" /> : null}
                </div>
                <div className="mt-1 flex justify-between text-micro text-ink-400">
                  <span>{executionTypeLabel(span.type)}</span>
                  <span className="font-mono-data">{formatDuration(span.selfMs)} self</span>
                </div>
              </button>
            ))}
          </div>
          {analysis.omittedCount > 0 ? (
            <p className="mt-3 text-micro text-warn-fg">
              {analysis.omittedCount} operation(s) omitted because start time was unavailable.
            </p>
          ) : null}
        </aside>
      </div>
    </div>
  );
}
