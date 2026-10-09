/** Live Activity overview. Every value comes from Observe; there are no UI fixtures. */

import ArrowRight from "lucide-react/dist/esm/icons/arrow-right";
import Radio from "lucide-react/dist/esm/icons/radio";
import { useNavigate } from "react-router-dom";
import {
  useObserveAnalytics,
  useObserveExecutions,
  useObserveSessions,
} from "@/api/suiteQueries";
import type { ExecutionSummary } from "@/api/types";
import { ErrorState } from "@/components/ErrorState";
import {
  NexusBadge,
  NexusCard,
  NexusMetric,
  NexusPageHeader,
} from "@/components/NexusUI";
import { formatTableDate } from "@/lib/dates";
import { useSuiteProject } from "@/features/suite/useSuiteProject";
import {
  executionTypeLabel,
  formatDuration,
  normalizeExecutionStatus,
} from "./executionGraphModel";

function money(micros: number): string {
  return `$${(micros / 1_000_000).toFixed(2)}`;
}

function statusTone(
  execution: ExecutionSummary,
): "ok" | "warn" | "risk" | "info" | "default" {
  const status = normalizeExecutionStatus(execution.status);
  if (status === "succeeded") return "ok";
  if (status === "failed") return "risk";
  if (status === "running") return "info";
  if (status === "retry" || status === "waiting") return "warn";
  return "default";
}

export default function ObserveTracesPanel() {
  const navigate = useNavigate();
  const { projectId } = useSuiteProject();
  const analytics = useObserveAnalytics(projectId);
  const executions = useObserveExecutions(projectId, { limit: "8" });
  const sessions = useObserveSessions(projectId, { limit: "50" });

  if (analytics.isError && executions.isError && sessions.isError) {
    return (
      <ErrorState
        title="Activity is unavailable"
        message={
          analytics.error instanceof Error
            ? analytics.error.message
            : "Observe did not return activity data."
        }
        onRetry={() => {
          void analytics.refetch();
          void executions.refetch();
          void sessions.refetch();
        }}
      />
    );
  }

  const metrics = analytics.data;
  const recent = executions.data?.items ?? [];
  const topUsers = metrics?.by_user?.slice(0, 5) ?? [];
  const topTools = metrics?.by_tool?.slice(0, 5) ?? [];
  const breakdowns = [
    { title: "Most active people", rows: topUsers },
    { title: "Most called tools", rows: topTools },
  ];

  return (
    <div className="space-y-6">
      <NexusPageHeader
        crumbs={["Activity", "Overview"]}
        title="Activity overview"
        lede="Live, tenant-scoped executions recorded by Observe. Initiating people, effective actors, model calls, and tool calls remain attributable."
        actions={
          <button
            type="button"
            onClick={() => navigate("/observe/live")}
            className="glass-button-primary flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-bold"
          >
            <Radio size={14} />
            Live activity
          </button>
        }
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <NexusMetric
          label="Executions"
          value={analytics.isPending ? "—" : String(metrics?.execution_count ?? 0)}
          meta={`${metrics?.agent_count ?? 0} agents · ${metrics?.success_count ?? 0} succeeded`}
        />
        <NexusMetric
          label="Sessions"
          value={sessions.isPending ? "—" : String(sessions.data?.total ?? 0)}
          meta={`${metrics?.user_count ?? 0} initiating users`}
        />
        <NexusMetric
          label="Observed tool calls"
          value={analytics.isPending ? "—" : String(metrics?.by_tool?.reduce((n, row) => n + row.count, 0) ?? 0)}
          meta={`${metrics?.by_mcp?.length ?? 0} MCP servers observed`}
        />
        <NexusMetric
          label="Attributed cost"
          value={analytics.isPending ? "—" : money(metrics?.total_cost_micros ?? 0)}
          meta={`${(metrics?.input_tokens ?? 0).toLocaleString()} input · ${(metrics?.output_tokens ?? 0).toLocaleString()} output tokens`}
          tone={(metrics?.failed_count ?? 0) > 0 ? "negative" : "default"}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {breakdowns.map(({ title, rows }) => (
          <NexusCard key={title}>
            <div className="border-b border-slate-200 px-5 py-4 dark:border-white/10">
              <h2 className="text-sm font-bold text-slate-900 dark:text-white">{title}</h2>
            </div>
            <div className="divide-y divide-slate-200 dark:divide-white/5">
              {rows.map((row) => (
                <div key={row.label} className="flex items-center justify-between px-5 py-3">
                  <span className="min-w-0 truncate text-xs font-semibold text-slate-800 dark:text-slate-200">
                    {row.label}
                  </span>
                  <span className="font-mono text-xs text-slate-500">{row.count}</span>
                </div>
              ))}
              {rows.length === 0 ? (
                <p className="px-5 py-6 text-xs text-slate-500">No observed activity.</p>
              ) : null}
            </div>
          </NexusCard>
        ))}
      </div>

      <div>
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-base font-bold text-slate-900 dark:text-white">
            Recent executions
          </h2>
          <button
            type="button"
            onClick={() => navigate("/observe/executions")}
            className="flex items-center gap-1.5 text-xs font-semibold text-indigo-600 dark:text-cyan-400"
          >
            All executions <ArrowRight size={13} />
          </button>
        </div>

        <NexusCard className="overflow-x-auto">
          <table className="min-w-[940px] text-left">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50/70 dark:border-white/10 dark:bg-white/[0.02]">
                {["Execution", "Initiating user", "Effective actor", "Observed work", "Started", "Duration", "Status"].map(
                  (heading) => (
                    <th key={heading} className="px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-slate-500">
                      {heading}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-white/5">
              {recent.map((execution) => (
                <tr
                  key={execution.execution_id}
                  className="cursor-pointer transition-colors hover:bg-slate-50 dark:hover:bg-white/[0.04]"
                  onClick={() =>
                    navigate(`/observe/executions/${encodeURIComponent(execution.execution_id)}`)
                  }
                >
                  <td className="px-4 py-3">
                    <div className="text-sm font-bold text-slate-900 dark:text-white">
                      {execution.agent_name ?? executionTypeLabel(execution.execution_type ?? "execution")}
                    </div>
                    <div className="max-w-56 truncate font-mono text-[10px] text-slate-500">
                      {execution.execution_id}
                    </div>
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-700 dark:text-slate-300">
                    {execution.initiating_user_id ?? "Unattributed"}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-500">
                    {execution.effective_actor_id ?? "—"}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {execution.generation_count} LLM · {execution.tool_count} tools · {execution.mcp_tool_count} MCP
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {execution.start_time ? formatTableDate(execution.start_time) : "—"}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-500">
                    {formatDuration(execution.duration_ms)}
                  </td>
                  <td className="px-4 py-3">
                    <NexusBadge tone={statusTone(execution)}>
                      {executionTypeLabel(normalizeExecutionStatus(execution.status))}
                    </NexusBadge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!executions.isPending && recent.length === 0 ? (
            <p className="p-8 text-center text-sm text-slate-500">No executions recorded.</p>
          ) : null}
        </NexusCard>
      </div>
    </div>
  );
}
