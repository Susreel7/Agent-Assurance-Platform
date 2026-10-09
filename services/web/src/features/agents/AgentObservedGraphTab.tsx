import { useObservedGraph } from "@/api/queries";
import { ErrorState } from "@/components/ErrorState";
import { Panel } from "@/components/Panel";
import { Skeleton } from "@/components/Skeleton";
import { ObservedGraphCanvas } from "@/features/operations/ObservedGraphCanvas";
import { useWindowDays, windowLabel } from "@/lib/windowDays";

type Props = { agentId: string };

export function AgentObservedGraphTab({ agentId }: Props) {
  const { days } = useWindowDays();
  const { data, isLoading, isError, error, refetch } = useObservedGraph(agentId, days);

  if (isLoading) return <Skeleton height="420px" />;
  if (isError || !data) {
    return (
      <ErrorState
        message={error instanceof Error ? error.message : "Could not load observed graph"}
        onRetry={() => void refetch()}
      />
    );
  }

  return (
    <div className="space-y-3">
      <Panel
        title="Observed LangGraph"
        explain={`Node size is executions, edge width is traversals, colour is failure rate — ${windowLabel(days).toLowerCase()}.`}
      >
        {data.nodes.length === 0 ? (
          <p className="py-12 text-center text-body text-ink-400">
            No node executions recorded in this window yet.
          </p>
        ) : (
          <>
            <ObservedGraphCanvas graph={data} />
            <p className="mt-3 text-micro text-ink-400">
              Entry: {data.entry_nodes.join(", ") || "—"} · Terminal:{" "}
              {data.terminal_nodes.join(", ") || "—"}
            </p>
          </>
        )}
      </Panel>
    </div>
  );
}
