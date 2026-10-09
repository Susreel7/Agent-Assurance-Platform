/**
 * LangSmith-style trace waterfall for one run — contract: docs/contracts/tracing.md
 */

import { useEffect, useMemo, useRef } from "react";
import { Link, useParams } from "react-router-dom";
import { useRunDetail } from "@/api/queries";
import { ErrorState } from "@/components/ErrorState";
import { Icon } from "@/components/Icon";
import { Panel } from "@/components/Panel";
import { RelativeTime } from "@/components/RelativeTime";
import { RunOutcomeBadge } from "@/components/StateBadge";
import { Skeleton } from "@/components/Skeleton";
import { formatDuration, formatUsdMicros } from "@/lib/formatters";
import type { RunOutcome, StepKind, StepRow } from "@/api/types";

const KIND_COLOR: Record<StepKind, string> = {
  node: "var(--series-2)",
  llm: "var(--series-3)",
  tool: "var(--series-5)",
  mcp_tool: "var(--series-1)",
  retrieval: "var(--series-4)",
  guardrail: "var(--warn-solid)",
  handoff: "var(--series-6)",
  sub_agent: "var(--info-solid)",
};

const OUTCOME_BAR: Record<RunOutcome, string> = {
  succeeded: "var(--ok-solid)",
  running: "var(--info-solid)",
  failed: "var(--risk-solid)",
  refused: "var(--warn-solid)",
  timed_out: "var(--risk-solid)",
  cancelled: "var(--mute-solid)",
};

function depth(steps: StepRow[], seq: number, cache = new Map<number, number>()): number {
  if (cache.has(seq)) return cache.get(seq)!;
  const step = steps.find((s) => s.seq === seq);
  if (!step || step.parent_seq === null) {
    cache.set(seq, 0);
    return 0;
  }
  const d = depth(steps, step.parent_seq, cache) + 1;
  cache.set(seq, d);
  return d;
}

function runSpan(runStarted: number, runEnd: number) {
  return Math.max(runEnd - runStarted, 1);
}

function TraceRow({
  step,
  indent,
  spanStart,
  spanTotal,
  selfMs,
  rowRef,
}: {
  step: StepRow;
  indent: number;
  spanStart: number;
  spanTotal: number;
  selfMs: number;
  rowRef?: (el: HTMLDivElement | null) => void;
}) {
  const stepStart = new Date(step.started_at).getTime();
  const stepDur = step.duration_ms ?? 0;
  const offsetPct = ((stepStart - spanStart) / spanTotal) * 100;
  const widthPct = Math.max((stepDur / spanTotal) * 100, 0.8);

  return (
    <div
      ref={rowRef}
      className="grid grid-cols-[minmax(0,1fr)_minmax(120px,28%)] items-center gap-3 border-b border-line-200 py-2 pl-2"
      style={{ paddingLeft: `${8 + indent * 16}px` }}
    >
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-mono text-micro text-ink-400">#{step.seq}</span>
          <span className="truncate text-body font-medium text-ink-900">{step.name}</span>
          <span className="rounded-md bg-bg-sunk px-1.5 py-0.5 text-micro text-ink-600">{step.kind}</span>
          {step.server_name ? (
            <span className="text-micro text-ink-400">{step.server_name}</span>
          ) : null}
        </div>
        <dl className="mt-1 flex flex-wrap gap-x-4 gap-y-0.5 text-micro text-ink-600">
          <div>
            <dt className="inline text-ink-400">Duration </dt>
            <dd className="inline font-mono">{formatDuration(step.duration_ms)}</dd>
          </div>
          <div>
            <dt className="inline text-ink-400">Self </dt>
            <dd className="inline font-mono">{formatDuration(selfMs)}</dd>
          </div>
          {step.model ? (
            <div>
              <dt className="inline text-ink-400">Model </dt>
              <dd className="inline font-mono">{step.model}</dd>
            </div>
          ) : null}
          {step.tokens_in + step.tokens_out > 0 ? (
            <div>
              <dt className="inline text-ink-400">Tokens </dt>
              <dd className="inline font-mono">
                {(step.tokens_in + step.tokens_out).toLocaleString()}
              </dd>
            </div>
          ) : null}
          {step.cost_micros > 0 ? (
            <div>
              <dt className="inline text-ink-400">Cost </dt>
              <dd className="inline font-mono">{formatUsdMicros(step.cost_micros)}</dd>
            </div>
          ) : null}
          {step.error_kind ? (
            <div className="text-risk-fg">
              <dt className="inline">Error </dt>
              <dd className="inline font-mono">{step.error_kind}</dd>
            </div>
          ) : null}
        </dl>
      </div>
      <div className="relative h-7 rounded-md bg-bg-sunk">
        <div
          className="absolute top-1/2 h-4 -translate-y-1/2 rounded-sm opacity-90"
          style={{
            left: `${Math.min(offsetPct, 99)}%`,
            width: `${Math.min(widthPct, 100 - offsetPct)}%`,
            background: OUTCOME_BAR[step.outcome] ?? KIND_COLOR[step.kind],
            boxShadow: `inset 0 0 0 1px ${KIND_COLOR[step.kind]}`,
          }}
          title={`${step.outcome} · ${formatDuration(step.duration_ms)}`}
        />
      </div>
    </div>
  );
}

