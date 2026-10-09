/**
 * Overview — the one screen someone opens every morning.
 *
 * It is ordered by what changes a decision, not by what is easiest to compute. Anything
 * needing a human comes first; the numbers that explain the estate come next; the
 * breakdowns you only read when a number looks wrong come last. Two earlier versions of
 * this page got that order backwards and both ended up being opened once and abandoned
 * — one was six metric tiles and four charts with nothing actionable above the fold,
 * the other was an attention list with no context around it, which left you unable to
 * tell whether three open issues was normal.
 *
 * The agent table is the reason this product exists. A runtime dashboard shows cost and
 * latency; a governance tool shows approvals and drift. Putting them in one row is what
 * answers "is the expensive one also the unapproved one", and that question is what
 * makes somebody do something.
 *
 * Everything on this page comes from a single request, so the numbers on it were all
 * measured over the same window. Seven requests arriving in an order you can watch
 * reads as a slow page rather than a rich one, and lets two panels disagree.
 */

import { Link } from "react-router-dom";
import { useDashboardSummary } from "@/api/queries";
import { ErrorState } from "@/components/ErrorState";
import { Icon } from "@/components/Icon";
import { Panel } from "@/components/Panel";
import { RelativeTime } from "@/components/RelativeTime";
import { Skeleton } from "@/components/Skeleton";
import { Stat } from "@/components/Stat";
import { AreaChart } from "@/components/charts/AreaChart";
import { BarList } from "@/components/charts/BarList";
import { DonutChart, DonutLegend } from "@/components/charts/DonutChart";
import {
  FrameworkTag,
  HealthBadge,
  ReleaseStateBadge,
  Badge,
} from "@/components/StateBadge";
import { formatDay } from "@/lib/dates";
import {
  deltaPct,
  formatCompact,
  formatDuration,
  formatPercent,
  formatSemverRange,
  formatUsdMicros,
} from "@/lib/formatters";
import { useWindowDays, windowLabel } from "@/lib/windowDays";
import type { AgentOpsRow, AttentionItem, ComplianceBar, HealthMix } from "@/api/types";
import { WindowDaysSelect } from "@/components/WindowDaysSelect";
import { LifecycleStateBadge } from "@/components/StateBadge";
import { MiniBars } from "@/components/charts/MiniBars";

const ENV_COLOR: Record<string, string> = {
  production: "var(--series-1)",
  staging: "var(--series-2)",
  test: "var(--series-3)",
  dev: "var(--series-5)",
  retired: "var(--mute-solid)",
};

function greeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

function healthSlices(mix: HealthMix) {
  return [
    { label: "Healthy", value: mix.healthy, color: "var(--ok-solid)" },
    { label: "Warning", value: mix.warning, color: "var(--warn-solid)" },
    { label: "At risk", value: mix.at_risk, color: "var(--risk-solid)" },
    { label: "Critical", value: mix.critical, color: "var(--risk-fg)" },
  ];
}

function AttentionRow({ item }: { item: AttentionItem }) {
  const tone = item.severity === "critical" || item.severity === "high" ? "risk" : "warn";
  return (
    <li>
      <Link
        to={item.href}
        className="flex items-start gap-3 rounded-md px-2.5 py-2 transition-colors hover:bg-bg-hover hover:no-underline"
      >
        <Icon
          name={tone === "risk" ? "issues" : "alert"}
          size={16}
          className={`mt-0.5 shrink-0 ${tone === "risk" ? "text-risk-solid" : "text-warn-solid"}`}
        />
        <span className="min-w-0 flex-1">
          <span className="block text-body font-medium text-ink-900">{item.title}</span>
          {/* The sentence that earns this list its place at the top of the page. "X is
              running an unapproved version" is a fact; "X has not agreed to what is
              running for them" is why anyone should stop what they are doing. */}
          <span className="block text-table text-ink-600">{item.consequence}</span>
        </span>
        <span className="shrink-0 text-micro text-ink-400">
          <RelativeTime iso={item.occurred_at} />
        </span>
      </Link>
    </li>
  );
}

