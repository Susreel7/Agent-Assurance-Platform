import type { FormEvent } from "react";
import {
  useObserveAnalytics,
  useObserveSamplingPolicy,
  useUpdateObserveSamplingPolicy,
} from "@/api/suiteQueries";
import type { ExecutionAnalytics, SamplingPolicyUpdate } from "@/api/types";
import { ErrorState } from "@/components/ErrorState";
import { NexusPageHeader } from "@/components/NexusUI";
import { Panel } from "@/components/Panel";
import { Skeleton } from "@/components/Skeleton";
import { useSuiteProject } from "@/features/suite/useSuiteProject";
import { formatTableDate } from "@/lib/dates";
import { formatDuration } from "./executionGraphModel";

type Breakdown = NonNullable<ExecutionAnalytics["by_agent"]>;

function percentage(value?: number | null): string {
  return value == null ? "Unknown" : `${(value * 100).toFixed(1)}%`;
}

function money(micros: number): string {
  return micros > 0 ? `$${(micros / 1_000_000).toFixed(2)}` : "$0.00";
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="border-r border-line-200 px-3 py-2.5 last:border-r-0">
      <p className="text-micro uppercase tracking-wide text-ink-400">{label}</p>
      <p className="mt-1 font-mono-data text-sm font-semibold text-ink-900">{value}</p>
    </div>
  );
}