export default function RunDetailScreen() {
  const { runId = "" } = useParams();
  const { data, isLoading, isError, error, refetch } = useRunDetail(runId);
  const failRef = useRef<HTMLDivElement | null>(null);

  const failedSeq = useMemo(() => {
    if (!data) return null;
    const bad = data.steps.find(
      (s) => s.outcome === "failed" || s.outcome === "timed_out" || s.outcome === "refused",
    );
    return bad?.seq ?? null;
  }, [data]);

  useEffect(() => {
    if (!data || failedSeq === null) return;
    failRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [data, failedSeq]);

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton height="2rem" width="40%" />
        <Skeleton height="320px" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <ErrorState
        title="Run not found"
        message={error instanceof Error ? error.message : "Unknown run"}
        onRetry={() => void refetch()}
      />
    );
  }

  const { run, steps, self_ms_by_seq } = data;
  const spanStart = new Date(run.started_at).getTime();
  const spanEnd = run.ended_at
    ? new Date(run.ended_at).getTime()
    : spanStart + (run.duration_ms ?? 0);
  const spanTotal = runSpan(spanStart, spanEnd);
  const depthCache = new Map<number, number>();

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <Link
            to="/runs"
            className="mb-2 inline-flex items-center gap-1 text-table text-ink-600 hover:text-ink-900 hover:no-underline"
          >
            <Icon name="chevronRight" size={14} className="rotate-180" />
            All runs
          </Link>
          <h1 className="text-display font-bold text-ink-900">Run trace</h1>
          <p className="mt-1 text-body text-ink-600">
            <Link to={`/agents/${run.agent_id}`} className="font-medium text-ink-900 hover:underline">
              {run.agent_display_name}
            </Link>
            {" · "}
            <RelativeTime iso={run.started_at} />
            {" · "}
            {formatDuration(run.duration_ms)}
          </p>
        </div>
        <RunOutcomeBadge outcome={run.outcome} />
      </header>

      <Panel title="Waterfall" explain="Rows follow seq and indent by parent_seq; bar position is time within the run span.">
        <div className="mb-2 flex items-center justify-between text-micro text-ink-400">
          <span>{steps.length} steps{data.steps_truncated ? " (truncated)" : ""}</span>
          <span className="font-mono">{formatDuration(run.duration_ms)} total</span>
        </div>
        <div className="max-h-[min(70vh,640px)] overflow-y-auto scrollbar-thin rounded-lg border border-line-200">
          {steps.map((step) => (
            <TraceRow
              key={step.id}
              step={step}
              indent={depth(steps, step.seq, depthCache)}
              spanStart={spanStart}
              spanTotal={spanTotal}
              selfMs={self_ms_by_seq[step.seq] ?? step.duration_ms ?? 0}
              rowRef={
                failedSeq === step.seq
                  ? (el) => {
                      failRef.current = el;
                    }
                  : undefined
              }
            />
          ))}
        </div>
      </Panel>
    </div>
  );
}
