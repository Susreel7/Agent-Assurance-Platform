import { Link, useParams } from "react-router-dom";
import { useObserveExecutions, useObserveSessionDetail } from "@/api/suiteQueries";
import { useSuiteProject } from "@/features/suite/useSuiteProject";
import { ErrorState } from "@/components/ErrorState";
import {
  NexusBadge,
  NexusCard,
  NexusMetric,
  NexusPageHeader,
} from "@/components/NexusUI";
import { Skeleton } from "@/components/Skeleton";
import { formatTableDate } from "@/lib/dates";
import {
  executionTypeLabel,
  formatDuration,
  normalizeExecutionStatus,
} from "./executionGraphModel";
import { SessionTimeline } from "./SessionTimeline";

export default function ObserveSessionDetailScreen() {
  const { sessionId = "" } = useParams();
  const { projectId } = useSuiteProject();
  const query = useObserveSessionDetail(projectId, sessionId);
  const executionsQuery = useObserveExecutions(projectId, {
    session_id: sessionId,
    limit: "200",
  });

  if (query.isLoading) return <Skeleton height="24rem" />;

  if (query.isError || !query.data) {
    return (
      <ErrorState
        message={query.error instanceof Error ? query.error.message : "Session not found"}
        onRetry={() => void query.refetch()}
      />
    );
  }

  const { session, traces } = query.data;
  const executions = executionsQuery.data?.items ?? [];
  const status = normalizeExecutionStatus(session.status);
  const tone =
    status === "succeeded"
      ? "ok"
      : status === "failed"
        ? "risk"
        : status === "running"
          ? "info"
          : "warn";

  return (
    <div className="space-y-6">
      <NexusPageHeader
        crumbs={["Activity", "Sessions", session.session_id]}
        title={session.display_name ?? "Agent session"}
        lede={`Initiated by ${session.initiating_user_id ?? "an unattributed caller"} · ${session.execution_count} executions · ${session.trace_count} traces`}
        actions={<NexusBadge tone={tone}>{executionTypeLabel(status)}</NexusBadge>}
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <NexusMetric label="Duration" value={formatDuration(session.duration_ms)} meta={`${session.node_count} nodes`} />
        <NexusMetric label="Executions / traces" value={`${session.execution_count} / ${session.trace_count}`} meta={session.session_id} />
        <NexusMetric label="LLM / tools" value={`${session.generation_count} / ${session.tool_count}`} meta={`${session.sdk_count} SDK calls`} />
        <NexusMetric
          label="Issues"
          value={`${session.error_count} / ${session.retry_count}`}
          meta="Errors / retries"
          tone={session.error_count > 0 ? "negative" : "positive"}
        />
      </div>

      <NexusCard pad>
        <dl className="grid gap-4 text-xs sm:grid-cols-3">
          <div>
            <dt className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Initiating user</dt>
            <dd className="mt-1 break-all font-mono text-slate-800 dark:text-slate-200">{session.initiating_user_id ?? "Unattributed"}</dd>
          </div>
          <div>
            <dt className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Started</dt>
            <dd className="mt-1 text-slate-800 dark:text-slate-200">{session.start_time ? formatTableDate(session.start_time) : "—"}</dd>
          </div>
          <div>
            <dt className="text-[10px] font-bold uppercase tracking-wide text-slate-500">Last activity</dt>
            <dd className="mt-1 text-slate-800 dark:text-slate-200">{session.end_time ? formatTableDate(session.end_time) : "—"}</dd>
          </div>
        </dl>
      </NexusCard>

      <NexusCard>
        <div className="border-b border-slate-200 px-5 py-4 dark:border-white/10">
          <h2 className="text-sm font-bold text-slate-900 dark:text-white">Execution history</h2>
          <p className="mt-1 text-xs text-slate-500">Every invocation and replay grouped into this user session.</p>
        </div>
        {executionsQuery.isLoading ? (
          <div className="p-4"><Skeleton height="10rem" /></div>
        ) : executionsQuery.isError ? (
          <div className="p-4">
            <ErrorState
              message={
                executionsQuery.error instanceof Error
                  ? executionsQuery.error.message
                  : "Could not load session executions"
              }
              onRetry={() => void executionsQuery.refetch()}
            />
          </div>
        ) : executions.length > 0 ? (
          <div className="overflow-x-auto">
            <SessionTimeline executions={executions} />
            <table className="min-w-[900px] w-full text-left text-xs">
              <thead className="border-y border-slate-200 bg-slate-50/70 text-[10px] uppercase tracking-wide text-slate-500 dark:border-white/10 dark:bg-white/[0.02]">
                <tr>
                  <th className="px-4 py-2 font-medium">Started</th>
                  <th className="px-4 py-2 font-medium">Agent</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Duration</th>
                  <th className="px-4 py-2 font-medium">Observed work</th>
                  <th className="px-4 py-2 font-medium">Lineage</th>
                </tr>
              </thead>
              <tbody>
                {executions.map((execution) => {
                  const executionStatus = normalizeExecutionStatus(execution.status);
                  const executionTone =
                    executionStatus === "succeeded"
                      ? "ok"
                      : executionStatus === "failed"
                        ? "risk"
                        : executionStatus === "running"
                          ? "info"
                          : "default";
                  return (
                    <tr key={execution.execution_id} className="border-b border-slate-200 hover:bg-slate-50 dark:border-white/5 dark:hover:bg-white/[0.03]">
                      <td className="whitespace-nowrap px-4 py-3 text-slate-500">
                        {execution.start_time ? formatTableDate(execution.start_time) : "—"}
                      </td>
                      <td className="px-4 py-3">
                        <Link
                          to={`/observe/executions/${encodeURIComponent(execution.execution_id)}`}
                          className="font-medium text-slate-900 hover:text-indigo-600 hover:underline dark:text-white dark:hover:text-cyan-400"
                        >
                          {execution.agent_name ?? execution.execution_type ?? "Execution"}
                        </Link>
                        <p className="mt-0.5 font-mono text-[10px] text-slate-500">
                          {execution.execution_id}
                        </p>
                      </td>
                      <td className="px-4 py-3">
                        <NexusBadge tone={executionTone}>{executionTypeLabel(executionStatus)}</NexusBadge>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 font-mono text-slate-500">
                        {formatDuration(execution.duration_ms)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-slate-500">
                        {execution.node_count} nodes · {execution.generation_count} LLM ·{" "}
                        {execution.tool_count} tools · {execution.sdk_count} SDK
                      </td>
                      <td className="px-4 py-3 text-slate-500">
                        {execution.replay_of_execution_id ? (
                          <span title={execution.replay_of_execution_id}>Replay</span>
                        ) : execution.parent_execution_id ? (
                          <span title={execution.parent_execution_id}>Child execution</span>
                        ) : (
                          "Root"
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="p-6 text-xs text-slate-500">No executions are associated with this session.</p>
        )}
      </NexusCard>

      <NexusCard className="overflow-x-auto">
        <div className="border-b border-slate-200 px-5 py-4 dark:border-white/10">
          <h2 className="text-sm font-bold text-slate-900 dark:text-white">Traces</h2>
          <p className="mt-1 text-xs text-slate-500">Distributed traces inside this session; open one for exact span lineage.</p>
        </div>
        {traces.length > 0 ? (
          <table className="min-w-[760px] w-full text-left text-xs">
            <thead className="border-y border-slate-200 bg-slate-50/70 text-[10px] uppercase tracking-wide text-slate-500 dark:border-white/10 dark:bg-white/[0.02]">
              <tr>
                <th className="px-4 py-2 font-medium">Trace</th>
                <th className="px-4 py-2 font-medium">Service / agent</th>
                <th className="px-4 py-2 font-medium">Spans</th>
                <th className="px-4 py-2 font-medium">Started</th>
                <th className="px-4 py-2 font-medium">Outcome</th>
              </tr>
            </thead>
            <tbody>
              {traces.map((trace) => (
                <tr key={trace.trace_id} className="border-b border-slate-200 hover:bg-slate-50 dark:border-white/5 dark:hover:bg-white/[0.03]">
                  <td className="px-4 py-3">
                    <Link
                      to={`/observe/traces/${encodeURIComponent(trace.trace_id)}`}
                      className="font-mono text-xs text-indigo-600 hover:underline dark:text-cyan-400"
                    >
                      {trace.trace_id}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-slate-500">
                    {[trace.service_name, trace.agent_id].filter(Boolean).join(" · ") || "—"}
                  </td>
                  <td className="px-4 py-3 font-mono text-slate-500">{trace.span_count}</td>
                  <td className="px-4 py-3 text-slate-500">
                    {trace.start_time ? formatTableDate(trace.start_time) : "—"}
                  </td>
                  <td className="px-4 py-3"><NexusBadge tone={trace.outcome === "error" ? "risk" : "ok"}>{trace.outcome ?? "unknown"}</NexusBadge></td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="p-6 text-xs text-slate-500">No traces are associated with this session.</p>
        )}
      </NexusCard>
    </div>
  );
}
