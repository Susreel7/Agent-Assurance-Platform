import { useState } from "react";
import { useCompileRouterSnapshot, useModules } from "@/api/suiteQueries";
import { canConfigureModule } from "@/lib/suiteModules";
import { useSuiteProject } from "@/features/suite/useSuiteProject";
import { EmptyState } from "@/components/EmptyState";
import { MutationBanner } from "@/components/MutationBanner";
import { Panel } from "@/components/Panel";
import { formatTableDate } from "@/lib/dates";

export default function RouterCompilePanel() {
  const { projectId } = useSuiteProject();
  const { data: manifest } = useModules();
  const canConfigure = canConfigureModule(manifest, "router");
  const compileMut = useCompileRouterSnapshot(projectId);

  const [feedback, setFeedback] = useState<{ tone: "success" | "error"; message: string } | null>(
    null,
  );

  if (!canConfigure) {
    return (
      <EmptyState
        title="Read-only"
        description="Your entitlement allows viewing router state but not compiling new signed snapshots."
      />
    );
  }

  return (
    <div className="space-y-4">
      {feedback ? (
        <MutationBanner {...feedback} onDismiss={() => setFeedback(null)} />
      ) : null}

      <Panel
        title="Compile configuration"
        explain="Build and sign the gateway snapshot for this project from current routes and deployments."
      >
        <button
          type="button"
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
          disabled={compileMut.isPending}
          onClick={() =>
            compileMut.mutate(
              {},
              {
                onSuccess: () =>
                  setFeedback({ tone: "success", message: "Snapshot compiled and signed." }),
                onError: (err) =>
                  setFeedback({
                    tone: "error",
                    message: err instanceof Error ? err.message : "Compile failed",
                  }),
              },
            )
          }
        >
          {compileMut.isPending ? "Compiling…" : "Compile snapshot"}
        </button>

        {compileMut.data ? (
          <dl className="mt-6 grid gap-2 text-sm md:grid-cols-2">
            <div>
              <dt className="text-ink-600">Snapshot ID</dt>
              <dd className="font-mono-data text-xs">{compileMut.data.id}</dd>
            </div>
            <div>
              <dt className="text-ink-600">Config digest</dt>
              <dd className="font-mono-data text-xs break-all">{compileMut.data.config_digest}</dd>
            </div>
            <div>
              <dt className="text-ink-600">Rules digest</dt>
              <dd className="font-mono-data text-xs break-all">{compileMut.data.rules_digest}</dd>
            </div>
            <div>
              <dt className="text-ink-600">Issued at</dt>
              <dd>{formatTableDate(compileMut.data.issued_at)}</dd>
            </div>
          </dl>
        ) : null}
      </Panel>
    </div>
  );
}