function BreakdownList({ title, items }: { title: string; items: Breakdown }) {
  const maximum = Math.max(1, ...items.map((item) => item.count));
  return (
    <section className="min-w-0 border border-line-200 bg-bg-panel">
      <div className="border-b border-line-200 px-3 py-2">
        <h3 className="text-xs font-semibold text-ink-900">{title}</h3>
      </div>
      {items.length > 0 ? (
        <div>
          {items.slice(0, 8).map((item) => (
            <div key={item.label} className="border-b border-line-100 px-3 py-2 last:border-b-0">
              <div className="flex items-center justify-between gap-3 text-xs">
                <span className="min-w-0 truncate text-ink-700">{item.label}</span>
                <span className="shrink-0 font-mono-data text-ink-500">{item.count}</span>
              </div>
              <div className="mt-1 h-1 bg-bg-sunk">
                <div
                  className="h-full bg-ink-400"
                  style={{ width: `${(item.count / maximum) * 100}%` }}
                />
              </div>
              <div className="mt-1 flex justify-between text-micro text-ink-400">
                <span>{item.failed_count} failed</span>
                <span>{formatDuration(item.avg_duration_ms)} avg</span>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="p-3 text-xs text-ink-400">No observed data.</p>
      )}
    </section>
  );
}

export default function ObserveAnalyticsPanel() {
  const { projectId } = useSuiteProject();
  const analyticsQuery = useObserveAnalytics(projectId);
  const policyQuery = useObserveSamplingPolicy(projectId);
  const updatePolicy = useUpdateObserveSamplingPolicy(projectId);

  if (analyticsQuery.isLoading) return <Skeleton height="32rem" />;
  if (analyticsQuery.isError || !analyticsQuery.data) {
    return (
      <ErrorState
        message={
          analyticsQuery.error instanceof Error
            ? analyticsQuery.error.message
            : "Analytics are unavailable"
        }
        onRetry={() => void analyticsQuery.refetch()}
      />
    );
  }

  const analytics = analyticsQuery.data;
  const pipeline = analytics.pipeline ?? {
    pending_manifests: 0,
    processing_manifests: 0,
    quarantined_manifests: 0,
    processed_24h: 0,
    pending_projections: 0,
    partial_executions: 0,
    malformed_executions: 0,
    late_executions: 0,
    last_manifest_at: null,
  };
  const policy = policyQuery.data;
  const submitPolicy = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const data = new FormData(event.currentTarget);
    const payload: SamplingPolicyUpdate = {
      head_sample_rate: Number(data.get("sample_rate") ?? 100) / 100,
      tail_keep_errors: data.has("tail_keep_errors"),
      tail_keep_retries: data.has("tail_keep_retries"),
      tail_keep_high_latency: data.has("tail_keep_high_latency"),
      high_latency_ms: Number(data.get("high_latency_ms") ?? 10000),
      max_traces_per_minute: data.get("max_traces_per_minute")
        ? Number(data.get("max_traces_per_minute"))
        : null,
    };
    updatePolicy.mutate(payload);
  };

  return (
    <div className="space-y-4">
      <NexusPageHeader
        crumbs={["Activity", "People activity"]}
        title="People activity"
        lede="Live usage, cost, model, tool, MCP, SDK, reliability, and pipeline rollups for people and agents in the selected project."
      />
      <Panel
        title="Execution analytics"
        explain={`${analytics.population_label}. Unknown values are not displayed as zero.`}
        noPadding
      >
        <div className="grid grid-cols-2 gap-px bg-line-200 sm:grid-cols-4 lg:grid-cols-8">
          <Metric label="Executions" value={analytics.execution_count} />
          <Metric label="Sessions" value={analytics.session_count} />
          <Metric label="Users" value={analytics.user_count} />
          <Metric label="Agents" value={analytics.agent_count} />
          <Metric label="Success" value={percentage(analytics.success_rate)} />
          <Metric label="p95" value={formatDuration(analytics.p95_duration_ms)} />
          <Metric label="Retries" value={analytics.retry_count} />
          <Metric label="Cost" value={money(analytics.total_cost_micros)} />
        </div>
        <div className="grid grid-cols-2 gap-px border-t border-line-200 bg-line-200 sm:grid-cols-4 lg:grid-cols-8">
          <Metric label="Average" value={formatDuration(analytics.avg_duration_ms)} />
          <Metric label="p50" value={formatDuration(analytics.p50_duration_ms)} />
          <Metric label="p90" value={formatDuration(analytics.p90_duration_ms)} />
          <Metric label="p99" value={formatDuration(analytics.p99_duration_ms)} />
          <Metric label="Failures" value={analytics.failed_count} />
          <Metric label="Errors" value={analytics.error_count} />
          <Metric
            label="Tokens"
            value={(analytics.input_tokens + analytics.output_tokens).toLocaleString()}
          />
          <Metric label="Actors" value={analytics.actor_count} />
        </div>
      </Panel>

      <div className="grid gap-3 lg:grid-cols-3">
        <BreakdownList title="Agents" items={analytics.by_agent ?? []} />
        <BreakdownList title="Users invoking agents" items={analytics.by_user ?? []} />
        <BreakdownList title="Environments" items={analytics.by_environment ?? []} />
        <BreakdownList title="Models" items={analytics.by_model ?? []} />
        <BreakdownList title="Tools" items={analytics.by_tool ?? []} />
        <BreakdownList title="SDK operations" items={analytics.by_sdk ?? []} />
        <BreakdownList title="MCP activity" items={analytics.by_mcp ?? []} />
        <BreakdownList title="Invocation sources" items={analytics.by_source ?? []} />
        <BreakdownList title="Frameworks" items={analytics.by_framework ?? []} />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <Panel title="Observe pipeline" explain="Durability, projection, and trace-integrity signals.">
          <dl className="grid grid-cols-2 gap-px border border-line-200 bg-line-200 sm:grid-cols-4">
            {[
              ["Pending ingest", pipeline.pending_manifests],
              ["Processing", pipeline.processing_manifests],
              ["Quarantined", pipeline.quarantined_manifests],
              ["Processed (24h)", pipeline.processed_24h],
              ["Projection backlog", pipeline.pending_projections],
              ["Partial", pipeline.partial_executions],
              ["Malformed", pipeline.malformed_executions],
              ["Late data", pipeline.late_executions],
            ].map(([label, value]) => (
              <div key={label} className="bg-bg-panel p-3">
                <dt className="text-micro uppercase tracking-wide text-ink-400">{label}</dt>
                <dd className="mt-1 font-mono-data text-sm font-semibold text-ink-900">
                  {value}
                </dd>
              </div>
            ))}
          </dl>
          <p className="mt-3 text-micro text-ink-400">
            Last envelope:{" "}
            {pipeline.last_manifest_at
              ? formatTableDate(pipeline.last_manifest_at)
              : "No ingest observed"}
          </p>
        </Panel>

        <Panel
          title="Sampling controls"
          explain="Head sampling is deterministic. Tail preservation protects important traces."
        >
          {policyQuery.isLoading ? (
            <Skeleton height="14rem" />
          ) : policy ? (
            <form key={policy.revision} onSubmit={submitPolicy} className="space-y-3 text-xs">
              <label className="block">
                <span className="text-ink-600">Head sample rate (%)</span>
                <input
                  name="sample_rate"
                  type="number"
                  min="0"
                  max="100"
                  step="0.1"
                  defaultValue={policy.head_sample_rate * 100}
                  className="mt-1 h-8 w-full border border-line-200 px-2 outline-none focus:border-info-fg"
                />
              </label>
              <label className="flex items-center gap-2 text-ink-700">
                <input
                  name="tail_keep_errors"
                  type="checkbox"
                  defaultChecked={policy.tail_keep_errors}
                />
                Always preserve failed executions
              </label>
              <label className="flex items-center gap-2 text-ink-700">
                <input
                  name="tail_keep_retries"
                  type="checkbox"
                  defaultChecked={policy.tail_keep_retries}
                />
                Always preserve retried executions
              </label>
              <label className="flex items-center gap-2 text-ink-700">
                <input
                  name="tail_keep_high_latency"
                  type="checkbox"
                  defaultChecked={policy.tail_keep_high_latency}
                />
                Preserve high-latency executions
              </label>
              <label className="block">
                <span className="text-ink-600">High-latency threshold (ms)</span>
                <input
                  name="high_latency_ms"
                  type="number"
                  min="1"
                  defaultValue={policy.high_latency_ms}
                  className="mt-1 h-8 w-full border border-line-200 px-2 outline-none focus:border-info-fg"
                />
              </label>
              <label className="block">
                <span className="text-ink-600">Maximum traces / minute (optional)</span>
                <input
                  name="max_traces_per_minute"
                  type="number"
                  min="1"
                  defaultValue={policy.max_traces_per_minute ?? ""}
                  className="mt-1 h-8 w-full border border-line-200 px-2 outline-none focus:border-info-fg"
                />
              </label>
              <button
                type="submit"
                disabled={updatePolicy.isPending}
                className="h-8 border border-ink-700 bg-ink-900 px-3 text-xs text-white disabled:opacity-50"
              >
                {updatePolicy.isPending ? "Saving…" : "Save sampling policy"}
              </button>
              {updatePolicy.isError ? (
                <p className="text-risk-fg">Sampling policy could not be saved.</p>
              ) : null}
            </form>
          ) : (
            <p className="text-xs text-ink-400">Sampling policy is unavailable.</p>
          )}
        </Panel>
      </div>
    </div>
  );
}
