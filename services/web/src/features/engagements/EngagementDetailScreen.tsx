import { Link, useParams } from "react-router-dom";
import { useEngagement } from "@/api/queries";
import type { EngagementAgent } from "@/api/types";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { ErrorState } from "@/components/ErrorState";
import { Panel } from "@/components/Panel";
import { Skeleton } from "@/components/Skeleton";
import { Urn } from "@/components/Urn";
import { formatPercent, formatSemverRange, titleCaseSnake } from "@/lib/formatters";

function DriftMarker({ row }: { row: EngagementAgent }) {
  if (!row.has_drift) return <span className="text-ink-400">—</span>;
  return (
    <span
      className="rounded-sm bg-risk-bg px-2 py-0.5 text-xs font-semibold text-risk-fg"
      title="Accreditation drift — deployed version differs from accredited version"
    >
      DRIFT
    </span>
  );
}

export default function EngagementDetailScreen() {
  const { engagementId = "" } = useParams();
  const query = useEngagement(engagementId);

  if (query.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton height="2rem" width="55%" />
        <Skeleton height="14rem" />
      </div>
    );
  }

  if (query.isError || !query.data) {
    return (
      <ErrorState
        message={query.error instanceof Error ? query.error.message : "Engagement not found"}
        onRetry={() => void query.refetch()}
      />
    );
  }

  const engagement = query.data;
  const driftAgents = engagement.agents.filter((a) => a.has_drift);

  const agentColumns: ColumnDef<EngagementAgent>[] = [
    {
      id: "agent",
      header: "Agent",
      sortValue: (a) => a.agent_display_name,
      accessor: (a) => (
        <div>
          <Link to={`/agents/${a.agent_id}`} className="font-medium text-ink-900 hover:underline">
            {a.agent_display_name}
          </Link>
          <div>
            <Urn value={a.agent_urn} />
          </div>
        </div>
      ),
    },
    {
      id: "accredited",
      header: "Accredited version",
      sortValue: (a) => a.accredited_semver ?? "",
      accessor: (a) => (
        <span className="font-mono-data tabular-nums">{a.accredited_semver ?? "—"}</span>
      ),
    },
    {
      id: "deployed",
      header: "Deployed version",
      sortValue: (a) => a.deployed_semver ?? "",
      accessor: (a) => (
        <span
          className={
            a.has_drift
              ? "font-mono-data tabular-nums font-semibold text-risk-fg"
              : "font-mono-data tabular-nums"
          }
        >
          {a.deployed_semver ?? "—"}
        </span>
      ),
    },
    {
      id: "drift",
      header: "Accreditation drift",
      sortValue: (a) => (a.has_drift ? 1 : 0),
      accessor: (a) => <DriftMarker row={a} />,
    },
    {
      id: "uptake",
      header: "Version uptake",
      accessor: (a) => titleCaseSnake(a.uptake),
    },
  ];

  return (
    <div className="space-y-4">
      <header className="space-y-2">
        <p className="text-xs text-ink-400">{engagement.slug}</p>
        <h1 className="text-lg font-semibold text-ink-900">{engagement.name}</h1>
        <p className="text-table text-ink-600">
          Customer{" "}
          <Link to={`/customers/${engagement.customer_id}`} className="text-info-fg hover:underline">
            {engagement.customer_display_name}
          </Link>{" "}
          · {titleCaseSnake(engagement.state)} · SLO {formatPercent(engagement.slo_attainment_pct)}
        </p>
        {driftAgents.length > 0 ? (
          <p className="rounded-sm border border-risk-fg/30 bg-risk-bg px-3 py-2 text-table text-risk-fg">
            {driftAgents.length} agent{driftAgents.length === 1 ? "" : "s"} in scope with accreditation
            drift:{" "}
            {driftAgents.map((a, i) => (
              <span key={a.id}>
                {i > 0 ? "; " : ""}
                {a.agent_display_name} ({formatSemverRange(a.accredited_semver, a.deployed_semver ?? "?")})
              </span>
            ))}
          </p>
        ) : null}
      </header>

      <Panel title="Agent scope" noPadding>
        <DataTable
          columns={agentColumns}
          data={engagement.agents}
          rowKey={(a) => a.id}
          emptyTitle="No agents in scope"
        />
      </Panel>

      <div className="grid gap-4 md:grid-cols-2">
        <Panel title="Residency">
          <dl className="space-y-2 text-table">
            <div>
              <dt className="text-ink-400">Permitted regions</dt>
              <dd>{engagement.permitted_regions.join(", ") || "—"}</dd>
            </div>
            <div>
              <dt className="text-ink-400">Prohibited regions</dt>
              <dd>{engagement.prohibited_regions.join(", ") || "—"}</dd>
            </div>
            <div>
              <dt className="text-ink-400">Cross-border transfer</dt>
              <dd>{titleCaseSnake(engagement.cross_border_transfer)}</dd>
            </div>
          </dl>
        </Panel>
        <Panel title="Service levels">
          {engagement.service_levels.length === 0 ? (
            <p className="text-table text-ink-600">No SLO definitions on this engagement.</p>
          ) : (
            <ul className="space-y-2 text-table">
              {engagement.service_levels.map((slo) => (
                <li key={slo.id}>
                  {titleCaseSnake(slo.kind)} — target {slo.target}
                  {slo.unit ? ` ${slo.unit}` : ""} ({titleCaseSnake(slo.measurement_window)})
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <p className="text-table text-ink-600">
        This client&rsquo;s own page, which you can share with them:{" "}
        <Link
          to={`/portal/${engagement.customer_slug}/${engagement.slug}`}
          className="text-info-fg hover:underline"
        >
          /portal/{engagement.customer_slug}/{engagement.slug}
        </Link>
      </p>
    </div>
  );
}
