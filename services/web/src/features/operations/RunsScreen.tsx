/**
 * Runs — every execution, newest first.
 *
 * The log, not a chart. Somebody arrives here from a number on the overview and wants
 * the individual rows behind it, which means the filters have to match the ways that
 * number can be sliced: by agent, by environment, by how it ended, and by whether a
 * human got pulled in.
 *
 * Step metadata (names, durations, classifications) opens in the trace viewer; prompts
 * and tool arguments are never stored (AGENTS.md rule 5).
 */

import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useRuns } from "@/api/queries";
import { ErrorState } from "@/components/ErrorState";
import { Icon } from "@/components/Icon";
import { PageHeader } from "@/components/PageHeader";
import { Pagination } from "@/components/Pagination";
import { Panel } from "@/components/Panel";
import { RelativeTime } from "@/components/RelativeTime";
import { TableSkeleton } from "@/components/Skeleton";
import { Badge, RunOutcomeBadge } from "@/components/StateBadge";
import { formatDuration, formatUsdMicros } from "@/lib/formatters";
import { useWindowDays, windowLabel } from "@/lib/windowDays";
import type { LifecycleState, RunOutcome } from "@/api/types";

const OUTCOMES: RunOutcome[] = [
  "succeeded",
  "failed",
  "refused",
  "timed_out",
  "running",
  "cancelled",
];

const ENVIRONMENTS: LifecycleState[] = ["production", "staging", "test", "dev"];

const PAGE_SIZE = 50;

function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-md px-2.5 py-1 text-table transition-colors ${
        active
          ? "bg-accent text-white"
          : "bg-bg-sunk text-ink-600 hover:bg-bg-hover hover:text-ink-900"
      }`}
    >
      {children}
    </button>
  );
}

export default function RunsScreen() {
  const { days } = useWindowDays();
  const [params] = useSearchParams();

  // Pre-filtered when arrived at from an agent page, so the back-link keeps its meaning.
  const agentId = params.get("agent_id") ?? undefined;

  const [outcomes, setOutcomes] = useState<RunOutcome[]>([]);
  const [environment, setEnvironment] = useState<LifecycleState | undefined>();
  const [escalated, setEscalated] = useState(false);
  const [offset, setOffset] = useState(0);

  const { data, isLoading, isError, error, refetch, isPlaceholderData } = useRuns({
    days,
    agent_id: agentId,
    environment,
    outcome: outcomes,
    escalated,
    limit: PAGE_SIZE,
    offset,
  });

  function toggleOutcome(outcome: RunOutcome) {
    setOffset(0);
    setOutcomes((current) =>
      current.includes(outcome) ? current.filter((o) => o !== outcome) : [...current, outcome],
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Runs"
        explain={`Every execution of every agent over ${windowLabel(days).toLowerCase()}, newest first. One row is one run.`}
        actions={
          agentId ? (
            <Link
              to={`/agents/${agentId}`}
              className="flex items-center gap-1.5 rounded-md bg-bg-sunk px-2.5 py-1.5 text-table text-ink-600 hover:no-underline hover:text-ink-900"
            >
              <Icon name="chevronRight" size={13} className="rotate-180" />
              Back to the agent
            </Link>
          ) : undefined
        }
      />

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-card bg-bg-panel px-4 py-3 shadow-card">
        <div className="flex items-center gap-1.5">
          <span className="mr-1 text-micro font-medium uppercase tracking-wider text-ink-400">
            Outcome
          </span>
          {OUTCOMES.map((outcome) => (
            <Chip
              key={outcome}
              active={outcomes.includes(outcome)}
              onClick={() => toggleOutcome(outcome)}
            >
              {outcome.replace("_", " ")}
            </Chip>
          ))}
        </div>

        <div className="flex items-center gap-1.5">
          <span className="mr-1 text-micro font-medium uppercase tracking-wider text-ink-400">
            Where
          </span>
          {ENVIRONMENTS.map((env) => (
            <Chip
              key={env}
              active={environment === env}
              onClick={() => {
                setOffset(0);
                setEnvironment((current) => (current === env ? undefined : env));
              }}
            >
              {env}
            </Chip>
          ))}
        </div>

        <Chip
          active={escalated}
          onClick={() => {
            setOffset(0);
            setEscalated((v) => !v);
          }}
        >
          Escalated to a human
        </Chip>
      </div>

      <Panel noPadding>
        {isError ? (
          <div className="p-4">
            <ErrorState
              title="Could not load runs"
              message={error instanceof Error ? error.message : "Unknown error"}
              onRetry={() => void refetch()}
            />
          </div>
        ) : isLoading ? (
          <div className="p-4">
            <TableSkeleton rows={10} cols={7} />
          </div>
        ) : (data?.items.length ?? 0) === 0 ? (
          <p className="px-4 py-12 text-center text-body text-ink-400">
            No runs match these filters in {windowLabel(days).toLowerCase()}.
          </p>
        ) : (
          <div className={`overflow-x-auto scrollbar-thin ${isPlaceholderData ? "opacity-60" : ""}`}>
            <table className="min-w-[1000px]">
              <thead>
                <tr>
                  <th className="px-3 py-2">Started</th>
                  <th className="px-3 py-2">Agent</th>
                  <th className="px-3 py-2">Where</th>
                  <th className="px-3 py-2">Outcome</th>
                  <th className="px-3 py-2 text-right">Took</th>
                  <th className="px-3 py-2 text-right">Steps</th>
                  <th className="px-3 py-2 text-right">Tools</th>
                  <th className="px-3 py-2">Model</th>
                  <th className="px-3 py-2 text-right">Tokens</th>
                  <th className="px-3 py-2 text-right">Cost</th>
                  <th className="px-3 py-2">Note</th>
                </tr>
              </thead>
              <tbody>
                {data?.items.map((run) => (
                  <tr key={run.id} className="hover:bg-bg-hover">
                    <td className="whitespace-nowrap px-3 py-2 text-ink-600">
                      <Link to={`/runs/${run.id}`} className="text-ink-900 hover:underline">
                        <RelativeTime iso={run.started_at} />
                      </Link>
                    </td>
                    <td className="px-3 py-2">
                      <Link
                        to={`/agents/${run.agent_id}`}
                        className="text-ink-900 hover:underline"
                      >
                        {run.agent_display_name}
                      </Link>
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
                    <td className="px-3 py-2 font-mono text-micro text-ink-600">
                      {run.model ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-600">
                      {(run.tokens_in + run.tokens_out).toLocaleString()}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-700">
                      {formatUsdMicros(run.cost_micros)}
                    </td>
                    <td className="px-3 py-2">
                      <span className="flex flex-wrap items-center gap-1">
                        {run.escalated ? <Badge label="Escalated" tone="info" /> : null}
                        {run.guardrail_blocks > 0 ? (
                          <Badge label={`${run.guardrail_blocks} blocked`} tone="warn" />
                        ) : null}
                        {/* A classification, never a message. Nothing a model wrote can
                            reach this column. */}
                        {run.error_kind ? <Badge label={run.error_kind} tone="risk" /> : null}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      {data && data.total > PAGE_SIZE ? (
        <Pagination
          total={data.total}
          limit={PAGE_SIZE}
          offset={offset}
          onPageChange={setOffset}
        />
      ) : null}
    </div>
  );
}
