import { useState } from "react";
import {
  useCreateScore,
  useEvaluateScores,
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

export default function EvaluateScoresTab() {
  const { projectId } = useSuiteProject();
  const { data: manifest } = useModules();
  const canConfigure = canConfigureModule(manifest, "evaluate");
  const query = useEvaluateScores(projectId);
  const items = useStableSuiteItems(query.data?.items);
  const createMut = useCreateScore(projectId);

  const [targetId, setTargetId] = useState("");
  const [name, setName] = useState("quality");
  const [value, setValue] = useState("1");
  const [feedback, setFeedback] = useState<{ tone: "success" | "error"; message: string } | null>(
    null,
  );

  if (query.isLoading) return <Skeleton height="10rem" />;

  if (query.isError) {
    return (
      <ErrorState
        message={query.error instanceof Error ? query.error.message : "Could not load scores"}
        onRetry={() => void query.refetch()}
      />
    );
  }

  return (
    <div className="space-y-4">
      {feedback ? (
        <MutationBanner {...feedback} onDismiss={() => setFeedback(null)} />
      ) : null}
      <Panel title="Scores">
        {items.length === 0 ? (
          <EmptyState title="No scores" description="Scores attach to traces, examples, or experiment runs." />
        ) : (
          <ul className="space-y-2 text-sm">
            {items.map((s) => (
              <li key={s.id} className="border-b border-line-100 py-2">
                <span className="font-medium">{s.name}</span>
                <span className="ml-2 text-ink-600">
                  {s.target_type}/{s.target_id.slice(0, 12)}
                </span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      {canConfigure ? (
        <Panel title="Record score">
          <form
            className="grid max-w-md gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              createMut.mutate(
                {
                  target_type: "trace",
                  target_id: targetId,
                  name,
                  value_type: "numeric",
                  value_numeric: Number(value),
                  source: "manual",
                },
                {
                  onSuccess: () =>
                    setFeedback({ tone: "success", message: "Score recorded." }),
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
              placeholder="target_id"
              value={targetId}
              onChange={(e) => setTargetId(e.target.value)}
              required
            />
            <input
              className="rounded-md border border-line-200 px-2 py-1.5 text-sm"
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
            <input
              className="rounded-md border border-line-200 px-2 py-1.5 text-sm"
              value={value}
              onChange={(e) => setValue(e.target.value)}
            />
            <button
              type="submit"
              className="w-fit rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              disabled={createMut.isPending}
            >
              Save score
            </button>
          </form>
        </Panel>
      ) : null}
    </div>
  );
}
