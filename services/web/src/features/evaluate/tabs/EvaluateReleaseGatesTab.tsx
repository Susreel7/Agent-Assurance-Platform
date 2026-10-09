import { useState } from "react";
import {
  useCreateReleaseGate,
  useEvaluateReleaseGate,
  useEvaluateReleaseGates,
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

export default function EvaluateReleaseGatesTab() {
  const { projectId } = useSuiteProject();
  const { data: manifest } = useModules();
  const canConfigure = canConfigureModule(manifest, "evaluate");
  const query = useEvaluateReleaseGates(projectId);
  const items = useStableSuiteItems(query.data?.items);
  const createMut = useCreateReleaseGate(projectId);
  const evaluateMut = useEvaluateReleaseGate(projectId);

  const [gateKey, setGateKey] = useState("");
  const [gateId, setGateId] = useState("");
  const [candidateExperimentId, setCandidateExperimentId] = useState("");
  const [feedback, setFeedback] = useState<{ tone: "success" | "error"; message: string } | null>(
    null,
  );

  if (query.isLoading) return <Skeleton height="10rem" />;

  if (query.isError) {
    return (
      <ErrorState
        message={query.error instanceof Error ? query.error.message : "Could not load release gates"}
        onRetry={() => void query.refetch()}
      />
    );
  }

  return (
    <div className="space-y-4">
      {feedback ? (
        <MutationBanner {...feedback} onDismiss={() => setFeedback(null)} />
      ) : null}
      <Panel title="Release gates">
        {items.length === 0 ? (
          <EmptyState title="No release gates" description="Compare candidate experiments against thresholds before release." />
        ) : (
          <ul className="space-y-2 text-sm">
            {items.map((g) => (
              <li key={g.id} className="flex justify-between border-b border-line-100 py-2">
                <button
                  type="button"
                  className="font-mono-data text-xs text-info-fg underline"
                  onClick={() => setGateId(g.id)}
                >
                  {g.gate_key}
                </button>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      {canConfigure ? (
        <>
          <Panel title="Create gate">
            <form
              className="flex max-w-md gap-2"
              onSubmit={(e) => {
                e.preventDefault();
                createMut.mutate(
                  { gate_key: gateKey, thresholds: {} },
                  {
                    onSuccess: () => {
                      setFeedback({ tone: "success", message: "Release gate created." });
                      setGateKey("");
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
                placeholder="gate_key"
                value={gateKey}
                onChange={(e) => setGateKey(e.target.value)}
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
          <Panel title="Evaluate gate">
            <form
              className="grid max-w-lg gap-3"
              onSubmit={(e) => {
                e.preventDefault();
                if (!gateId) return;
                evaluateMut.mutate(
                  { gateId, payload: { candidate_experiment_id: candidateExperimentId } },
                  {
                    onSuccess: (res) =>
                      setFeedback({
                        tone: res.passed ? "success" : "error",
                        message: res.passed ? "Gate passed." : "Gate failed.",
                      }),
                    onError: (err) =>
                      setFeedback({
                        tone: "error",
                        message: err instanceof Error ? err.message : "Evaluation failed",
                      }),
                  },
                );
              }}
            >
              <input
                className="rounded-md border border-line-200 px-2 py-1.5 font-mono-data text-xs"
                placeholder="gate_id"
                value={gateId}
                onChange={(e) => setGateId(e.target.value)}
                required
              />
              <input
                className="rounded-md border border-line-200 px-2 py-1.5 font-mono-data text-xs"
                placeholder="candidate_experiment_id"
                value={candidateExperimentId}
                onChange={(e) => setCandidateExperimentId(e.target.value)}
                required
              />
              <button
                type="submit"
                className="w-fit rounded-md border border-line-200 px-4 py-2 text-sm disabled:opacity-50"
                disabled={evaluateMut.isPending}
              >
                Evaluate
              </button>
            </form>
            {evaluateMut.data ? (
              <pre className="mt-4 max-h-48 overflow-auto text-xs">
                {JSON.stringify(evaluateMut.data.detail ?? evaluateMut.data, null, 2)}
              </pre>
            ) : null}
          </Panel>
        </>
      ) : null}
    </div>
  );
}
