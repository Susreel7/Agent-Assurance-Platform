/**
 * Tools & MCP — what the agents reached for, and whether they were allowed to.
 *
 * The `declared` column is the whole point of this screen. Everything else here is a
 * usage report that a dozen products already give you; the question only this one can
 * answer is whether the thing an agent called appears in the bill of materials its
 * client approved. An MCP server is where that matters most: it is a process somebody
 * else operates, it can add a tool without any agent's descriptor changing, and the
 * agent will happily call it.
 *
 * The check is per calling agent, not per estate — "some other team declared this tool"
 * is no answer to "why is this agent calling it".
 *
 * Servers come before tools because the server is the thing somebody owns and can
 * revoke. When an MCP server misbehaves the action is at that level, not at the level
 * of one of its tools.
 */

import { useState } from "react";
import { useMcpServers, useToolInventory } from "@/api/queries";
import { ErrorState } from "@/components/ErrorState";
import { Icon } from "@/components/Icon";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { RelativeTime } from "@/components/RelativeTime";
import { Skeleton } from "@/components/Skeleton";
import { Stat } from "@/components/Stat";
import { Badge } from "@/components/StateBadge";
import { formatCompact, formatDuration, formatPercent } from "@/lib/formatters";
import { useWindowDays, windowLabel } from "@/lib/windowDays";
import type { ToolSurface } from "@/api/types";

const SURFACE_LABEL: Record<ToolSurface, string> = {
  mcp: "MCP",
  native: "Built in",
  retrieval: "Retrieval",
  sub_agent: "Sub-agent",
  handoff: "Handoff",
};

