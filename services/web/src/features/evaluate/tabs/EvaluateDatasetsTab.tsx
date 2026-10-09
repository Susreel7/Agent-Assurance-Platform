import { useState } from "react";
import {
  useCreateDataset,
  useEvaluateDatasets,
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

export default function EvaluateDatasetsTab() {
  const { projectId } = useSuiteProject();
  const { data: manifest } = useModules();
  const canConfigure = canConfigureModule(manifest, "evaluate");
  const query = useEvaluateDatasets(projectId);
  const items = useStableSuiteItems(query.data?.items);
  const createMut = useCreateDataset(projectId);

  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [feedback, setFeedback] = useState<{ tone: "success" | "error"; message: string } | null>(
    null,
  );

  if (query.isLoading) return <Skeleton height="10rem" />;

  if (query.isError) {
    return (
      <ErrorState
        message={query.error instanceof Error ? query.error.message : "Could not load datasets"}
        onRetry={() => void query.refetch()}
      />
    );
  }

  return (
    <div className="space-y-4">
      {feedback ? (
        <MutationBanner {...feedback} onDismiss={() => setFeedback(null)} />
      ) : null}
      <Panel title="Datasets">
        {items.length === 0 ? (
          <EmptyState title="No datasets" description="Create a dataset to hold evaluation examples." />
        ) : (
          <ul className="space-y-2 text-sm">
            {items.map((d) => (
              <li key={d.id} className="flex justify-between border-b border-line-100 py-2">
                <span className="font-medium">{d.display_name || d.dataset_key}</span>
                <span className="font-mono-data text-xs text-ink-600">{d.dataset_key}</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      {canConfigure ? (
        <Panel title="Create dataset">
          <form
            className="grid max-w-md gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              createMut.mutate(
                { dataset_key: key, display_name: name, description: "", tags: [] },
                {
                  onSuccess: () => {
                    setFeedback({ tone: "success", message: "Dataset created." });
                    setKey("");
                    setName("");
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
              placeholder="dataset_key"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              required
            />
            <input
              className="rounded-md border border-line-200 px-2 py-1.5 text-sm"
              placeholder="Display name"
              value={name}
              onChange={(e) => setName(e.target.value)}
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