function ComplianceRow({ bar }: { bar: ComplianceBar }) {
  const tone =
    bar.pct >= 90 ? "var(--ok-solid)" : bar.pct >= 60 ? "var(--warn-solid)" : "var(--risk-solid)";
  return (
    <li className="space-y-1">
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-body text-ink-900" title={bar.explain}>
          {bar.label}
        </span>
        <span className="font-mono text-table text-ink-600">
          {bar.covered}/{bar.applicable}
        </span>
      </div>
      <div className="h-1.5 overflow-hidden rounded-full bg-bg-sunk">
        <div
          className="h-full rounded-full transition-[width] duration-500"
          style={{ width: `${Math.min(bar.pct, 100)}%`, background: tone }}
        />
      </div>
    </li>
  );
}

function AgentRow({ agent }: { agent: AgentOpsRow }) {
  return (
    <tr className="hover:bg-bg-hover">
      <td className="px-3 py-2">
        <Link
          to={`/agents/${agent.id}`}
          className="block truncate font-medium text-ink-900 hover:underline"
        >
          {agent.display_name}
        </Link>
        <span className="mt-0.5 flex items-center gap-1.5">
          <FrameworkTag framework={agent.runtime_framework} />
          {agent.semver ? (
            <span className="font-mono text-micro text-ink-400">v{agent.semver}</span>
          ) : null}
        </span>
      </td>
      <td className="px-3 py-2">
        <HealthBadge health={agent.health} />
        {agent.drifted ? <span className="ml-1"><Badge label="Drifted" tone="warn" /></span> : null}
      </td>
      <td className="px-3 py-2">
        <LifecycleStateBadge state={agent.lifecycle_state} />
      </td>
      <td className="px-3 py-2 text-right font-mono tabular-nums">
        {agent.runs.toLocaleString()}
        {agent.running_now > 0 ? (
          <span className="ml-1.5 text-micro text-warn-fg">+{agent.running_now}</span>
        ) : null}
      </td>
      <td
        className={`px-3 py-2 text-right font-mono tabular-nums ${
          agent.success_rate_pct < 90 ? "text-risk-fg" : "text-ink-700"
        }`}
      >
        {agent.runs ? formatPercent(agent.success_rate_pct, 0) : "—"}
      </td>
      <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-700">
        {formatDuration(agent.p95_duration_ms || null)}
      </td>
      <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-700">
        {formatUsdMicros(agent.cost_micros)}
      </td>
      <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-600">
        {agent.mcp_servers || "—"}
      </td>
      <td className="px-3 py-2">
        {agent.accreditation_state === "approved" ? (
          <Badge label="Approved" tone="ok" />
        ) : (
          <Badge label={agent.accreditation_state ? "In review" : "None"} tone="mute" />
        )}
      </td>
    </tr>
  );
}

