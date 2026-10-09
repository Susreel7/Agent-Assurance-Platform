import { useMemo, useState } from "react";
import { useAgents } from "@/api/queries";
import {
  useCreateRoute,
  useModules,
  useRouterDeployments,
  useRouterRoutes,
  useStableSuiteItems,
} from "@/api/suiteQueries";
import type { RouteCreate, RouteOut } from "@/api/types";
import { canConfigureModule } from "@/lib/suiteModules";
import { useSuiteProject } from "@/features/suite/useSuiteProject";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { MutationBanner } from "@/components/MutationBanner";
import { Panel } from "@/components/Panel";
import { Skeleton } from "@/components/Skeleton";

export default function RouterRoutesPanel() {
  const { projectId } = useSuiteProject();
  const { data: manifest } = useModules();
  const canConfigure = canConfigureModule(manifest, "router");

  const routesQuery = useRouterRoutes(projectId, true);
  const deploymentsQuery = useRouterDeployments(projectId, true);
  const agentsQuery = useAgents({ limit: "100" });

  const routes = useStableSuiteItems(routesQuery.data?.items);
  const deployments = useStableSuiteItems(deploymentsQuery.data?.items);
  const agents = useStableSuiteItems(agentsQuery.data?.items);

  const createMut = useCreateRoute(projectId);

  const [agentId, setAgentId] = useState("");
  const [deploymentId, setDeploymentId] = useState("");
  const [alias, setAlias] = useState("default");
  const [feedback, setFeedback] = useState<{ tone: "success" | "error"; message: string } | null>(
    null,
  );

  const columns: ColumnDef<RouteOut>[] = useMemo(
    () => [
      { id: "alias", header: "Alias", sortValue: (r) => r.alias, accessor: (r) => r.alias },
      {
        id: "env",
        header: "Environment",
        sortValue: (r) => r.environment,
        accessor: (r) => r.environment,
      },
      {
        id: "agent",
        header: "Agent",
        accessor: (r) => r.agent_id.slice(0, 8),
      },
      {
        id: "targets",
        header: "Targets",
        accessor: (r) => r.targets.length,
      },
      {
        id: "status",
        header: "Status",
        accessor: (r) => (r.disabled_at ? "Disabled" : "Active"),
      },
    ],
    [],
  );

  if (routesQuery.isLoading) return <Skeleton height="14rem" />;

  if (routesQuery.isError) {
    return (
      <ErrorState
        message={
          routesQuery.error instanceof Error ? routesQuery.error.message : "Could not load routes"
        }
        onRetry={() => void routesQuery.refetch()}
      />
    );
  }

  const draft: RouteCreate | null =
    agentId && deploymentId
      ? {
          agent_id: agentId,
          environment: "production",
          alias,
          strategy: "priority",
          enforcement: "advisory",
          targets: [{ deployment_id: deploymentId, position: 0 }],
          permitted_regions: [],
          data_classes: [],
          fallback_before_first_byte: true,
          max_attempts: 3,
          response_cache_enabled: false,
        }
      : null;

  return (
    <div className="space-y-4">
      {feedback ? (
        <MutationBanner {...feedback} onDismiss={() => setFeedback(null)} />
      ) : null}

      <Panel title="Routes" explain="Agent-scoped model aliases and target ordering.">
        {routes.length === 0 ? (
          <EmptyState title="No routes" description="Create a route once deployments exist." />
        ) : (
          <DataTable data={routes} columns={columns} rowKey={(r) => r.id} />
        )}
      </Panel>

      {canConfigure ? (
        <Panel title="Create route" explain="Bind an agent alias to a deployment target.">
          <form
            className="grid gap-3 md:grid-cols-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (!draft) return;
              createMut.mutate(draft, {
                onSuccess: () => setFeedback({ tone: "success", message: "Route created." }),
                onError: (err) =>
                  setFeedback({
                    tone: "error",
                    message: err instanceof Error ? err.message : "Create failed",
                  }),
              });
            }}
          >
            <label className="block text-sm">
              <span className="font-medium text-ink-900">Agent</span>
              <select
                className="mt-1 w-full rounded-md border border-line-200 px-2 py-1.5"
                value={agentId}
                onChange={(e) => setAgentId(e.target.value)}
                required
              >
                <option value="">Select agent…</option>
                {agents.map((a) => (
                  <option key={a.id} value={a.id}>
                    {a.display_name || a.urn}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              <span className="font-medium text-ink-900">Deployment</span>
              <select
                className="mt-1 w-full rounded-md border border-line-200 px-2 py-1.5"
                value={deploymentId}
                onChange={(e) => setDeploymentId(e.target.value)}
                required
              >
                <option value="">Select deployment…</option>
                {deployments.map((d) => (
                  <option key={d.id} value={d.id} disabled={Boolean(d.disabled_at)}>
                    {d.name} ({d.model})
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm md:col-span-2">
              <span className="font-medium text-ink-900">Alias</span>
              <input
                className="mt-1 w-full rounded-md border border-line-200 px-2 py-1.5"
                value={alias}
                onChange={(e) => setAlias(e.target.value)}
              />
            </label>
            <div className="md:col-span-2">
              <button
                type="submit"
                className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
                disabled={createMut.isPending || !draft}
              >
                {createMut.isPending ? "Creating…" : "Create route"}
              </button>
            </div>
          </form>
        </Panel>
      ) : null}
    </div>
  );
}
