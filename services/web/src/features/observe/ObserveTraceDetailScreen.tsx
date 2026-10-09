import { useParams } from "react-router-dom";
import GitBranch from "lucide-react/dist/esm/icons/git-branch";
import { useObserveTraceDetail, useObserveTraceGraph } from "@/api/suiteQueries";
import { useSuiteProject } from "@/features/suite/useSuiteProject";
import { ErrorState } from "@/components/ErrorState";
import {
  NexusBadge,
  NexusCard,
  NexusMetric,
  NexusPageHeader,
} from "@/components/NexusUI";
import { Skeleton } from "@/components/Skeleton";

export default function ObserveTraceDetailScreen() {
  const { traceId = "" } = useParams();
  const { projectId } = useSuiteProject();
  const detailQuery = useObserveTraceDetail(projectId, traceId);
  const graphQuery = useObserveTraceGraph(projectId, traceId);

  if (detailQuery.isLoading) return <Skeleton height="16rem" />;

  if (detailQuery.isError || !detailQuery.data) {
    return (
      <ErrorState
        message={
          detailQuery.error instanceof Error ? detailQuery.error.message : "Trace not found"
        }
        onRetry={() => void detailQuery.refetch()}
      />
    );
  }

  const detail = detailQuery.data;
  const graph = graphQuery.data;
  const errors = detail.spans.filter((span) => span.outcome === "error").length;
  const roots = graph?.nodes.filter((node) => !node.parent_span_id).length ?? 0;

  return (
    <div className="space-y-6">
      <NexusPageHeader
        crumbs={["Activity", "Sessions", "Traces", traceId]}
        title="Trace detail"
        lede={`${traceId} · ${detail.total ?? detail.spans.length} recorded spans`}
        actions={
          <NexusBadge tone={errors > 0 ? "risk" : "ok"}>
            {errors > 0 ? `${errors} span errors` : "No span errors"}
          </NexusBadge>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <NexusMetric label="Recorded spans" value={String(detail.spans.length)} meta={detail.truncated ? "Result truncated" : "Complete result"} />
        <NexusMetric label="Graph nodes" value={graphQuery.isPending ? "—" : String(graph?.nodes.length ?? 0)} meta={`${roots} roots`} />
        <NexusMetric label="Span errors" value={String(errors)} meta="Recorded outcomes" tone={errors > 0 ? "negative" : "positive"} />
        <NexusMetric label="Graph integrity" value={graph?.has_cycle ? "Cycle" : graph?.malformed ? "Malformed" : "Valid"} meta="Parent-link validation" tone={graph?.has_cycle || graph?.malformed ? "negative" : "positive"} />
      </div>

      <NexusCard className="overflow-x-auto">
        <div className="border-b border-slate-200 px-5 py-4 dark:border-white/10">
          <h2 className="text-sm font-bold text-slate-900 dark:text-white">Recorded spans</h2>
          <p className="mt-1 text-xs text-slate-500">Exact operations from Observe; no generated run nodes.</p>
        </div>
        {detail.truncated ? (
          <p className="m-4 rounded-xl border border-amber-500/20 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-300">Span list truncated at server limit.</p>
        ) : null}
        <div className="max-h-[34rem] overflow-auto">
          <table className="min-w-[880px] w-full text-left text-xs">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50/70 text-[10px] uppercase tracking-wide text-slate-500 dark:border-white/10 dark:bg-white/[0.02]">
                {["Span", "Kind", "Operation", "Model / tool", "Duration", "Outcome"].map((heading) => (
                  <th key={heading} className="px-4 py-3 font-semibold">{heading}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-white/5">
              {detail.spans.map((span) => (
                <tr key={span.span_id} className="hover:bg-slate-50 dark:hover:bg-white/[0.03]">
                  <td className="px-4 py-3 font-mono text-slate-700 dark:text-slate-300">{span.span_id}</td>
                  <td className="px-4 py-3 text-slate-500">{span.kind}</td>
                  <td className="px-4 py-3 font-semibold text-slate-800 dark:text-slate-200">{span.operation_name}</td>
                  <td className="px-4 py-3 font-mono text-slate-500">{span.model ?? span.tool_name ?? "—"}</td>
                  <td className="px-4 py-3 font-mono text-slate-500">{span.duration_ms == null ? "—" : `${span.duration_ms.toFixed(1)} ms`}</td>
                  <td className="px-4 py-3"><NexusBadge tone={span.outcome === "error" ? "risk" : "ok"}>{span.outcome ?? "unknown"}</NexusBadge></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </NexusCard>

      <NexusCard>
        <div className="flex items-center gap-2 border-b border-slate-200 px-5 py-4 dark:border-white/10">
          <GitBranch size={15} className="text-indigo-600 dark:text-cyan-400" />
          <h2 className="text-sm font-bold text-slate-900 dark:text-white">Parent-link graph</h2>
        </div>
        {graphQuery.isLoading ? (
          <div className="p-5"><Skeleton height="8rem" /></div>
        ) : graphQuery.isError ? (
          <div className="p-5">
            <ErrorState
              message={graphQuery.error instanceof Error ? graphQuery.error.message : "Graph unavailable"}
              onRetry={() => void graphQuery.refetch()}
            />
          </div>
        ) : graph ? (
          <div className="p-5">
            {graph.has_cycle ? (
              <p className="mb-3 rounded-xl border border-amber-500/20 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-300">Cycle detected in span parent links.</p>
            ) : null}
            <ul className="space-y-2">
              {graph.nodes.map((n) => (
                <li key={n.span_id} className="grid gap-1 rounded-xl border border-slate-200 bg-slate-50/70 px-3 py-2 text-xs dark:border-white/10 dark:bg-white/[0.03] sm:grid-cols-[160px_minmax(0,1fr)]">
                  <span className="font-mono text-slate-500">{n.parent_span_id ? `↳ ${n.parent_span_id.slice(0, 12)}` : "Root"}</span>
                  <span className="font-semibold text-slate-800 dark:text-slate-200">{n.operation_name} <span className="font-normal text-slate-500">· {n.kind}</span></span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
      </NexusCard>
    </div>
  );
}
