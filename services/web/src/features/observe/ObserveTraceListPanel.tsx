import { Link, useSearchParams } from "react-router-dom";
import { useObserveTraces } from "@/api/suiteQueries";
import { ErrorState } from "@/components/ErrorState";
import {
  NexusBadge,
  NexusCard,
  NexusPageHeader,
} from "@/components/NexusUI";
import { formatTableDate } from "@/lib/dates";
import { useSuiteProject } from "@/features/suite/useSuiteProject";

function cost(micros: number | null | undefined): string {
  return micros == null ? "—" : `$${(micros / 1_000_000).toFixed(4)}`;
}

export default function ObserveTraceListPanel() {
  const { projectId } = useSuiteProject();
  const [search, setSearch] = useSearchParams();
  const queryText = search.get("q") ?? "";
  const outcome = search.get("outcome") ?? "";
  const user = search.get("user") ?? "";
  const setFilter = (key: "q" | "outcome" | "user", value: string) => {
    const next = new URLSearchParams(search);
    if (value.trim()) next.set(key, value);
    else next.delete(key);
    setSearch(next, { replace: true });
  };
  const query = useObserveTraces(projectId, {
    limit: "100",
    ...(queryText.trim() ? { query: queryText.trim() } : {}),
    ...(outcome ? { outcome } : {}),
    ...(user.trim() ? { initiating_user_id: user.trim() } : {}),
  });
  const rows = query.data?.items ?? [];

  return (
    <div className="space-y-6">
      <NexusPageHeader
        crumbs={["Activity", "Sessions", "Traces"]}
        title="Traces"
        lede="Raw distributed traces recorded inside execution and session boundaries. Open a trace to inspect its exact spans and parent links."
      />

      <NexusCard pad>
        <div className="flex flex-wrap items-end gap-3">
          <label className="min-w-56 flex-1">
            <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-500">
              Initiating user ID
            </span>
            <input
              value={user}
              onChange={(event) => setFilter("user", event.target.value)}
              placeholder="All users"
              className="glass-input h-9 w-full rounded-xl px-3 text-xs outline-none"
            />
          </label>
          <label className="min-w-64 flex-[2]">
            <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-500">
              Search operation, model, tool, or agent
            </span>
            <input
              value={queryText}
              onChange={(event) => setFilter("q", event.target.value)}
              placeholder="Search recorded trace metadata"
              className="glass-input h-9 w-full rounded-xl px-3 text-xs outline-none"
            />
          </label>
          <label className="w-44">
            <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-500">
              Outcome
            </span>
            <select
              value={outcome}
              onChange={(event) => setFilter("outcome", event.target.value)}
              className="glass-input h-9 w-full rounded-xl px-3 text-xs outline-none"
            >
              <option value="">All outcomes</option>
              <option value="success">Success</option>
              <option value="error">Error</option>
            </select>
          </label>
        </div>
      </NexusCard>

      {query.isError ? (
        <ErrorState
          message={query.error instanceof Error ? query.error.message : "Could not load traces"}
          onRetry={() => void query.refetch()}
        />
      ) : (
        <NexusCard className="overflow-x-auto">
          <table className="min-w-[920px] text-left">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50/70 dark:border-white/10 dark:bg-white/[0.02]">
                {["Trace", "Session", "Service / agent", "Spans", "Started", "Ended", "Cost", "Outcome"].map(
                  (heading) => (
                    <th
                      key={heading}
                      className="px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-slate-500"
                    >
                      {heading}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-white/5">
              {rows.map((trace) => (
                <tr
                  key={trace.trace_id}
                  className="transition-colors hover:bg-slate-50 dark:hover:bg-white/[0.03]"
                >
                  <td className="px-4 py-3">
                    <Link
                      to={`/observe/traces/${encodeURIComponent(trace.trace_id)}`}
                      className="font-mono text-xs font-semibold text-indigo-600 hover:underline dark:text-cyan-400"
                    >
                      {trace.trace_id}
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    {trace.session_id ? (
                      <Link
                        to={`/observe/sessions/${encodeURIComponent(trace.session_id)}`}
                        className="font-mono text-xs text-slate-600 hover:underline dark:text-slate-300"
                      >
                        {trace.session_id}
                      </Link>
                    ) : (
                      <span className="text-xs text-slate-400">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-700 dark:text-slate-300">
                    {[trace.service_name, trace.agent_id].filter(Boolean).join(" · ") || "—"}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-500">
                    {trace.span_count}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-xs text-slate-500">
                    {trace.start_time ? formatTableDate(trace.start_time) : "—"}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-xs text-slate-500">
                    {trace.end_time ? formatTableDate(trace.end_time) : "—"}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-500">
                    {cost(trace.total_cost_micros)}
                  </td>
                  <td className="px-4 py-3">
                    <NexusBadge tone={trace.outcome === "error" ? "risk" : "ok"}>
                      {trace.outcome ?? "unknown"}
                    </NexusBadge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!query.isPending && rows.length === 0 ? (
            <p className="p-8 text-center text-sm text-slate-500">No traces recorded.</p>
          ) : null}
        </NexusCard>
      )}
    </div>
  );
}
