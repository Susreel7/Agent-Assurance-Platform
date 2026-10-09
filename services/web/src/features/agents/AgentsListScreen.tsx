import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { useAgents, useCustomers } from "@/api/queries";
import type { AccreditationState, AgentSummary, LifecycleState } from "@/api/types";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { Panel } from "@/components/Panel";
import { Toolbar } from "@/components/Toolbar";
import { Pagination } from "@/components/Pagination";
import {
  AccreditationStateBadge,
  LifecycleStateBadge,
} from "@/components/StateBadge";
import { Urn } from "@/components/Urn";
import { RelativeTime } from "@/components/RelativeTime";
import { titleCaseSnake } from "@/lib/formatters";

const PAGE_SIZE = 25;

export default function AgentsListScreen() {
  const [offset, setOffset] = useState(0);
  const [lifecycle, setLifecycle] = useState<LifecycleState | "">("");
  const [accreditation, setAccreditation] = useState<AccreditationState | "">("");
  const [team, setTeam] = useState("");
  const [customerId, setCustomerId] = useState("");
  const [driftOnly, setDriftOnly] = useState(false);

  const navigate = useNavigate();
  const query = useAgents({
    limit: String(PAGE_SIZE),
    offset: String(offset),
    lifecycle_state: lifecycle ? [lifecycle] : undefined,
  });
  const customersQuery = useCustomers({ limit: "50" });

  const teams = useMemo(() => {
    const set = new Set<string>();
    for (const a of query.data?.items ?? []) {
      if (a.owning_team) set.add(a.owning_team);
    }
    return [...set].sort();
  }, [query.data]);

  const filtered = useMemo(() => {
    let items = query.data?.items ?? [];
    if (team) items = items.filter((a) => a.owning_team === team);
    if (accreditation) items = items.filter((a) => a.accreditation_state === accreditation);
    if (customerId) items = items.filter((a) => a.customer_ids.includes(customerId));
    if (driftOnly) items = items.filter((a) => a.has_drift);
    return items;
  }, [query.data, team, accreditation, customerId, driftOnly]);

  const columns: ColumnDef<AgentSummary>[] = [
    {
      id: "urn",
      header: "URN",
      sortValue: (a) => a.urn,
      accessor: (a) => <Urn value={a.urn} />,
    },
    {
      id: "name",
      header: "Display name",
      sortValue: (a) => a.display_name,
      accessor: (a) => a.display_name,
    },
    {
      id: "team",
      header: "Owning team",
      sortValue: (a) => a.owning_team ?? "",
      accessor: (a) => a.owning_team ?? "—",
    },
    {
      id: "lifecycle",
      header: "Lifecycle",
      sortValue: (a) => a.lifecycle_state,
      accessor: (a) => <LifecycleStateBadge state={a.lifecycle_state} />,
    },
    {
      id: "framework",
      header: "Framework",
      accessor: (a) => a.runtime_framework ?? "—",
    },
    {
      id: "environment",
      header: "Environment",
      accessor: (a) => titleCaseSnake(a.environment),
    },
    {
      id: "posture",
      header: "Posture",
      align: "right",
      sortValue: (a) => a.posture_score,
      accessor: (a) => <span className="tabular-nums">{a.posture_score}</span>,
    },
    {
      id: "accreditation",
      header: "Accreditation",
      accessor: (a) =>
        a.accreditation_state ? (
          <AccreditationStateBadge state={a.accreditation_state} />
        ) : (
          "—"
        ),
    },
    {
      id: "drift",
      header: "Drift",
      sortValue: (a) => (a.has_drift ? 1 : 0),
      accessor: (a) =>
        a.has_drift ? (
          <span className="font-medium text-risk-fg" title="Deployed version differs from accredited version">
            Drift
          </span>
        ) : (
          <span className="text-ink-400">Aligned</span>
        ),
      className: "bg-risk-bg/30",
    },
    {
      id: "release",
      header: "Last release",
      sortValue: (a) => a.last_release_at ?? "",
      accessor: (a) =>
        a.last_release_at ? (
          <span className="text-table">
            <span className="font-mono-data">{a.last_release_tag}</span>
            <br />
            <RelativeTime iso={a.last_release_at} mode="table" />
          </span>
        ) : (
          "—"
        ),
    },
  ];

  const total = query.data?.total ?? 0;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Agents"
        explain="Every AI agent you run. Each has a history of versions, and each version can be approved by the clients it serves."
      />
      <Panel
        toolbar={
          <Toolbar>
            <select
              className="rounded-sm border border-line-200 bg-bg-panel px-2 py-1 text-table"
              value={lifecycle}
              onChange={(e) => {
                setLifecycle(e.target.value as LifecycleState | "");
                setOffset(0);
              }}
              aria-label="Filter by lifecycle state"
            >
              <option value="">All lifecycle states</option>
              {(["dev", "test", "staging", "production", "retired"] as const).map((s) => (
                <option key={s} value={s}>
                  {titleCaseSnake(s)}
                </option>
              ))}
            </select>
            <select
              className="rounded-sm border border-line-200 bg-bg-panel px-2 py-1 text-table"
              value={team}
              onChange={(e) => setTeam(e.target.value)}
              aria-label="Filter by owning team"
            >
              <option value="">All teams</option>
              {teams.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <select
              className="rounded-sm border border-line-200 bg-bg-panel px-2 py-1 text-table"
              value={accreditation}
              onChange={(e) => setAccreditation(e.target.value as AccreditationState | "")}
              aria-label="Filter by accreditation state"
            >
              <option value="">All accreditation states</option>
              {(["draft", "submitted", "approved", "suspended", "expired", "withdrawn"] as const).map(
                (s) => (
                  <option key={s} value={s}>
                    {titleCaseSnake(s)}
                  </option>
                ),
              )}
            </select>
            <select
              className="rounded-sm border border-line-200 bg-bg-panel px-2 py-1 text-table"
              value={customerId}
              onChange={(e) => setCustomerId(e.target.value)}
              aria-label="Filter by customer"
              disabled={customersQuery.isLoading}
            >
              <option value="">All customers</option>
              {(customersQuery.data?.items ?? []).map((c) => (
                <option key={c.id} value={c.id}>
                  {c.display_name}
                </option>
              ))}
            </select>
            <label className="flex items-center gap-2 text-table">
              <input
                type="checkbox"
                checked={driftOnly}
                onChange={(e) => setDriftOnly(e.target.checked)}
              />
              Drift only
            </label>
          </Toolbar>
        }
        noPadding
      >
        <DataTable
          columns={columns}
          data={filtered}
          rowKey={(a) => a.id}
          isLoading={query.isLoading}
          error={query.isError ? (query.error instanceof Error ? query.error.message : "Error") : null}
          onRetry={() => void query.refetch()}
          onRowClick={(a) => navigate(`/agents/${a.id}`)}
          emptyTitle="No agents match filters"
        />
        {!query.isLoading && !query.isError ? (
          <div className="border-t border-line-200 px-4 py-3">
            <Pagination total={total} limit={PAGE_SIZE} offset={offset} onPageChange={setOffset} />
          </div>
        ) : null}
      </Panel>
    </div>
  );
}
