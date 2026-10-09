import { useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import GitBranch from "lucide-react/dist/esm/icons/git-branch";
import ListTree from "lucide-react/dist/esm/icons/list-tree";
import Rows3 from "lucide-react/dist/esm/icons/rows-3";
import TimerReset from "lucide-react/dist/esm/icons/timer-reset";
import {
  useObserveExecution,
  useObserveExecutionEvents,
  useObserveExecutionObservations,
} from "@/api/suiteQueries";
import { ErrorState } from "@/components/ErrorState";
import {
  NexusBadge,
  NexusCard,
  NexusMetric,
  NexusPageHeader,
} from "@/components/NexusUI";
import { formatTableDate } from "@/lib/dates";
import { useSuiteProject } from "@/features/suite/useSuiteProject";
import { ExecutionActivityPanel } from "./ExecutionActivityPanel";
import { ExecutionGraphCanvas } from "./ExecutionGraphCanvas";
import { ExecutionInspector } from "./ExecutionInspector";
import { ExecutionSwimlanes } from "./ExecutionSwimlanes";
import { ExecutionTimeline } from "./ExecutionTimeline";
import { ExecutionTree } from "./ExecutionTree";
import {
  buildExecutionGraphItems,
  executionTypeLabel,
  formatDuration,
  normalizeExecutionStatus,
} from "./executionGraphModel";

type View = "graph" | "tree" | "swimlanes" | "waterfall";

export default function ObserveExecutionDetailScreen() {
  const { executionId = "" } = useParams();
  const { projectId } = useSuiteProject();
  const [search, setSearch] = useSearchParams();
  const [view, setView] = useState<View>("graph");
  const detail = useObserveExecution(projectId, executionId);
  const observations = useObserveExecutionObservations(projectId, executionId);
  const events = useObserveExecutionEvents(projectId, executionId);
  const items = useMemo(
    () =>
      buildExecutionGraphItems(
        observations.data?.items ?? [],
        events.data?.items ?? [],
      ),
    [events.data?.items, observations.data?.items],
  );
  const requestedSpan = search.get("span");
  const selectedId =
    requestedSpan && items.some((item) => item.id === requestedSpan)
      ? requestedSpan
      : (items[0]?.id ?? null);
  const selected = items.find((item) => item.id === selectedId) ?? null;

  if (detail.isPending || observations.isPending || events.isPending) {
    return (
      <div className="glass-card min-h-[32rem] animate-pulse rounded-2xl" />
    );
  }

  if (detail.isError || !detail.data || observations.isError || events.isError) {
    const error = detail.error ?? observations.error ?? events.error;
    return (
      <ErrorState
        title="Execution could not be loaded"
        message={error instanceof Error ? error.message : "The execution is unavailable."}
        onRetry={() => {
          void detail.refetch();
          void observations.refetch();
          void events.refetch();
        }}
      />
    );
  }

  const execution = detail.data.execution;
  const status = normalizeExecutionStatus(execution.status);
  const statusTone =
    status === "succeeded"
      ? "ok"
      : status === "failed"
        ? "risk"
        : status === "running"
          ? "info"
          : "warn";
  const select = (id: string) => {
    const next = new URLSearchParams(search);
    next.set("span", id);
    setSearch(next, { replace: true });
  };
  const views: Array<{ id: View; label: string; icon: React.ElementType }> = [
    { id: "graph", label: "Flow graph", icon: GitBranch },
    { id: "tree", label: "Call tree", icon: ListTree },
    { id: "swimlanes", label: "Swimlanes", icon: Rows3 },
    { id: "waterfall", label: "Waterfall", icon: TimerReset },
  ];

  return (
    <div className="space-y-6">
      <NexusPageHeader
        crumbs={["Activity", "Executions", execution.execution_id]}
        title={execution.agent_name ?? "Execution detail"}
        lede={`${execution.execution_id} · initiated by ${execution.initiating_user_id ?? "unattributed"} · effective actor ${execution.effective_actor_id ?? "unknown"}`}
        actions={
          <NexusBadge tone={statusTone}>{executionTypeLabel(status)}</NexusBadge>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <NexusMetric
          label="Started"
          value={execution.start_time ? formatTableDate(execution.start_time) : "—"}
          meta={execution.session_id ? `Session ${execution.session_id}` : "No session ID"}
        />
        <NexusMetric
          label="Duration"
          value={formatDuration(execution.duration_ms)}
          meta={`${execution.span_count} spans · ${events.data.items.length} events`}
        />
        <NexusMetric
          label="Model & tool calls"
          value={`${execution.generation_count} / ${execution.tool_count}`}
          meta={`${execution.mcp_tool_count} MCP · ${execution.sdk_count} SDK`}
        />
        <NexusMetric
          label="Cost"
          value={`$${(execution.total_cost_micros / 1_000_000).toFixed(4)}`}
          meta={`${execution.input_tokens.toLocaleString()} input · ${execution.output_tokens.toLocaleString()} output tokens`}
          tone={execution.error_count > 0 ? "negative" : "default"}
        />
      </div>

      <NexusCard className="min-h-[620px]">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 p-4 dark:border-white/10">
          <div className="flex items-center gap-1 rounded-xl border border-slate-200 bg-slate-100/70 p-1 dark:border-white/10 dark:bg-black/30">
            {views.map((option) => {
              const ViewIcon = option.icon;
              return (
                <button
                  key={option.id}
                  type="button"
                  onClick={() => setView(option.id)}
                  className={`flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-semibold transition-colors ${
                    view === option.id
                      ? "bg-white text-slate-900 dark:bg-white/10 dark:text-white"
                      : "text-slate-500 hover:text-slate-900 dark:hover:text-slate-200"
                  }`}
                >
                  <ViewIcon size={13} />
                  {option.label}
                </button>
              );
            })}
          </div>
          <div className="flex items-center gap-3 text-[10px] font-medium text-slate-500">
            {execution.is_partial ? <NexusBadge tone="warn">Partial capture</NexusBadge> : null}
            {execution.has_cycle ? <NexusBadge tone="warn">Cycle detected</NexusBadge> : null}
            {execution.session_id ? (
              <Link
                to={`/observe/sessions/${encodeURIComponent(execution.session_id)}`}
                className="text-indigo-600 hover:underline dark:text-cyan-400"
              >
                Open session
              </Link>
            ) : null}
            <Link
              to={`/observe/traces/${encodeURIComponent(detail.data.trace_id)}`}
              className="text-indigo-600 hover:underline dark:text-cyan-400"
            >
              Raw trace
            </Link>
          </div>
        </div>

        <div className="grid min-h-[550px] grid-cols-1 lg:grid-cols-[minmax(0,1fr)_340px]">
          <div className="min-h-[550px] min-w-0 overflow-auto border-r border-slate-200 dark:border-white/10">
            {view === "graph" ? (
              <ExecutionGraphCanvas
                items={items}
                selectedId={selectedId}
                onSelect={select}
                hasCycle={execution.has_cycle}
              />
            ) : null}
            {view === "tree" ? (
              <ExecutionTree items={items} selectedId={selectedId} onSelect={select} />
            ) : null}
            {view === "swimlanes" ? (
              <ExecutionSwimlanes items={items} selectedId={selectedId} onSelect={select} />
            ) : null}
            {view === "waterfall" ? (
              <ExecutionTimeline items={items} selectedId={selectedId} onSelect={select} />
            ) : null}
          </div>
          <div className="min-h-[550px] min-w-0 overflow-hidden bg-white/50 dark:bg-black/10">
            <ExecutionInspector
              projectId={projectId}
              traceId={detail.data.trace_id}
              execution={execution}
              item={selected}
            />
          </div>
        </div>
      </NexusCard>

      <ExecutionActivityPanel
        execution={execution}
        observations={observations.data.items}
        events={events.data.items}
        selectedItem={selected}
        onSelect={select}
      />
    </div>
  );
}
