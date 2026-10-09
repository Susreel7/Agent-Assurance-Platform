import { useState } from "react";
import {
  useCreateAnnotationQueue,
  useEvaluateAnnotationItems,
  useEvaluateAnnotationQueues,
  useModules,
  useStableSuiteItems,
} from "@/api/suiteQueries";
import { canConfigureModule } from "@/lib/suiteModules";
import { useSuiteProject } from "@/features/suite/useSuiteProject";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { MutationBanner } from "@/components/MutationBanner";
import { Panel } from "@/components/Panel";
import { Skeleton } from "@/components/Skeleton";

export default function EvaluateAnnotationTab() {
  const { projectId } = useSuiteProject();
  const { data: manifest } = useModules();
  const canConfigure = canConfigureModule(manifest, "evaluate");
  const queuesQuery = useEvaluateAnnotationQueues(projectId);
  const itemsQuery = useEvaluateAnnotationItems(projectId);
  const queues = useStableSuiteItems(queuesQuery.data?.items);
  const items = useStableSuiteItems(itemsQuery.data?.items);
  const createMut = useCreateAnnotationQueue(projectId);

  const [queueKey, setQueueKey] = useState("");
  const [feedback, setFeedback] = useState<{ tone: "success" | "error"; message: string } | null>(
    null,
  );

  if (queuesQuery.isLoading || itemsQuery.isLoading) return <Skeleton height="10rem" />;

  if (queuesQuery.isError || itemsQuery.isError) {
    const err = queuesQuery.error ?? itemsQuery.error;
    return (
      <ErrorState
        message={err instanceof Error ? err.message : "Could not load annotation data"}
        onRetry={() => {
          void queuesQuery.refetch();
          void itemsQuery.refetch();
        }}
      />
    );
  }

  return (
    <div className="space-y-4">
      {feedback ? (
        <MutationBanner {...feedback} onDismiss={() => setFeedback(null)} />
      ) : null}
      <Panel title="Annotation queues">
        {queues.length === 0 ? (
          <EmptyState title="No queues" description="Human reviewers pull items from a queue." />
        ) : (
          <ul className="space-y-2 text-sm">
            {queues.map((q) => (
              <li key={q.id} className="border-b border-line-100 py-2">
                {q.display_name || q.queue_key}
              </li>
            ))}
          </ul>
        )}
      </Panel>
      <Panel title="Queue items">
        {items.length === 0 ? (
          <EmptyState title="No items" description="Items appear when traces or scores are enqueued." />
        ) : (
          <ul className="space-y-2 text-sm">
            {items.map((item) => (
              <li key={item.id} className="flex justify-between border-b border-line-100 py-2">
                <span className="font-mono-data text-xs">{item.id.slice(0, 8)}</span>
                <span className="text-ink-600">{item.status}</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      {canConfigure ? (
        <Panel title="Create queue">
          <form
            className="flex max-w-md gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              createMut.mutate(
                { queue_key: queueKey, display_name: queueKey, reviewers_required: 1 },
                {
                  onSuccess: () => {
                    setFeedback({ tone: "success", message: "Queue created." });
                    setQueueKey("");
                  },
                  onError: (err) =>
                    setFeedback({
                      tone: "error",
                      message: err instanceof Error ? err.message : "Create failed",
                    }),
                },
              );
            }}
          >
            <input
              className="min-w-0 flex-1 rounded-md border border-line-200 px-2 py-1.5 text-sm"
              placeholder="queue_key"
              value={queueKey}
              onChange={(e) => setQueueKey(e.target.value)}
              required
            />
            <button
              type="submit"
              className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              disabled={createMut.isPending}
            >
              Create
            </button>
          </form>
        </Panel>
      ) : null}
    </div>
  );
}
