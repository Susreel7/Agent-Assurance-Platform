import { useQueries } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { api } from "@/api/client";
import { qk } from "@/api/queries";
import { EMPTY_ITEMS, useCustomers } from "@/api/queries";
import type { CustomerSummary, ReadinessResponse } from "@/api/types";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { Panel } from "@/components/Panel";
import { Pagination } from "@/components/Pagination";
import { formatPercent, titleCaseSnake } from "@/lib/formatters";

const PAGE_SIZE = 25;

export default function CustomersListScreen() {
  const [offset, setOffset] = useState(0);
  const navigate = useNavigate();
  const query = useCustomers({ limit: String(PAGE_SIZE), offset: String(offset) });
  const items = query.data?.items ?? EMPTY_ITEMS;

  const readinessQueries = useQueries({
    queries: items.map((c) => ({
      queryKey: qk.customerReadiness(c.id),
      queryFn: () => api.get<ReadinessResponse>(`/v1/customers/${c.id}/readiness`),
      staleTime: 60_000,
    })),
  });

  const readinessByCustomer = useMemo(() => {
    const map = new Map<string, number>();
    items.forEach((c, i) => {
      const pct = readinessQueries[i]?.data?.coverage_pct;
      if (pct !== undefined) map.set(c.id, pct);
    });
    return map;
  }, [items, readinessQueries]);

  const readinessLoading = readinessQueries.some((q) => q.isLoading);

  const columns: ColumnDef<CustomerSummary>[] = [
    {
      id: "name",
      header: "Customer",
      sortValue: (c) => c.display_name,
      accessor: (c) => c.display_name,
    },
    {
      id: "sector",
      header: "Sector",
      sortValue: (c) => c.sector ?? "",
      accessor: (c) => (c.sector ? titleCaseSnake(c.sector) : "—"),
    },
    {
      id: "jurisdiction",
      header: "Jurisdiction",
      accessor: (c) => c.home_jurisdiction ?? "—",
    },
    {
      id: "criticality",
      header: "Criticality",
      sortValue: (c) => c.criticality,
      accessor: (c) => titleCaseSnake(c.criticality),
    },
    {
      id: "engagements",
      header: "Engagements",
      align: "right",
      sortValue: (c) => c.engagement_count,
      accessor: (c) => <span className="tabular-nums">{c.engagement_count}</span>,
    },
    {
      id: "frameworks",
      header: "Frameworks",
      align: "right",
      sortValue: (c) => c.framework_count,
      accessor: (c) => <span className="tabular-nums">{c.framework_count}</span>,
    },
    {
      id: "readiness",
      header: "Readiness",
      align: "right",
      sortValue: (c) => readinessByCustomer.get(c.id) ?? -1,
      accessor: (c) => {
        const pct = readinessByCustomer.get(c.id);
        if (readinessLoading && pct === undefined) return "…";
        return pct !== undefined ? (
          <span className="tabular-nums">{formatPercent(pct)}</span>
        ) : (
          "—"
        );
      },
    },
    {
      id: "drift",
      header: "Drift",
      align: "right",
      sortValue: (c) => c.drift_count,
      accessor: (c) => (
        <span className={c.drift_count > 0 ? "tabular-nums text-risk-fg font-medium" : "tabular-nums"}>
          {c.drift_count}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Clients"
        explain="The companies you deliver agents to. Each one has its own rules to satisfy, and this shows how much of the proof you can already produce."
      />

      <Panel noPadding>
        <DataTable
          columns={columns}
          data={items}
          rowKey={(c) => c.id}
          isLoading={query.isLoading}
          error={
            query.isError
              ? query.error instanceof Error
                ? query.error.message
                : "Failed to load customers"
              : null
          }
          onRetry={() => void query.refetch()}
          onRowClick={(c) => navigate(`/customers/${c.id}`)}
          emptyTitle="No customers"
          emptyDescription="No customer records in this tenant."
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
