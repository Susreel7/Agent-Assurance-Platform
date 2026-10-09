import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { EMPTY_ITEMS, useAccreditations } from "@/api/queries";
import type { AccreditationState, AccreditationSummary } from "@/api/types";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { Panel } from "@/components/Panel";
import { AccreditationStateBadge } from "@/components/StateBadge";
import { Urn } from "@/components/Urn";
import { formatTableDate } from "@/lib/dates";

const STATE_ORDER: AccreditationState[] = [
  "draft",
  "submitted",
  "approved",
  "suspended",
  "expired",
  "withdrawn",
];

const columns: ColumnDef<AccreditationSummary>[] = [
  {
    id: "ref",
    header: "Reference",
    sortValue: (a) => a.reference,
    accessor: (a) => <span className="font-mono-data">{a.reference}</span>,
  },
  {
    id: "agent",
    header: "Agent",
    accessor: (a) => <Urn value={a.agent_urn} />,
  },
  {
    id: "customer",
    header: "Customer",
    sortValue: (a) => a.customer_display_name,
    accessor: (a) => a.customer_display_name,
  },
  {
    id: "framework",
    header: "Framework",
    accessor: (a) => a.framework_name,
  },
  {
    id: "version",
    header: "Version",
    accessor: (a) => <span className="font-mono-data tabular-nums">{a.version_semver}</span>,
  },
  {
    id: "state",
    header: "State",
    sortValue: (a) => a.state,
    accessor: (a) => <AccreditationStateBadge state={a.state} />,
  },
  {
    id: "approved",
    header: "Approved",
    sortValue: (a) => a.approved_at ?? "",
    accessor: (a) => (a.approved_at ? formatTableDate(a.approved_at) : "—"),
  },
];

export default function AccreditationsListScreen() {
  const navigate = useNavigate();
  const query = useAccreditations({ limit: "100", offset: "0" });
  const items = query.data?.items ?? EMPTY_ITEMS;

  const grouped = useMemo(() => {
    const map = new Map<AccreditationState, AccreditationSummary[]>();
    for (const state of STATE_ORDER) {
      map.set(state, []);
    }
    for (const a of items) {
      const list = map.get(a.state);
      if (list) list.push(a);
    }
    return map;
  }, [items]);

  return (
    <div className="space-y-4">
      <PageHeader
        title="Approvals"
        explain="A client formally agreeing that one specific agent version is fit for their use. Known as an accreditation. Each one moves from draft, to submitted, to approved."
      />

      {query.isLoading ? (
        <Panel>
          <p className="text-table text-ink-400" aria-busy>
            Loading…
          </p>
        </Panel>
      ) : query.isError ? (
        <Panel>
          <p className="text-risk-fg text-table">
            {query.error instanceof Error ? query.error.message : "Failed to load accreditations"}
          </p>
          <button
            type="button"
            className="mt-2 text-table text-info-fg underline"
            onClick={() => void query.refetch()}
          >
            Retry
          </button>
        </Panel>
      ) : (
        STATE_ORDER.map((state) => {
          const rows = grouped.get(state) ?? [];
          return (
            <Panel
              key={state}
              title={`${state.replace(/_/g, " ")} (${rows.length})`}
              noPadding
            >
              {rows.length === 0 ? (
                <p className="p-4 text-table text-ink-400">None in this state.</p>
              ) : (
                <DataTable
                  columns={columns}
                  data={rows}
                  rowKey={(a) => a.id}
                  onRowClick={(a) => navigate(`/accreditations/${a.id}`)}
                  stickyHeader={false}
                />
              )}
            </Panel>
          );
        })
      )}

      <p className="text-xs text-ink-400">
        Suspended accreditations often follow material release changes — see{" "}
        <Link to="/releases" className="text-info-fg hover:underline">
          releases
        </Link>
        .
      </p>
    </div>
  );
}
