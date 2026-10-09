import { Link, useSearchParams } from "react-router-dom";
import Filter from "lucide-react/dist/esm/icons/filter";
import RotateCcw from "lucide-react/dist/esm/icons/rotate-ccw";
import { useObserveExecutions } from "@/api/suiteQueries";
import type { ExecutionSummary } from "@/api/types";
import { ErrorState } from "@/components/ErrorState";
import {
  NexusBadge,
  NexusCard,
  NexusPageHeader,
} from "@/components/NexusUI";
import { formatTableDate } from "@/lib/dates";
import { useSuiteProject } from "@/features/suite/useSuiteProject";
import {
  executionTypeLabel,
  formatDuration,
  normalizeExecutionStatus,
} from "./executionGraphModel";

function tone(
  execution: ExecutionSummary,
): "ok" | "warn" | "risk" | "info" | "default" {
  const status = normalizeExecutionStatus(execution.status);
  if (status === "succeeded") return "ok";
  if (status === "failed") return "risk";
  if (status === "running") return "info";
  if (status === "retry" || status === "waiting") return "warn";
  return "default";
}

export default function ObserveExecutionsPanel() {
  const { projectId } = useSuiteProject();
  const [search, setSearch] = useSearchParams();
  const user = search.get("user") ?? "";
  const status = search.get("status") ?? "";
  const setFilter = (key: "user" | "status", value: string) => {
    const next = new URLSearchParams(search);
    if (value.trim()) next.set(key, value);
    else next.delete(key);
    setSearch(next, { replace: true });
  };
  const query = useObserveExecutions(projectId, {
    limit: "100",
    ...(user.trim() ? { initiating_user_id: user.trim() } : {}),
    ...(status ? { status } : {}),
  });
  const rows = query.data?.items ?? [];

  return (
    <div className="space-y-6">
      <NexusPageHeader
        crumbs={["Activity", "Executions"]}
        title="Executions"
        lede="Every recorded agent invocation. Select a row to open its live graph, call tree, swimlanes, waterfall, events, and protected payload metadata."
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
          <label className="w-44">
            <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-500">
              Status
            </span>
            <select
              value={status}
              onChange={(event) => setFilter("status", event.target.value)}
              className="glass-input h-9 w-full rounded-xl px-3 text-xs outline-none"
            >
              <option value="">All statuses</option>
              <option value="running">Running</option>
              <option value="succeeded">Succeeded</option>
              <option value="failed">Failed</option>
              <option value="partial">Partial</option>
            </select>
          </label>
          <button
            type="button"
            onClick={() => void query.refetch()}
            className="glass-button flex h-9 items-center gap-2 rounded-xl px-3 text-xs font-semibold"
          >
            <Filter size={13} />
            Refresh
          </button>
          <button
            type="button"
            onClick={() => setSearch({}, { replace: true })}
            className="glass-button flex h-9 items-center gap-2 rounded-xl px-3 text-xs font-semibold"
          >
            <RotateCcw size={13} />
            Clear
          </button>
        </div>
      </NexusCard>

      {query.isError ? (
        <ErrorState
          message={query.error instanceof Error ? query.error.message : "Could not load executions"}
          onRetry={() => void query.refetch()}
        />
      ) : (
        <NexusCard className="overflow-x-auto">
          <table className="min-w-[1120px] text-left">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50/70 dark:border-white/10 dark:bg-white/[0.02]">
                {[
                  "Execution",
                  "Session",
                  "Initiated by",
                  "Effective actor",
                  "Source",
                  "Observed work",
                  "Started",
                  "Duration",
                  "Status",
                ].map((heading) => (
                  <th
                    key={heading}
                    className="px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-slate-500"
                  >
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-white/5">
              {rows.map((execution) => (
                <tr
                  key={execution.execution_id}
                  className="transition-colors hover:bg-slate-50 dark:hover:bg-white/[0.03]"
                >
                  <td className="px-4 py-3">
                    <Link
                      to={`/observe/executions/${encodeURIComponent(execution.execution_id)}`}
                      className="block text-sm font-bold text-slate-900 hover:text-indigo-600 dark:text-white dark:hover:text-cyan-400"
                    >
                      {execution.agent_name ??
                        executionTypeLabel(execution.execution_type ?? "execution")}
                    </Link>
                    <span className="block max-w-56 truncate font-mono text-[10px] text-slate-500">
                      {execution.execution_id}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    {execution.session_id ? (
                      <Link
                        to={`/observe/sessions/${encodeURIComponent(execution.session_id)}`}
                        className="font-mono text-xs text-indigo-600 hover:underline dark:text-cyan-400"
                      >
                        {execution.session_id}
                      </Link>
                    ) : (
                      <span className="text-xs text-slate-400">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-700 dark:text-slate-300">
                    {execution.initiating_user_id ?? "Unattributed"}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-500">
                    {execution.effective_actor_id ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {[execution.invocation_source, execution.client_name]
                      .filter(Boolean)
                      .join(" · ") || "—"}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-xs text-slate-500">
                    {execution.node_count} nodes · {execution.generation_count} LLM ·{" "}
                    {execution.tool_count} tools · {execution.mcp_tool_count} MCP
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-xs text-slate-500">
                    {execution.start_time ? formatTableDate(execution.start_time) : "—"}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap font-mono text-xs text-slate-500">
                    {formatDuration(execution.duration_ms)}
                  </td>
                  <td className="px-4 py-3">
                    <NexusBadge tone={tone(execution)}>
                      {executionTypeLabel(normalizeExecutionStatus(execution.status))}
                    </NexusBadge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!query.isPending && rows.length === 0 ? (
            <p className="p-8 text-center text-sm text-slate-500">
              No executions match these filters.
            </p>
          ) : null}
        </NexusCard>
      )}
    </div>
  );
}
