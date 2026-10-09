import { useMemo } from "react";
import {
  executionTypeLabel,
  formatDuration,
  type ExecutionGraphItem,
  type ExecutionVisualStatus,
} from "./executionGraphModel";

type Props = {
  items: ExecutionGraphItem[];
  selectedId: string | null;
  onSelect: (id: string) => void;
};

const barClass: Record<ExecutionVisualStatus, string> = {
  queued: "bg-slate-400",
  running: "bg-blue-500",
  succeeded: "bg-emerald-500",
  failed: "bg-rose-500",
  skipped: "bg-slate-300",
  retry: "bg-amber-500",
  waiting: "bg-violet-500",
  unknown: "bg-slate-400",
};

function lane(type: string): string {
  if (type === "agent" || type === "chain") return "Agent";
  if (type === "node" || type === "state_transition") return "Workflow";
  if (type === "generation") return "Models";
  if (type === "mcp") return "MCP";
  if (type === "tool" || type === "retrieval" || type === "http" || type === "database") {
    return "Tools & data";
  }
  if (type === "sdk") return "SDK";
  if (type === "human_approval") return "Human approval";
  return "Events";
}

export function ExecutionSwimlanes({ items, selectedId, onSelect }: Props) {
  const model = useMemo(() => {
    const timed = items.flatMap((item) => {
      const start = item.startTime ? Date.parse(item.startTime) : Number.NaN;
      if (!Number.isFinite(start)) return [];
      const duration = Math.max(item.durationMs ?? 1, 1);
      return [{ item, start, end: start + duration }];
    });
    if (timed.length === 0) return null;
    const start = Math.min(...timed.map((row) => row.start));
    const end = Math.max(...timed.map((row) => row.end));
    const duration = Math.max(1, end - start);
    const grouped = new Map<string, typeof timed>();
    for (const row of timed) {
      const key = lane(row.item.type);
      grouped.set(key, [...(grouped.get(key) ?? []), row]);
    }
    return { start, duration, grouped: [...grouped.entries()] };
  }, [items]);

  if (!model) {
    return <p className="p-6 text-xs text-slate-500">No timed spans are available.</p>;
  }

  return (
    <div className="min-w-[900px] overflow-auto">
      <div className="grid h-9 grid-cols-[150px_minmax(720px,1fr)] border-b border-slate-200 bg-slate-50/70 dark:border-white/10 dark:bg-white/[0.02]">
        <div className="border-r border-slate-200 px-3 py-2 text-[10px] font-bold uppercase tracking-wider text-slate-500 dark:border-white/10">
          Lane
        </div>
        <div className="relative">
          {[0, 25, 50, 75, 100].map((tick) => (
            <div
              key={tick}
              className="absolute inset-y-0 border-l border-slate-200 dark:border-white/10"
              style={{ left: `${tick}%` }}
            >
              <span className="ml-1 font-mono text-[9px] text-slate-500">
                {formatDuration((model.duration * tick) / 100)}
              </span>
            </div>
          ))}
        </div>
      </div>
      {model.grouped.map(([name, rows]) => (
        <div
          key={name}
          className="grid min-h-12 grid-cols-[150px_minmax(720px,1fr)] border-b border-slate-200 dark:border-white/5"
        >
          <div className="border-r border-slate-200 px-3 py-4 text-xs font-semibold text-slate-700 dark:border-white/10 dark:text-slate-300">
            {name}
          </div>
          <div className="relative min-h-12">
            {rows.map(({ item, start, end }, index) => {
              const left = ((start - model.start) / model.duration) * 100;
              const width = Math.max(((end - start) / model.duration) * 100, 0.35);
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => onSelect(item.id)}
                  className={`absolute h-2.5 rounded-full ${barClass[item.status]} ${
                    selectedId === item.id ? "ring-2 ring-indigo-500 ring-offset-2 dark:ring-cyan-400 dark:ring-offset-slate-950" : ""
                  }`}
                  style={{
                    left: `${left}%`,
                    width: `${width}%`,
                    top: `${7 + (index % 3) * 11}px`,
                  }}
                  title={`${item.label} · ${executionTypeLabel(item.type)} · ${formatDuration(item.durationMs)}`}
                  aria-label={`Inspect ${item.label}`}
                />
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}
