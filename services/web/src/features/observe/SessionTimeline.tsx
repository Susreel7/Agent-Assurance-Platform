import { Link } from "react-router-dom";
import type { ExecutionSummary } from "@/api/types";
import { formatDuration, normalizeExecutionStatus } from "./executionGraphModel";

type TimedExecution = {
  execution: ExecutionSummary;
  startMs: number;
  endMs: number;
};

function statusClass(status?: string | null): string {
  const normalized = normalizeExecutionStatus(status);
  if (normalized === "failed") return "bg-risk-solid";
  if (normalized === "running") return "bg-info-solid";
  if (normalized === "retry" || normalized === "waiting") return "bg-warn-solid";
  if (normalized === "succeeded") return "bg-ink-500";
  return "bg-mute-solid";
}

export function SessionTimeline({ executions }: { executions: ExecutionSummary[] }) {
  const timed = executions.flatMap<TimedExecution>((execution) => {
      if (!execution.start_time) return [];
      const startMs = Date.parse(execution.start_time);
      if (!Number.isFinite(startMs)) return [];
      const parsedEnd = execution.end_time ? Date.parse(execution.end_time) : Number.NaN;
      const endMs = Number.isFinite(parsedEnd)
        ? parsedEnd
        : startMs + Math.max(0, execution.duration_ms ?? 0);
      return [{ execution, startMs, endMs: Math.max(startMs, endMs) }];
    });
  timed.sort((left, right) => left.startMs - right.startMs);
  if (timed.length === 0) return null;

  const startMs = Math.min(...timed.map((item) => item.startMs));
  const endMs = Math.max(...timed.map((item) => item.endMs));
  const durationMs = Math.max(1, endMs - startMs);

  return (
    <div className="border-b border-line-200">
      <div className="grid h-8 min-w-[760px] grid-cols-[220px_minmax(520px,1fr)] border-b border-line-200 bg-bg-sunk">
        <div className="border-r border-line-200 px-4 py-2 text-micro uppercase tracking-wide text-ink-400">
          Session timeline
        </div>
        <div className="relative">
          {[0, 25, 50, 75, 100].map((tick) => (
            <div
              key={tick}
              className="absolute inset-y-0 border-l border-line-200"
              style={{ left: `${tick}%` }}
            >
              <span className="ml-1 font-mono-data text-micro text-ink-400">
                {formatDuration((durationMs * tick) / 100)}
              </span>
            </div>
          ))}
        </div>
      </div>
      <div className="max-h-64 min-w-[760px] overflow-y-auto">
        {timed.map(({ execution, startMs: executionStart, endMs: executionEnd }) => {
          const left = ((executionStart - startMs) / durationMs) * 100;
          const width = Math.max(((executionEnd - executionStart) / durationMs) * 100, 0.35);
          return (
            <div
              key={execution.execution_id}
              className="grid h-8 grid-cols-[220px_minmax(520px,1fr)] border-b border-line-100 bg-bg-panel last:border-b-0"
            >
              <Link
                to={`/observe/executions/${encodeURIComponent(execution.execution_id)}`}
                className="flex min-w-0 items-center gap-2 border-r border-line-200 px-4 hover:bg-bg-hover"
              >
                <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${statusClass(execution.status)}`} />
                <span className="min-w-0 flex-1 truncate text-xs text-ink-700">
                  {execution.agent_name ?? execution.execution_type ?? "Execution"}
                </span>
                <span className="font-mono-data text-micro text-ink-400">
                  {formatDuration(execution.duration_ms)}
                </span>
              </Link>
              <div className="relative">
                {[0, 25, 50, 75, 100].map((tick) => (
                  <span
                    key={tick}
                    className="absolute inset-y-0 border-l border-line-100"
                    style={{ left: `${tick}%` }}
                  />
                ))}
                <Link
                  to={`/observe/executions/${encodeURIComponent(execution.execution_id)}`}
                  className={`absolute top-1/2 h-3 -translate-y-1/2 border border-transparent opacity-90 hover:opacity-100 ${statusClass(execution.status)}`}
                  style={{ left: `${left}%`, width: `${width}%` }}
                  title={`${execution.agent_name ?? "Execution"} · ${formatDuration(execution.duration_ms)}`}
                  aria-label={`Open ${execution.agent_name ?? "execution"}`}
                />
                {execution.replay_of_execution_id ? (
                  <span
                    className="absolute top-0 h-full border-l border-dashed border-warn-solid"
                    style={{ left: `${left}%` }}
                    title="Replay execution"
                  />
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
