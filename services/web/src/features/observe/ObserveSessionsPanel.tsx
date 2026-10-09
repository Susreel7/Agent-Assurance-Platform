import { Link, useSearchParams } from "react-router-dom";
import { useObserveSessions } from "@/api/suiteQueries";
import { useSuiteProject } from "@/features/suite/useSuiteProject";
import { ErrorState } from "@/components/ErrorState";
import { Skeleton } from "@/components/Skeleton";
import {
  NexusBadge,
  NexusCard,
  NexusPageHeader,
} from "@/components/NexusUI";
import { formatTableDate } from "@/lib/dates";
import {
  executionTypeLabel,
  formatDuration,
  normalizeExecutionStatus,
} from "./executionGraphModel";

export default function ObserveSessionsPanel() {
  const { projectId } = useSuiteProject();
  const [search, setSearch] = useSearchParams();
  const user = search.get("user") ?? "";
  const query = useObserveSessions(projectId, {
    limit: "100",
    ...(user.trim() ? { initiating_user_id: user.trim() } : {}),
  });
  const sessions = query.data?.items ?? [];

  if (query.isLoading) return <Skeleton height="12rem" />;

  if (query.isError) {
    return (
      <ErrorState
        message={query.error instanceof Error ? query.error.message : "Could not load sessions"}
        onRetry={() => void query.refetch()}
      />
    );
  }

  return (
    <div className="space-y-6">
      <NexusPageHeader
        crumbs={["Activity", "Sessions"]}
        title="Sessions"
        lede="A session groups a person's related executions and traces. Open one session to follow its complete execution history and underlying distributed traces."
      />
      <NexusCard pad>
        <label className="block max-w-xl">
          <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-500">
            Initiating user ID
          </span>
          <input
            value={user}
            onChange={(event) => {
              const next = new URLSearchParams(search);
              if (event.target.value.trim()) next.set("user", event.target.value);
              else next.delete("user");
              setSearch(next, { replace: true });
            }}
            placeholder="All users"
            className="glass-input h-9 w-full rounded-xl px-3 text-xs outline-none"
          />
        </label>
      </NexusCard>
      <NexusCard className="overflow-x-auto">
        <table className="min-w-[1040px] text-left">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50/70 dark:border-white/10 dark:bg-white/[0.02]">
              {["Session", "User", "Runs / traces", "Observed work", "Issues", "Duration", "Last seen", "Status"].map(
                (heading) => (
                  <th key={heading} className="px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-slate-500">
                    {heading}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 dark:divide-white/5">
            {sessions.map((session) => {
              const status = normalizeExecutionStatus(session.status);
              const tone =
                status === "succeeded"
                  ? "ok"
                  : status === "failed"
                    ? "risk"
                    : status === "running"
                      ? "info"
                      : "default";
              return (
                <tr key={session.session_id} className="transition-colors hover:bg-slate-50 dark:hover:bg-white/[0.03]">
                  <td className="px-4 py-3">
                    <Link
                      to={`/observe/sessions/${encodeURIComponent(session.session_id)}`}
                      className="block text-sm font-bold text-slate-900 hover:text-indigo-600 dark:text-white dark:hover:text-cyan-400"
                    >
                      {session.display_name ?? "Agent session"}
                    </Link>
                    <span className="block max-w-64 truncate font-mono text-[10px] text-slate-500">
                      {session.session_id}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-700 dark:text-slate-300">
                    {session.initiating_user_id ?? "Unattributed"}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-500">
                    {session.execution_count} / {session.trace_count}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-xs text-slate-500">
                    {session.node_count} nodes · {session.generation_count} LLM ·{" "}
                    {session.tool_count} tools · {session.sdk_count} SDK
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-xs text-slate-500">
                    {session.error_count} errors · {session.retry_count} retries
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap font-mono text-xs text-slate-500">
                    {formatDuration(session.duration_ms)}
                  </td>
                  <td className="px-4 py-3 whitespace-nowrap text-xs text-slate-500">
                    {session.last_seen_at ? formatTableDate(session.last_seen_at) : "—"}
                  </td>
                  <td className="px-4 py-3">
                    <NexusBadge tone={tone}>{executionTypeLabel(status)}</NexusBadge>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {sessions.length === 0 ? (
          <p className="p-8 text-center text-sm text-slate-500">
            No sessions match this user.
          </p>
        ) : null}
      </NexusCard>
    </div>
  );
}
