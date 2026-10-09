import { useState } from "react";
import { useRouterRoutes, useSimulateRoute, useStableSuiteItems } from "@/api/suiteQueries";
import { useSuiteProject } from "@/features/suite/useSuiteProject";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { MutationBanner } from "@/components/MutationBanner";
import { Panel } from "@/components/Panel";
import { Skeleton } from "@/components/Skeleton";

export default function RouterSimulatePanel() {
  const { projectId } = useSuiteProject();
  const routesQuery = useRouterRoutes(projectId, true);
  const routes = useStableSuiteItems(routesQuery.data?.items);
  const simulateMut = useSimulateRoute(projectId);

  const [routeId, setRouteId] = useState("");
  const [dataClass, setDataClass] = useState("");
  const [feedback, setFeedback] = useState<{ tone: "success" | "error"; message: string } | null>(
    null,
  );

  if (routesQuery.isLoading) return <Skeleton height="10rem" />;

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

  return (
    <div className="space-y-4">
      {feedback ? (
        <MutationBanner {...feedback} onDismiss={() => setFeedback(null)} />
      ) : null}

      <Panel
        title="Route simulation"
        explain="Check which deployment targets would be eligible for a request profile."
      >
        {routes.length === 0 ? (
          <EmptyState title="No routes to simulate" description="Create a route first." />
        ) : (
          <form
            className="space-y-3 max-w-xl"
            onSubmit={(e) => {
              e.preventDefault();
              if (!routeId) return;
              simulateMut.mutate(
                {
                  routeId,
                  payload: {
                    operation: "chat",
                    data_class: dataClass || null,
                    region_hint: null,
                  },
                },
                {
                  onSuccess: (result) =>
                    setFeedback({
                      tone: "success",
                      message: `Simulation complete — ${result.targets.length} target(s) evaluated.`,
                    }),
                  onError: (err) =>
                    setFeedback({
                      tone: "error",
                      message: err instanceof Error ? err.message : "Simulation failed",
                    }),
                },
              );
            }}
          >
            <label className="block text-sm">
              <span className="font-medium text-ink-900">Route</span>
              <select
                className="mt-1 w-full rounded-md border border-line-200 px-2 py-1.5"
                value={routeId}
                onChange={(e) => setRouteId(e.target.value)}
                required
              >
                <option value="">Select route…</option>
                {routes.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.alias} · {r.environment}
                  </option>
                ))}
              </select>
            </label>
            <label className="block text-sm">
              <span className="font-medium text-ink-900">Data class (optional)</span>
              <input
                className="mt-1 w-full rounded-md border border-line-200 px-2 py-1.5"
                value={dataClass}
                onChange={(e) => setDataClass(e.target.value)}
              />
            </label>
            <button
              type="submit"
              className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              disabled={simulateMut.isPending || !routeId}
            >
              {simulateMut.isPending ? "Simulating…" : "Run simulation"}
            </button>
          </form>
        )}

        {simulateMut.data ? (
          <div className="mt-6 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-line-200 text-left text-ink-600">
                  <th className="py-2 pr-4">Deployment</th>
                  <th className="py-2 pr-4">Eligible</th>
                  <th className="py-2">Reason</th>
                </tr>
              </thead>
              <tbody>
                {simulateMut.data.targets.map((t) => (
                  <tr key={t.deployment_id} className="border-b border-line-100">
                    <td className="py-2 pr-4 font-mono-data text-xs">{t.deployment_id.slice(0, 8)}</td>
                    <td className="py-2 pr-4">{t.eligible ? "Yes" : "No"}</td>
                    <td className="py-2 text-ink-600">{t.reason ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </Panel>
    </div>
  );
}
