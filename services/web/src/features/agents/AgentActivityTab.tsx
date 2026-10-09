/**
 * One agent's activity: what it ran, what it cost, what it called.
 *
 * The same aggregates as the overview, computed by the same SQL with an agent predicate
 * added. That matters more than it sounds: a detail page that derives its numbers
 * separately from the dashboard it was opened from will eventually disagree with it,
 * and the first person to notice stops trusting both.
 *
 * The MCP list is here rather than only on the estate-wide tools screen because the
 * question "what is this agent talking to, and was it allowed to" is asked about one
 * agent at a time — usually the one somebody has just been paged about.
 */

import { Link } from "react-router-dom";
import { useAgentOperations } from "@/api/queries";
import { ErrorState } from "@/components/ErrorState";
import { Icon } from "@/components/Icon";
import { Panel } from "@/components/Panel";
import { RelativeTime } from "@/components/RelativeTime";
import { Skeleton } from "@/components/Skeleton";
import { Stat } from "@/components/Stat";
import { AreaChart } from "@/components/charts/AreaChart";
import { BarList } from "@/components/charts/BarList";
import { Badge, RunOutcomeBadge } from "@/components/StateBadge";
import { formatDay } from "@/lib/dates";
import {
  deltaPct,
  formatCompact,
  formatDuration,
  formatPercent,
  formatUsdMicros,
} from "@/lib/formatters";
import { useWindowDays, windowLabel } from "@/lib/windowDays";

const ENV_COLOR: Record<string, string> = {
  production: "var(--series-1)",
  staging: "var(--series-2)",
  test: "var(--series-3)",
  dev: "var(--series-5)",
  retired: "var(--mute-solid)",
};