function DeclaredCell({ declared, count }: { declared: boolean; count: number }) {
  if (declared) {
    return (
      <span className="inline-flex items-center gap-1 text-ok-fg">
        <Icon name="check" size={13} />
        <span className="text-micro">declared</span>
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1 text-risk-fg"
      title="An agent called this without naming it in the bill of materials its client approved."
    >
      <Icon name="alert" size={13} />
      <span className="text-micro">
        {count} agent{count === 1 ? "" : "s"} undeclared
      </span>
    </span>
  );
}

export default function ToolsScreen() {
  const { days } = useWindowDays();
  const [onlyUndeclared, setOnlyUndeclared] = useState(false);

  const mcp = useMcpServers(days);
  const tools = useToolInventory(days);

  if (mcp.isLoading || tools.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton height="4rem" />
        <div className="grid gap-3 sm:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} height="104px" />
          ))}
        </div>
        <Skeleton height="320px" />
      </div>
    );
  }

  if (mcp.isError || tools.isError || !mcp.data || !tools.data) {
    const err = mcp.error ?? tools.error;
    return (
      <ErrorState
        title="Could not load the tool inventory"
        message={err instanceof Error ? err.message : "Unknown error"}
        onRetry={() => {
          void mcp.refetch();
          void tools.refetch();
        }}
      />
    );
  }

  const rows = onlyUndeclared
    ? tools.data.items.filter((item) => !item.declared)
    : tools.data.items;

  const totalCalls = tools.data.items.reduce((sum, item) => sum + item.calls, 0);
  const totalErrors = tools.data.items.reduce((sum, item) => sum + item.errors, 0);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Tools & MCP"
        explain={`Everything your agents called over ${windowLabel(days).toLowerCase()}, and whether the agent calling it had declared it.`}
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="MCP servers"
          value={String(mcp.data.servers.length)}
          explain={`${formatCompact(mcp.data.total_calls)} calls through them`}
        />
        <Stat
          label="Distinct tools"
          value={String(tools.data.items.length)}
          explain={`${formatCompact(totalCalls)} calls in total`}
        />
        <Stat
          label="Undeclared"
          value={String(tools.data.undeclared)}
          explain="called by an agent that never declared it"
          tone={tools.data.undeclared > 0 ? "risk" : "ok"}
        />
        <Stat
          label="Tool error rate"
          value={formatPercent(totalCalls ? (totalErrors / totalCalls) * 100 : 0, 2)}
          explain={`${formatCompact(totalErrors)} failed calls`}
          tone={totalErrors / Math.max(totalCalls, 1) > 0.05 ? "warn" : "neutral"}
        />
      </div>

      {tools.data.undeclared > 0 ? (
        <div className="flex items-start gap-3 rounded-card bg-warn-bg px-4 py-3 text-body text-warn-fg shadow-card">
          <Icon name="alert" size={18} className="mt-0.5 shrink-0" />
          <p>
            <strong className="font-semibold">
              {tools.data.undeclared} tool{tools.data.undeclared === 1 ? " was" : "s were"}
            </strong>{" "}
            called by an agent whose approved bill of materials never mentioned{" "}
            {tools.data.undeclared === 1 ? "it" : "them"}. That is a capability running in
            production that nobody signed off — worth confirming before the next review asks
            about it.
          </p>
        </div>
      ) : null}

      <Panel
        title="MCP servers"
        explain="A server is a process somebody else operates. It can add tools without your descriptor changing."
        noPadding
      >
        <div className="overflow-x-auto scrollbar-thin">
          <table className="min-w-[820px]">
            <thead>
              <tr>
                <th className="px-3 py-2">Server</th>
                <th className="px-3 py-2">Tools exposed</th>
                <th className="px-3 py-2 text-right">Agents</th>
                <th className="px-3 py-2 text-right">Calls</th>
                <th className="px-3 py-2 text-right">Errors</th>
                <th className="px-3 py-2 text-right">Mean</th>
                <th className="px-3 py-2">Declared</th>
                <th className="px-3 py-2">Last call</th>
              </tr>
            </thead>
            <tbody>
              {mcp.data.servers.map((server) => (
                <tr key={server.server_name} className="hover:bg-bg-hover">
                  <td className="px-3 py-2">
                    <span className="flex items-center gap-2">
                      <Icon name="mcp" size={15} className="shrink-0 text-ink-400" />
                      <span className="font-medium text-ink-900">{server.server_name}</span>
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <span className="flex flex-wrap gap-1">
                      {server.tool_names.map((name) => (
                        <span
                          key={name}
                          className="rounded border border-line-200 bg-bg-sunk px-1.5 py-0.5 font-mono text-micro text-ink-600"
                        >
                          {name}
                        </span>
                      ))}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-700">
                    {server.agents}
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-700">
                    {server.calls.toLocaleString()}
                  </td>
                  <td
                    className={`px-3 py-2 text-right font-mono tabular-nums ${
                      server.error_rate_pct > 5 ? "text-risk-fg" : "text-ink-600"
                    }`}
                  >
                    {server.errors.toLocaleString()}
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-600">
                    {formatDuration(server.mean_duration_ms)}
                  </td>
                  <td className="px-3 py-2">
                    <DeclaredCell
                      declared={server.declared}
                      count={server.undeclared_agents}
                    />
                  </td>
                  <td className="px-3 py-2 text-ink-600">
                    {server.last_seen_at ? <RelativeTime iso={server.last_seen_at} /> : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {mcp.data.servers.length === 0 ? (
          <p className="px-4 py-10 text-center text-body text-ink-400">
            No MCP server was called in {windowLabel(days).toLowerCase()}.
          </p>
        ) : null}
      </Panel>

      <Panel
        title="Every tool called"
        explain="Across all surfaces — MCP, built-in, retrieval, sub-agents and handoffs."
        noPadding
        toolbar={
          <button
            type="button"
            onClick={() => setOnlyUndeclared((v) => !v)}
            aria-pressed={onlyUndeclared}
            className={`rounded-md px-2.5 py-1 text-table transition-colors ${
              onlyUndeclared
                ? "bg-accent text-white"
                : "bg-bg-sunk text-ink-600 hover:bg-bg-hover hover:text-ink-900"
            }`}
          >
            Undeclared only
          </button>
        }
      >
        <div className="overflow-x-auto scrollbar-thin">
          <table className="min-w-[820px]">
            <thead>
              <tr>
                <th className="px-3 py-2">Tool</th>
                <th className="px-3 py-2">Where from</th>
                <th className="px-3 py-2 text-right">Agents</th>
                <th className="px-3 py-2 text-right">Calls</th>
                <th className="px-3 py-2 text-right">Errors</th>
                <th className="px-3 py-2 text-right">Denied</th>
                <th className="px-3 py-2 text-right">Mean</th>
                <th className="px-3 py-2 text-right">Slowest</th>
                <th className="px-3 py-2">Declared</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((tool) => (
                <tr
                  key={`${tool.surface}:${tool.server_name}:${tool.tool_name}`}
                  className="hover:bg-bg-hover"
                >
                  <td className="px-3 py-2">
                    <span className="font-mono text-table text-ink-900">{tool.tool_name}</span>
                    {tool.server_name ? (
                      <span className="ml-1.5 text-micro text-ink-400">{tool.server_name}</span>
                    ) : null}
                  </td>
                  <td className="px-3 py-2">
                    <Badge label={SURFACE_LABEL[tool.surface]} tone={tool.surface === "mcp" ? "info" : "mute"} />
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-700">
                    {tool.agents}
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-700">
                    {tool.calls.toLocaleString()}
                  </td>
                  <td
                    className={`px-3 py-2 text-right font-mono tabular-nums ${
                      tool.error_rate_pct > 5 ? "text-risk-fg" : "text-ink-600"
                    }`}
                  >
                    {tool.errors.toLocaleString()}
                  </td>
                  {/* Denied is not an error. A guardrail refusing a call is the system
                      working, and colouring it red teaches people to switch it off. */}
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-600">
                    {tool.denied.toLocaleString()}
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-600">
                    {formatDuration(tool.mean_duration_ms)}
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-600">
                    {formatDuration(tool.max_duration_ms)}
                  </td>
                  <td className="px-3 py-2">
                    <DeclaredCell declared={tool.declared} count={tool.undeclared_agents} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {rows.length === 0 ? (
          <p className="px-4 py-10 text-center text-body text-ink-400">
            {onlyUndeclared
              ? "Every tool called was declared by the agent calling it."
              : `No tool was called in ${windowLabel(days).toLowerCase()}.`}
          </p>
        ) : null}
      </Panel>
    </div>
  );
}
