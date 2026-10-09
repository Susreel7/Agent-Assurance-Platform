import { useState } from "react";
import {
  useCreateDeployment,
  useDisableDeployment,
  useRouterDeployments,
  useStableSuiteItems,
} from "@/api/suiteQueries";
import type { DeploymentCreate, DeploymentOut } from "@/api/types";
import { useModules } from "@/api/suiteQueries";
import { canConfigureModule } from "@/lib/suiteModules";
import { useSuiteProject } from "@/features/suite/useSuiteProject";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { MutationBanner } from "@/components/MutationBanner";
import { Panel } from "@/components/Panel";
import { Skeleton } from "@/components/Skeleton";
import { formatTableDate } from "@/lib/dates";

const DEFAULT_CREATE: DeploymentCreate = {
  name: "",
  provider: "openai_compatible",
  model: "gpt-4o-mini",
  endpoint: "https://api.example.com/v1",
  credential_ref: "default",
  region: "eu-west-1",
  jurisdiction: "EU",
  capabilities: ["chat"],
  priority: 100,
  weight: 100,
  timeout_ms: 60_000,
  max_retries: 2,
  input_price_micros_per_m: 0,
  output_price_micros_per_m: 0,
  data_classes: [],
};

export default function RouterDeploymentsPanel() {
  const { projectId } = useSuiteProject();
  const { data: manifest } = useModules();
  const canConfigure = canConfigureModule(manifest, "router");

  const query = useRouterDeployments(projectId, true);
  const items = useStableSuiteItems(query.data?.items);

  const createMut = useCreateDeployment(projectId);
  const disableMut = useDisableDeployment(projectId);

  const [draft, setDraft] = useState(DEFAULT_CREATE);
  const [feedback, setFeedback] = useState<{ tone: "success" | "error"; message: string } | null>(
    null,
  );

  const columns: ColumnDef<DeploymentOut>[] = [
    { id: "name", header: "Name", sortValue: (d) => d.name, accessor: (d) => d.name },
    { id: "model", header: "Model", sortValue: (d) => d.model, accessor: (d) => d.model },
    { id: "region", header: "Region", sortValue: (d) => d.region, accessor: (d) => d.region },
    {
      id: "status",
      header: "Status",
      accessor: (d) => (d.disabled_at ? "Disabled" : "Active"),
    },
    {
      id: "updated",
      header: "Updated",
      sortValue: (d) => d.updated_at,
      accessor: (d) => formatTableDate(d.updated_at),
    },
    {
      id: "actions",
      header: "",
      accessor: (d) =>
        canConfigure && !d.disabled_at ? (
          <button
            type="button"
            className="text-sm text-info-fg underline"
            disabled={disableMut.isPending}
            onClick={() => {
              disableMut.mutate(d.id, {
                onSuccess: () =>
                  setFeedback({ tone: "success", message: `Disabled deployment ${d.name}.` }),
                onError: (err) =>
                  setFeedback({
                    tone: "error",
                    message: err instanceof Error ? err.message : "Disable failed",
                  }),
              });
            }}
          >
            Disable
          </button>
        ) : null,
    },
  ];

  if (query.isLoading) return <Skeleton height="14rem" />;

  if (query.isError) {
    return (
      <ErrorState
        message={query.error instanceof Error ? query.error.message : "Could not load deployments"}
        onRetry={() => void query.refetch()}
      />
    );
  }

  return (
    <div className="space-y-4">
      {feedback ? (
        <MutationBanner {...feedback} onDismiss={() => setFeedback(null)} />
      ) : null}

      <Panel
        title="Deployments"
        explain={`${query.data?.total ?? items.length} registered targets`}
      >
        {items.length === 0 ? (
          <EmptyState
            title="No deployments yet"
            description="Register a model endpoint this project can route to."
          />
        ) : (
          <DataTable data={items} columns={columns} rowKey={(d) => d.id} />
        )}
      </Panel>

      {canConfigure ? (
        <Panel title="Add deployment" explain="Minimum fields for a chat-capable target.">
          <form
            className="grid gap-3 md:grid-cols-2"
            onSubmit={(e) => {
              e.preventDefault();
              createMut.mutate(draft, {
                onSuccess: () => {
                  setFeedback({ tone: "success", message: "Deployment created." });
                  setDraft(DEFAULT_CREATE);
                },
                onError: (err) =>
                  setFeedback({
                    tone: "error",
                    message: err instanceof Error ? err.message : "Create failed",
                  }),
              });
            }}
          >
            {(
              [
                ["name", "Name"],
                ["model", "Model"],
                ["endpoint", "Endpoint"],
                ["credential_ref", "Credential ref"],
                ["region", "Region"],
                ["jurisdiction", "Jurisdiction"],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className="block text-sm">
                <span className="font-medium text-ink-900">{label}</span>
                <input
                  className="mt-1 w-full rounded-md border border-line-200 px-2 py-1.5"
                  value={draft[key]}
                  onChange={(e) => setDraft((prev) => ({ ...prev, [key]: e.target.value }))}
                  required={key === "name"}
                />
              </label>
            ))}
            <div className="md:col-span-2">
              <button
                type="submit"
                className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
                disabled={createMut.isPending || !draft.name.trim()}
              >
                {createMut.isPending ? "Creating…" : "Create deployment"}
              </button>
            </div>
          </form>
        </Panel>
      ) : null}
    </div>
  );
}