export function AgentActivityTab({ agentId }: { agentId: string }) {
  const { days } = useWindowDays();
  const { data, isLoading, isError, error, refetch } = useAgentOperations(agentId, days);

  if (isLoading) {
    return (
      <div className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} height="96px" />
          ))}
        </div>
        <Skeleton height="240px" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <ErrorState
        title="Could not load this agent's activity"
        message={error instanceof Error ? error.message : "Unknown error"}
        onRetry={() => void refetch()}
      />
    );
  }

  if (data.runs_total === 0 && data.running_now === 0) {
    return (
      <div className="rounded-card bg-bg-sunk px-4 py-10 text-center">
        <p className="text-body text-ink-600">
          This agent has not run in {windowLabel(days).toLowerCase()}.
        </p>
        <p className="mt-1 text-table text-ink-400">
          Runs appear here once an SDK or collector reports them to{" "}
          <code className="font-mono">POST /v1/operations/runs</code>.
        </p>
      </div>
    );
  }

  const series = Object.entries(data.activity.by_environment)
    .filter(([, values]) => values.some((v) => v > 0))
    .map(([name, values]) => ({
      name,
      values,
      color: ENV_COLOR[name] ?? "var(--series-6)",
    }));

  const undeclared = data.tools.filter((t) => !t.declared);

  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Runs"
          value={formatCompact(data.runs_total)}
          explain={data.running_now > 0 ? `${data.running_now} in flight` : "none in flight"}
          delta={{ pct: deltaPct(data.runs_total, data.runs_previous), upIsGood: true }}
        />
        <Stat
          label="Success rate"
          value={formatPercent(data.success_rate_pct, 1)}
          explain={`${data.runs_failed} failed · ${data.runs_refused} refused`}
          tone={data.success_rate_pct < 95 ? "warn" : "ok"}
        />
        <Stat
          label="Spend"
          value={formatUsdMicros(data.cost_micros, { compact: true })}
          explain={`${formatCompact(data.tokens)} tokens`}
          delta={{
            pct: deltaPct(data.cost_micros, data.previous_cost_micros),
            upIsGood: false,
          }}
        />
        <Stat
          label="Slowest 5%"
          value={formatDuration(data.p95_duration_ms)}
          explain={`median ${formatDuration(data.p50_duration_ms)}`}
        />
      </div>

      <Panel
        title="Activity"
        explain="Runs per day. The dashed line is failures."
        more={{ label: "All runs for this agent", to: `/runs?agent_id=${agentId}` }}
      >
        <AreaChart
          labels={data.activity.days}
          series={series}
          overlay={{
            name: "Failures",
            values: data.activity.failures,
            color: "var(--risk-solid)",
          }}
          formatLabel={formatDay}
          formatValue={formatCompact}
          height={200}
        />
      </Panel>

      <div className="grid gap-3 lg:grid-cols-3">
        <Panel title="Models" explain="Where this agent's spend went.">
          <BarList
            items={data.by_model.map((slice) => ({
              label: slice.label,
              value: slice.cost_micros,
              display: formatUsdMicros(slice.cost_micros, { compact: true }),
              meta: `${formatCompact(slice.runs)} runs`,
              color: "color-mix(in srgb, var(--series-1) 16%, transparent)",
            }))}
            emptyMessage="No model attributed."
          />
        </Panel>

        <Panel
          title="Why runs failed"
          explain="A classification, never a message — no model output is stored."
        >
          <BarList
            items={data.error_kinds.map((kind) => ({
              label: kind.error_kind,
              value: kind.runs,
              meta: `${formatPercent((kind.runs / Math.max(data.runs_total, 1)) * 100, 1)} of runs`,
              color: "color-mix(in srgb, var(--risk-solid) 14%, transparent)",
            }))}
            emptyMessage="No failures in this window."
          />
        </Panel>

        <Panel
          title="MCP servers"
          explain={`${data.mcp_servers.length} reached by this agent.`}
          more={{ label: "Estate view", to: "/tools" }}
        >
          {data.mcp_servers.length === 0 ? (
            <p className="py-6 text-center text-body text-ink-400">
              This agent called no MCP server.
            </p>
          ) : (
            <ul className="space-y-1.5">
              {data.mcp_servers.map((server) => (
                <li
                  key={server.server_name}
                  className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-bg-hover"
                >
                  <Icon name="mcp" size={15} className="shrink-0 text-ink-400" />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-body text-ink-900">
                      {server.server_name}
                    </span>
                    <span className="block text-micro text-ink-400">
                      {server.tools} tool{server.tools === 1 ? "" : "s"} ·{" "}
                      {formatCompact(server.calls)} calls
                    </span>
                  </span>
                  {server.declared ? (
                    <Badge label="Declared" tone="ok" />
                  ) : (
                    <Badge label="Undeclared" tone="risk" />
                  )}
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      {undeclared.length > 0 ? (
        <div className="flex items-start gap-3 rounded-card bg-warn-bg px-4 py-3 text-body text-warn-fg shadow-card">
          <Icon name="alert" size={18} className="mt-0.5 shrink-0" />
          <p>
            This agent called{" "}
            <strong className="font-semibold">
              {undeclared.length} tool{undeclared.length === 1 ? "" : "s"}
            </strong>{" "}
            its approved bill of materials never mentions:{" "}
            <span className="font-mono">
              {undeclared.slice(0, 5).map((t) => t.tool_name).join(", ")}
              {undeclared.length > 5 ? `, +${undeclared.length - 5} more` : ""}
            </span>
            .{" "}
            <Link to="/tools" className="underline">
              Review the inventory
            </Link>
          </p>
        </div>
      ) : null}

      <Panel
        title="Recent runs"
        more={{ label: "All runs", to: `/runs?agent_id=${agentId}` }}
        noPadding
      >
        <div className="overflow-x-auto scrollbar-thin">
          <table className="min-w-[760px]">
            <thead>
              <tr>
                <th className="px-3 py-2">Started</th>
                <th className="px-3 py-2">Where</th>
                <th className="px-3 py-2">Outcome</th>
                <th className="px-3 py-2 text-right">Took</th>
                <th className="px-3 py-2 text-right">Steps</th>
                <th className="px-3 py-2 text-right">Tools</th>
                <th className="px-3 py-2 text-right">Cost</th>
                <th className="px-3 py-2">Note</th>
              </tr>
            </thead>
            <tbody>
              {data.recent_runs.map((run) => (
                <tr key={run.id} className="hover:bg-bg-hover">
                  <td className="whitespace-nowrap px-3 py-2 text-ink-600">
                    <RelativeTime iso={run.started_at} />
                  </td>
                  <td className="px-3 py-2 text-ink-600">{run.environment}</td>
                  <td className="px-3 py-2">
                    <RunOutcomeBadge outcome={run.outcome} />
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-700">
                    {formatDuration(run.duration_ms)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-600">
                    {run.step_count}
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-600">
                    {run.tool_call_count}
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-700">
                    {formatUsdMicros(run.cost_micros)}
                  </td>
                  <td className="px-3 py-2">
                    <span className="flex flex-wrap items-center gap-1">
                      {run.escalated ? <Badge label="Escalated" tone="info" /> : null}
                      {run.error_kind ? <Badge label={run.error_kind} tone="risk" /> : null}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  );
}
