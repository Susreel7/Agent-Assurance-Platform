import { useState } from "react";
import {
  useCreateExperiment,
  useEvaluateExperiments,
  useExperimentResults,
  useModules,
  useStableSuiteItems,
  useStartExperiment,
} from "@/api/suiteQueries";
import { canConfigureModule } from "@/lib/suiteModules";
import { useSuiteProject } from "@/features/suite/useSuiteProject";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { MutationBanner } from "@/components/MutationBanner";
import { Panel } from "@/components/Panel";
import { Skeleton } from "@/components/Skeleton";

export default function EvaluateExperimentsTab() {
  const { projectId } = useSuiteProject();
  const { data: manifest } = useModules();
  const canConfigure = canConfigureModule(manifest, "evaluate");
  const query = useEvaluateExperiments(projectId);
  const items = useStableSuiteItems(query.data?.items);
  const createMut = useCreateExperiment(projectId);
  const startMut = useStartExperiment(projectId);

  const [selectedId, setSelectedId] = useState("");
  const resultsQuery = useExperimentResults(projectId, selectedId);

  const [key, setKey] = useState("");
  const [datasetRevisionId, setDatasetRevisionId] = useState("");
  const [feedback, setFeedback] = useState<{ tone: "success" | "error"; message: string } | null>(
    null,
  );

  if (query.isLoading) return <Skeleton height="10rem" />;

  if (query.isError) {
    return (
      <ErrorState
        message={query.error instanceof Error ? query.error.message : "Could not load experiments"}
        onRetry={() => void query.refetch()}
      />
    );
  }

  return (
    <div className="space-y-4">
      {feedback ? (
        <MutationBanner {...feedback} onDismiss={() => setFeedback(null)} />
      ) : null}
      <Panel title="Experiments">
        {items.length === 0 ? (
          <EmptyState title="No experiments" description="Run offline evaluation against a dataset revision." />
        ) : (
          <ul className="space-y-2 text-sm">
            {items.map((exp) => (
              <li key={exp.id} className="flex flex-wrap items-center gap-2 border-b border-line-100 py-2">
                <button
                  type="button"
                  className="font-medium text-info-fg underline"
                  onClick={() => setSelectedId(exp.id)}
                >
                  {exp.display_name || exp.experiment_key}
                </button>
                <span className="text-ink-600">{exp.status}</span>
                {canConfigure && exp.status === "draft" ? (
                  <button
                    type="button"
                    className="text-xs underline"
                    disabled={startMut.isPending}
                    onClick={() =>
                      startMut.mutate(exp.id, {
                        onSuccess: () =>
                          setFeedback({ tone: "success", message: "Experiment started." }),
                        onError: (err) =>
                          setFeedback({
                            tone: "error",
                            message: err instanceof Error ? err.message : "Start failed",
                          }),
                      })
                    }
                  >
                    Start
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Panel>

      {selectedId && resultsQuery.data ? (
        <Panel title="Results">
          <pre className="max-h-64 overflow-auto text-xs">
            {JSON.stringify(resultsQuery.data, null, 2)}
          </pre>
        </Panel>
      ) : null}

      {canConfigure ? (
        <Panel title="Create experiment (draft)">
          <form
            className="grid max-w-lg gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              createMut.mutate(
                {
                  experiment_key: key,
                  display_name: key,
                  spec: { dataset_revision_id: datasetRevisionId },
                  seed: 0,
                  repetitions: 1,
                  concurrency: 2,
                },
                {
                  onSuccess: () => {
                    setFeedback({ tone: "success", message: "Draft experiment created." });
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
              placeholder="experiment_key"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              required
            />
            <input
              className="rounded-md border border-line-200 px-2 py-1.5 font-mono-data text-xs"
              placeholder="dataset_revision_id (UUID)"
              value={datasetRevisionId}
              onChange={(e) => setDatasetRevisionId(e.target.value)}
              required
            />
            <button
              type="submit"
              className="w-fit rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              disabled={createMut.isPending}
            >
              Create draft
            </button>
          </form>
        </Panel>
      ) : null}
    </div>
  );
}
