import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { useEngagements } from "@/api/queries";
import type { EngagementSummary } from "@/api/types";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { Panel } from "@/components/Panel";
import { Pagination } from "@/components/Pagination";
import { formatPercent, titleCaseSnake } from "@/lib/formatters";

const PAGE_SIZE = 25;

export default function EngagementsListScreen() {
  const [offset, setOffset] = useState(0);
  const navigate = useNavigate();
  const query = useEngagements({ limit: String(PAGE_SIZE), offset: String(offset) });

  const columns: ColumnDef<EngagementSummary>[] = [
    {
      id: "name",
      header: "Engagement",
      sortValue: (e) => e.name,
      accessor: (e) => e.name,
    },
    {
      id: "customer",
      header: "Customer",
      sortValue: (e) => e.customer_display_name,
      accessor: (e) => (
        <Link
          to={`/customers/${e.customer_id}`}
          className="text-info-fg hover:underline"
          onClick={(ev) => ev.stopPropagation()}
        >
          {e.customer_display_name}
        </Link>
      ),
    },
    {
      id: "state",
      header: "State",
      sortValue: (e) => e.state,
      accessor: (e) => titleCaseSnake(e.state),
    },
    {
      id: "agents",
      header: "Agents",
      align: "right",
      sortValue: (e) => e.agent_count,
      accessor: (e) => <span className="tabular-nums">{e.agent_count}</span>,
    },
    {
      id: "regions",
      header: "Permitted regions",
      accessor: (e) => e.permitted_regions.join(", ") || "—",
    },
    {
      id: "slo",
      header: "SLO attainment",
      align: "right",
      sortValue: (e) => e.slo_attainment_pct,
      accessor: (e) => <span className="tabular-nums">{formatPercent(e.slo_attainment_pct)}</span>,
    },
    {
      id: "drift",
      header: "Drift",
      align: "right",
      sortValue: (e) => e.drift_count,
      accessor: (e) => (
        <span className={e.drift_count > 0 ? "tabular-nums font-medium text-risk-fg" : "tabular-nums"}>
          {e.drift_count}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Contracts"
        explain="What you agreed with each client: which agents are in scope, where their data may be processed, and the service levels you promised. Formally called engagements."
      />

      <Panel noPadding>
        <DataTable
          columns={columns}
          data={query.data?.items ?? []}
          rowKey={(e) => e.id}
          isLoading={query.isLoading}
          error={
            query.isError
              ? query.error instanceof Error
                ? query.error.message
                : "Failed to load engagements"
              : null
          }
          onRetry={() => void query.refetch()}
          onRowClick={(e) => navigate(`/engagements/${e.id}`)}
          emptyTitle="No engagements"
        />
        {!query.isLoading && !query.isError && (query.data?.total ?? 0) > PAGE_SIZE ? (
          <Pagination
            offset={offset}
            limit={PAGE_SIZE}
            total={query.data?.total ?? 0}
            onPageChange={setOffset}
          />
        ) : null}
      </Panel>
    </div>
  );
}
