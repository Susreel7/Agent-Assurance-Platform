import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { useReleases } from "@/api/queries";
import type { ReleaseSummary } from "@/api/types";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { Panel } from "@/components/Panel";
import { Pagination } from "@/components/Pagination";
import { ReleaseStateBadge } from "@/components/StateBadge";
import { Urn } from "@/components/Urn";
import { RelativeTime } from "@/components/RelativeTime";
import { formatSemverRange } from "@/lib/formatters";
import {
  accreditationImpactLabel,
  accreditationImpactTone,
} from "@/lib/materiality";
const PAGE_SIZE = 25;

export default function ReleasesListScreen() {
  const [offset, setOffset] = useState(0);
  const navigate = useNavigate();
  const query = useReleases({ limit: String(PAGE_SIZE), offset: String(offset) });

  const columns: ColumnDef<ReleaseSummary>[] = [
    {
      id: "tag",
      header: "Release",
      sortValue: (r) => r.release_tag,
      accessor: (r) => (
        <span className="font-mono-data text-table">{r.release_tag}</span>
      ),
    },
    {
      id: "agent",
      header: "Agent",
      sortValue: (r) => r.agent_urn,
      accessor: (r) => <Urn value={r.agent_urn} />,
    },
    {
      id: "range",
      header: "Version",
      accessor: (r) => (
        <span className="font-mono-data tabular-nums text-table">
          {formatSemverRange(r.from_semver, r.to_semver)}
        </span>
      ),
    },
    {
      id: "state",
      header: "State",
      sortValue: (r) => r.state,
      accessor: (r) => <ReleaseStateBadge state={r.state} />,
    },
    {
      id: "changes",
      header: "Changes",
      align: "right",
      sortValue: (r) => r.change_count,
      accessor: (r) => (
        <span className="tabular-nums">
          {r.change_count}
          {r.material_count > 0 ? (
            <span className="text-risk-fg"> ({r.material_count} material)</span>
          ) : null}
        </span>
      ),
    },
    {
      id: "accreditation",
      header: "Accreditation",
      accessor: (r) => {
        const tone = accreditationImpactTone(r.accreditation_impact);
        const cls =
          tone === "risk" ? "text-risk-fg" : tone === "warn" ? "text-warn-fg" : "text-ink-600";
        return <span className={cls}>{accreditationImpactLabel(r.accreditation_impact)}</span>;
      },
    },
    {
      id: "created",
      header: "Created",
      sortValue: (r) => r.created_at,
      accessor: (r) => <RelativeTime iso={r.created_at} mode="table" />,
    },
  ];

  const items = query.data?.items ?? [];
  const total = query.data?.total ?? 0;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Changes"
        explain="Every move from one agent version to another. For each one, the system decides whether the change is significant enough that clients must approve it again — the formal term is a release."
      />
      <Panel noPadding>
        <DataTable
          columns={columns}
          data={items}
          rowKey={(r) => r.id}
          isLoading={query.isLoading}
          error={query.isError ? (query.error instanceof Error ? query.error.message : "Error") : null}
          onRetry={() => void query.refetch()}
          onRowClick={(r) => navigate(`/releases/${r.id}`)}
          emptyTitle="No releases"
          emptyDescription="Published releases will appear here."
        />
        {!query.isLoading && !query.isError && total > 0 ? (
          <div className="border-t border-line-200 px-4 py-3">
            <Pagination total={total} limit={PAGE_SIZE} offset={offset} onPageChange={setOffset} />
          </div>
        ) : null}
      </Panel>
    </div>
  );
}