export default function HomeScreen() {
  const { days } = useWindowDays();
  const { data, isLoading, isError, error, refetch } = useDashboardSummary(days);

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton height="2.5rem" width="320px" />
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} height="104px" />
          ))}
        </div>
        <Skeleton height="280px" />
        <Skeleton height="320px" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <ErrorState
        title="Could not load the overview"
        message={error instanceof Error ? error.message : "Unknown error"}
        onRetry={() => void refetch()}
      />
    );
  }

  const { estate, health, operations: ops, attention, compliance, agents } = data;

  const activitySeries = Object.entries(ops.activity.by_environment)
    .filter(([, values]) => values.some((v) => v > 0))
    .map(([name, values]) => ({
      name,
      values,
      color: ENV_COLOR[name] ?? "var(--series-6)",
    }));

  const needsAttention = attention.length;
  const atRisk = health.at_risk + health.critical;
  const activitySpark = ops.activity.totals.slice(-14);
  const healthyShare =
    estate.agents_total > 0 ? Math.round((health.healthy / estate.agents_total) * 100) : 0;

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="max-w-2xl">
          <p className="text-body text-ink-600">
            {greeting()}, Operator <span aria-hidden="true">☀️</span>
          </p>
          <h1 className="mt-1 text-headline font-bold tracking-tight text-ink-900">
            Your AI agents are in safe hands.
          </h1>
          <p className="mt-2 text-lede text-ink-600">
            Monitor, govern and ensure trust across your entire agent estate.
            {needsAttention > 0 ? (
              <>
                {" "}
                <Link to="/findings" className="font-medium text-ink-900 hover:underline">
                  {needsAttention} item{needsAttention === 1 ? "" : "s"} need a decision.
                </Link>
              </>
            ) : null}
          </p>
        </div>
        <WindowDaysSelect variant="card" className="shrink-0" />
      </header>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
        <Stat
          label="Total agents"
          value={String(estate.agents_total)}
          icon="agents"
          iconTint="accent"
          href="/agents"
        />
        <Stat
          label="Active agents"
          value={String(ops.agents_active)}
          explain={`${estate.agents_in_production} in production`}
          icon="pulse"
          iconTint="ok"
          sparkline={activitySpark}
          href="/agents"
        />
        <Stat
          label="At risk"
          value={String(atRisk)}
          tone={atRisk > 0 ? "risk" : "ok"}
          icon="alert"
          iconTint="risk"
          href="/agents"
        />
        <Stat
          label="Unaccredited"
          value={String(estate.agents_unaccredited)}
          tone={estate.agents_unaccredited > 0 ? "warn" : "ok"}
          icon="approvals"
          iconTint="warn"
          href="/accreditations"
        />
        <Stat
          label="Open issues"
          value={String(estate.open_findings)}
          explain={`${estate.open_critical_findings} critical`}
          tone={estate.open_critical_findings > 0 ? "risk" : estate.open_findings > 0 ? "warn" : "ok"}
          icon="issues"
          iconTint="risk"
          href="/findings"
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Runs"
          value={formatCompact(ops.runs_total)}
          explain={
            ops.running_now > 0 ? `${ops.running_now} in flight now` : "none in flight now"
          }
          delta={{ pct: deltaPct(ops.runs_total, ops.runs_previous), upIsGood: true }}
          sparkline={activitySpark}
          href="/runs"
        />
        <Stat
          label="Success rate"
          value={formatPercent(ops.success_rate_pct, 1)}
          explain={`${ops.runs_failed} failed · ${ops.runs_refused} refused by a guardrail`}
          tone={ops.success_rate_pct < 95 ? "warn" : "ok"}
          href="/runs"
        />
        <Stat
          label="Spend"
          value={formatUsdMicros(ops.cost.total_cost_micros, { compact: true })}
          explain={`${formatCompact(ops.cost.total_tokens)} tokens`}
          delta={{
            pct: deltaPct(ops.cost.total_cost_micros, ops.cost.previous_cost_micros),
            upIsGood: false,
          }}
          href="/cost"
        />
        <Stat
          label="Needs a decision"
          value={String(needsAttention)}
          explain={`${estate.approvals_waiting} awaiting approval`}
          tone={needsAttention === 0 ? "ok" : estate.open_critical_findings > 0 ? "risk" : "warn"}
          href="/findings"
        />
      </div>

      {needsAttention > 0 ? (
        <Panel
          title="Needs a decision"
          explain="Each line says what happens if it is left alone."
          more={{ label: "All issues", to: "/findings" }}
          noPadding
        >
          <ul className="px-1.5 pb-2">
            {attention.map((item) => (
              <AttentionRow key={item.id} item={item} />
            ))}
          </ul>
        </Panel>
      ) : null}

      <div className="grid gap-3 lg:grid-cols-3">
        <Panel
          className="lg:col-span-2"
          title="Activity"
          explain="Runs per day, stacked by environment. The dashed line is failures."
          more={{ label: "All runs", to: "/runs" }}
          toolbar={
            <div className="flex items-center gap-3">
              {activitySeries.map((s) => (
                <span key={s.name} className="flex items-center gap-1.5 text-micro text-ink-600">
                  <span className="h-2 w-2 rounded-full" style={{ background: s.color }} />
                  {s.name}
                </span>
              ))}
            </div>
          }
        >
          <AreaChart
            labels={ops.activity.days}
            series={activitySeries}
            overlay={{ name: "Failures", values: ops.activity.failures, color: "var(--risk-solid)" }}
            formatLabel={formatDay}
            formatValue={formatCompact}
            height={216}
          />
          <dl className="mt-3 grid grid-cols-3 gap-3 border-t border-line-200 pt-3">
            <div>
              <dt className="text-micro text-ink-400">Median run</dt>
              <dd className="font-mono text-body text-ink-900">
                {formatDuration(ops.p50_duration_ms)}
              </dd>
            </div>
            <div>
              <dt className="text-micro text-ink-400">Slowest 5%</dt>
              <dd className="font-mono text-body text-ink-900">
                {formatDuration(ops.p95_duration_ms)}
              </dd>
            </div>
            <div>
              <dt className="text-micro text-ink-400">Escalated to a human</dt>
              <dd className="font-mono text-body text-ink-900">
                {ops.escalations.toLocaleString()}
              </dd>
            </div>
          </dl>
        </Panel>

        <Panel title="Agent health" explain={`${estate.agents_total} agents registered.`}>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center">
            <DonutChart
              slices={healthSlices(health)}
              centerValue={String(estate.agents_total)}
              centerLabel="agents"
            />
            <div className="min-w-0 flex-1">
              <DonutLegend slices={healthSlices(health)} />
            </div>
          </div>
          {healthyShare >= 70 ? (
            <div className="mt-4 flex gap-2 rounded-lg bg-ok-bg px-3 py-2.5 text-table text-ok-fg">
              <Icon name="check" size={18} className="mt-0.5 shrink-0" />
              <div>
                <p className="font-semibold text-ink-900">
                  Overall agent health is {healthyShare >= 85 ? "good" : "fair"}.
                </p>
                <p className="text-micro text-ink-600">
                  {health.healthy} healthy · {estate.agents_drifted} drifted from approval
                </p>
              </div>
            </div>
          ) : null}
        </Panel>
      </div>

      <Panel
        title="Agents"
        explain="What each one is, and what it has been doing. Busiest first."
        more={{ label: "All agents", to: "/agents" }}
        noPadding
      >
        <div className="overflow-x-auto scrollbar-thin">
          <table className="min-w-[900px]">
            <thead>
              <tr>
                <th className="px-3 py-2">Agent</th>
                <th className="px-3 py-2">Health</th>
                <th className="px-3 py-2">Environment</th>
                <th className="px-3 py-2 text-right">Runs</th>
                <th className="px-3 py-2 text-right">Success</th>
                <th className="px-3 py-2 text-right">p95</th>
                <th className="px-3 py-2 text-right">Cost</th>
                <th className="px-3 py-2 text-right">MCP</th>
                <th className="px-3 py-2">Approval</th>
              </tr>
            </thead>
            <tbody>
              {agents.map((agent) => (
                <AgentRow key={agent.id} agent={agent} />
              ))}
            </tbody>
          </table>
        </div>
        {agents.length === 0 ? (
          <p className="px-4 py-8 text-center text-body text-ink-400">
            No agents registered yet.
          </p>
        ) : null}
      </Panel>

      <div className="grid gap-3 lg:grid-cols-3">
        <Panel
          title="Top frameworks"
          explain="Which agent framework the runs came from."
          more={{ label: "See all", to: "/tools" }}
        >
          <BarList
            items={ops.frameworks.map((f, i) => ({
              label: f.framework,
              value: f.runs || f.agents,
              display: `${f.share_pct.toFixed(0)}%`,
              meta: `${f.agents} agent${f.agents === 1 ? "" : "s"}`,
              color: `color-mix(in srgb, var(--series-${(i % 6) + 1}) 18%, transparent)`,
            }))}
            emptyMessage="No framework recorded yet."
          />
        </Panel>

        <Panel
          title="Cost & usage"
          explain={`${formatUsdMicros(ops.cost.total_cost_micros)} across ${windowLabel(days).toLowerCase()}.`}
          more={{ label: "See all", to: "/cost" }}
          toolbar={<WindowDaysSelect variant="compact" />}
        >
          <div className="mb-4 grid grid-cols-2 gap-4">
            <div>
              <p className="text-micro text-ink-400">Total cost</p>
              <p className="text-stat font-semibold text-ink-900">
                {formatUsdMicros(ops.cost.total_cost_micros, { compact: true })}
              </p>
              <p className="text-micro text-ok-fg">
                {deltaPct(ops.cost.total_cost_micros, ops.cost.previous_cost_micros) < -0.5
                  ? `↓ ${Math.abs(deltaPct(ops.cost.total_cost_micros, ops.cost.previous_cost_micros)).toFixed(0)}% vs prior period`
                  : "vs prior period"}
              </p>
            </div>
            <div>
              <p className="text-micro text-ink-400">Total tokens</p>
              <p className="text-stat font-semibold text-ink-900">
                {formatCompact(ops.cost.total_tokens)}
              </p>
            </div>
          </div>
          <MiniBars
            values={ops.cost.by_day.map((d) => d.cost_micros)}
            width={320}
            height={64}
            color="var(--ok-solid)"
            label="Daily spend"
          />
        </Panel>

        <Panel
          title="MCP & tools"
          explain={`${ops.tools.mcp_servers} MCP servers called by your agents.`}
          more={{ label: "All tools", to: "/tools" }}
        >
          {ops.tools.undeclared > 0 ? (
            <Link
              to="/tools"
              className="mb-2 flex items-center gap-2 rounded-md bg-warn-bg px-2.5 py-2 text-table text-warn-fg hover:no-underline"
            >
              <Icon name="alert" size={15} className="shrink-0" />
              <span>
                <strong className="font-semibold">{ops.tools.undeclared}</strong> tools were called
                by an agent whose approved descriptor never mentioned them.
              </span>
            </Link>
          ) : null}
          <BarList
            items={ops.tools.items.slice(0, 6).map((t) => ({
              label: t.server_name ? `${t.server_name} · ${t.tool_name}` : t.tool_name,
              value: t.calls,
              display: formatCompact(t.calls),
              meta: `${t.agents} agent${t.agents === 1 ? "" : "s"}${t.declared ? "" : " · undeclared"}`,
              color: t.declared
                ? "color-mix(in srgb, var(--series-2) 16%, transparent)"
                : "var(--warn-bg)",
            }))}
            emptyMessage="No tool calls recorded yet."
          />
        </Panel>
      </div>

      <Panel
        title="Recent activity"
        explain="Governance and runtime events, newest first."
        more={{ label: "See all", to: "/findings" }}
        noPadding
      >
        <ul className="divide-y divide-line-200">
          {attention.slice(0, 5).map((item) => (
            <AttentionRow key={item.id} item={item} />
          ))}
          {attention.length === 0
            ? data.recent_releases.slice(0, 3).map((release) => (
                <li key={release.id}>
                  <Link
                    to={`/releases/${release.id}`}
                    className="flex items-center gap-3 px-4 py-3 hover:bg-bg-hover hover:no-underline"
                  >
                    <span className="flex h-9 w-9 items-center justify-center rounded-full bg-accent-soft text-accent-ink">
                      <Icon name="changes" size={16} />
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="block text-body font-medium text-ink-900">
                        Release {release.release_tag}
                      </span>
                      <span className="block text-micro text-ink-400">{release.agent_urn}</span>
                    </span>
                    <RelativeTime iso={release.created_at} />
                  </Link>
                </li>
              ))
            : null}
        </ul>
      </Panel>

      <div className="grid gap-3 lg:grid-cols-2">
        <Panel
          title="Compliance overview"
          explain="Each bar carries the two numbers it came from."
        >
          <ul className="space-y-3">
            {compliance.map((bar) => (
              <ComplianceRow key={bar.id} bar={bar} />
            ))}
          </ul>
          <p className="mt-3 border-t border-line-200 pt-3 text-table text-ink-600">
            {formatPercent(estate.slos_meeting_target_pct, 0)} of service levels are meeting their
            target.{" "}
            <Link to="/sla" className="text-accent-ink hover:underline">
              Service levels
            </Link>
          </p>
        </Panel>

        <Panel
          title="Recent changes"
          explain="Version changes to an agent, newest first."
          more={{ label: "All changes", to: "/releases" }}
          noPadding
        >
          <ul className="divide-y divide-line-200">
            {data.recent_releases.map((release) => (
              <li key={release.id}>
                <Link
                  to={`/releases/${release.id}`}
                  className="flex items-center gap-3 px-4 py-2.5 hover:bg-bg-hover hover:no-underline"
                >
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-body text-ink-900">
                      {release.title ?? release.release_tag}
                    </span>
                    <span className="block truncate font-mono text-micro text-ink-400">
                      {release.agent_urn.split(":").pop()} ·{" "}
                      {formatSemverRange(release.from_semver, release.to_semver)}
                    </span>
                  </span>
                  <ReleaseStateBadge state={release.state} />
                  <span className="shrink-0 text-micro text-ink-400">
                    <RelativeTime iso={release.created_at} />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
          {data.recent_releases.length === 0 ? (
            <p className="px-4 py-8 text-center text-body text-ink-400">No changes yet.</p>
          ) : null}
        </Panel>
      </div>

      <p className="pb-2 text-center text-micro text-ink-400">
        Measured over {windowLabel(days).toLowerCase()} · generated{" "}
        <RelativeTime iso={data.generated_at} />
      </p>
    </div>
  );
}
