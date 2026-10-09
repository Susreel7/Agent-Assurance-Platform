import { useState } from "react";
import {
  useCreateEvaluator,
  useEvaluateEvaluators,
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

export default function EvaluateEvaluatorsTab() {
  const { projectId } = useSuiteProject();
  const { data: manifest } = useModules();
  const canConfigure = canConfigureModule(manifest, "evaluate");
  const query = useEvaluateEvaluators(projectId);
  const items = useStableSuiteItems(query.data?.items);
  const createMut = useCreateEvaluator(projectId);

  const [key, setKey] = useState("");
  const [kind, setKind] = useState("llm_judge");
  const [feedback, setFeedback] = useState<{ tone: "success" | "error"; message: string } | null>(
    null,
  );

  if (query.isLoading) return <Skeleton height="10rem" />;

  if (query.isError) {
    return (
      <ErrorState
        message={query.error instanceof Error ? query.error.message : "Could not load evaluators"}
        onRetry={() => void query.refetch()}
      />
    );
  }

  return (
    <div className="space-y-4">
      {feedback ? (
        <MutationBanner {...feedback} onDismiss={() => setFeedback(null)} />
      ) : null}
      <Panel title="Evaluators">
        {items.length === 0 ? (
          <EmptyState title="No evaluators" description="Define scoring functions for experiments and online rules." />
        ) : (
          <ul className="space-y-2 text-sm">
            {items.map((ev) => (
              <li key={ev.id} className="flex justify-between border-b border-line-100 py-2">
                <span>{ev.display_name || ev.evaluator_key}</span>
                <span className="text-ink-600">{ev.kind}</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      {canConfigure ? (
        <Panel title="Create evaluator">
          <form
            className="grid max-w-md gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              createMut.mutate(
                { evaluator_key: key, display_name: key, kind, config: {} },
                {
                  onSuccess: () => {
                    setFeedback({ tone: "success", message: "Evaluator created." });
                    setKey("");
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
              className="rounded-md border border-line-200 px-2 py-1.5 text-sm"
              placeholder="evaluator_key"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              required
            />
            <input
              className="rounded-md border border-line-200 px-2 py-1.5 text-sm"
              value={kind}
              onChange={(e) => setKind(e.target.value)}
            />
            <button
              type="submit"
              className="w-fit rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
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
