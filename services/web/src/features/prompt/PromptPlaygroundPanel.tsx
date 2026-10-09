import { useState } from "react";
import {
  usePlaygroundRun,
  usePlaygroundRunStatus,
  usePromptArtifacts,
  useStableSuiteItems,
} from "@/api/suiteQueries";
import { useSuiteProject } from "@/features/suite/useSuiteProject";
import { EmptyState } from "@/components/EmptyState";
import { MutationBanner } from "@/components/MutationBanner";
import { Panel } from "@/components/Panel";
import { Skeleton } from "@/components/Skeleton";

export default function PromptPlaygroundPanel() {
  const { projectId } = useSuiteProject();
  const artifactsQuery = usePromptArtifacts(projectId);
  const artifacts = useStableSuiteItems(artifactsQuery.data?.items);

  const runMut = usePlaygroundRun(projectId);
  const [runId, setRunId] = useState("");
  const statusQuery = usePlaygroundRunStatus(projectId, runId);

  const [artifactKey, setArtifactKey] = useState("");
  const [modelAlias, setModelAlias] = useState("default");
  const [feedback, setFeedback] = useState<{ tone: "success" | "error"; message: string } | null>(
    null,
  );

  if (artifactsQuery.isLoading) return <Skeleton height="10rem" />;

  return (
    <div className="space-y-4">
      {feedback ? (
        <MutationBanner {...feedback} onDismiss={() => setFeedback(null)} />
      ) : null}

      <Panel
        title="Playground run"
        explain="Execute a prompt artifact against a model alias (non-streaming)."
      >
        {artifacts.length === 0 ? (
          <EmptyState title="No artifacts" description="Create an artifact before running the playground." />
        ) : (
          <form
            className="grid max-w-lg gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              runMut.mutate(
                {
                  mode: "sync",
                  stream: false,
                  model_alias: modelAlias,
                  artifacts: [{ artifact_key: artifactKey }],
                  variables: {},
                },
                {
                  onSuccess: (res) => {
                    setRunId(res.run_id);
                    setFeedback({ tone: "success", message: "Run started." });
                  },
                  onError: (err) =>
                    setFeedback({
                      tone: "error",
                      message: err instanceof Error ? err.message : "Run failed",
                    }),
                },
              );
            }}
          >
            <label className="text-sm">
              Artifact
              <select
                className="mt-1 w-full rounded-md border border-line-200 px-2 py-1.5"
                value={artifactKey}
                onChange={(e) => setArtifactKey(e.target.value)}
                required
              >
                <option value="">Select…</option>
                {artifacts.map((a) => (
                  <option key={a.id} value={a.artifact_key}>
                    {a.artifact_key}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-sm">
              Model alias
              <input
                className="mt-1 w-full rounded-md border border-line-200 px-2 py-1.5"
                value={modelAlias}
                onChange={(e) => setModelAlias(e.target.value)}
              />
            </label>
            <button
              type="submit"
              className="w-fit rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              disabled={runMut.isPending}
            >
              {runMut.isPending ? "Running…" : "Run"}
            </button>
          </form>
        )}

        {runId && statusQuery.data ? (
          <div className="mt-6 text-sm">
            <p>
              Status: <strong>{statusQuery.data.status}</strong>
            </p>
            {statusQuery.data.error_message ? (
              <p className="mt-2 text-risk-fg">{statusQuery.data.error_message}</p>
            ) : null}
            <dl className="mt-2 grid gap-1 text-xs text-ink-600">
              {statusQuery.data.output_digest ? (
                <div>
                  <dt className="inline">Output digest: </dt>
                  <dd className="inline font-mono-data">{statusQuery.data.output_digest}</dd>
                </div>
              ) : null}
            </dl>
          </div>
        ) : null}
      </Panel>
    </div>
  );
}
