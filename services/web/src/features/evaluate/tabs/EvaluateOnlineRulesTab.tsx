import { useState } from "react";
import {
  useCreateOnlineRule,
  useEvaluateOnlineRules,
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

export default function EvaluateOnlineRulesTab() {
  const { projectId } = useSuiteProject();
  const { data: manifest } = useModules();
  const canConfigure = canConfigureModule(manifest, "evaluate");
  const query = useEvaluateOnlineRules(projectId);
  const items = useStableSuiteItems(query.data?.items);
  const createMut = useCreateOnlineRule(projectId);

  const [ruleKey, setRuleKey] = useState("");
  const [feedback, setFeedback] = useState<{ tone: "success" | "error"; message: string } | null>(
    null,
  );

  if (query.isLoading) return <Skeleton height="10rem" />;

  if (query.isError) {
    return (
      <ErrorState
        message={query.error instanceof Error ? query.error.message : "Could not load online rules"}
        onRetry={() => void query.refetch()}
      />
    );
  }

  return (
    <div className="space-y-4">
      {feedback ? (
        <MutationBanner {...feedback} onDismiss={() => setFeedback(null)} />
      ) : null}
      <Panel title="Online rules">
        {items.length === 0 ? (
          <EmptyState title="No online rules" description="Sample production traces into evaluators." />
        ) : (
          <ul className="space-y-2 text-sm">
            {items.map((r) => (
              <li key={r.id} className="flex justify-between border-b border-line-100 py-2">
                <span className="font-mono-data text-xs">{r.rule_key}</span>
                <span className="text-ink-600">sample {Math.round(r.sample_rate * 1000) / 10}%</span>
              </li>
            ))}
          </ul>
        )}
      </Panel>
      {canConfigure ? (
        <Panel title="Create rule">
          <form
            className="flex max-w-md flex-wrap gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              createMut.mutate(
                { rule_key: ruleKey, sample_rate: 0.01, max_concurrency: 2 },
                {
                  onSuccess: () => {
                    setFeedback({ tone: "success", message: "Online rule created." });
                    setRuleKey("");
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
              placeholder="rule_key"
              value={ruleKey}
              onChange={(e) => setRuleKey(e.target.value)}
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
