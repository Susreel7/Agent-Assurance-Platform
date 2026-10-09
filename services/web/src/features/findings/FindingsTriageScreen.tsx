import { useMemo, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { useFindings } from "@/api/queries";
import type { Finding, FindingSource, FindingState, Severity } from "@/api/types";
import { AgentRef } from "@/components/AgentRef";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { Panel } from "@/components/Panel";
import { Pagination } from "@/components/Pagination";
import { FindingStateBadge, SeverityBadge } from "@/components/StateBadge";
import { Toolbar } from "@/components/Toolbar";
import { formatTableDate } from "@/lib/dates";
import { titleCaseSnake } from "@/lib/formatters";

const PAGE_SIZE = 50;
const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "low", "info"];

// A finding that is already resolved is not overdue however old its due date, which is
// why the state is part of the question and not just the date.
const SETTLED: FindingState[] = ["fixed", "mitigated", "accepted", "false_positive"];

function isOverdue(due: string, state: FindingState): boolean {
  if (SETTLED.includes(state)) return false;
  return new Date(due).getTime() < Date.now();
}

export default function FindingsTriageScreen() {
  const [offset, setOffset] = useState(0);
  const [severity, setSeverity] = useState<Severity | "">("");
  const [source, setSource] = useState<FindingSource | "">("");
  const [category, setCategory] = useState("");
  const [state, setState] = useState<FindingState | "">("");

  const query = useFindings({ limit: String(PAGE_SIZE), offset: String(offset) });

  const filtered = useMemo(() => {
    let items = query.data?.items ?? [];
    if (severity) items = items.filter((f) => f.severity === severity);
    if (source) items = items.filter((f) => f.source === source);
    if (category) items = items.filter((f) => f.category === category);
    if (state) items = items.filter((f) => f.state === state);
    return items;
  }, [query.data, severity, source, category, state]);

  const severityCounts = useMemo(() => {
    const counts: Record<Severity, number> = {
      critical: 0,
      high: 0,
      medium: 0,
      low: 0,
      info: 0,
    };
    for (const f of query.data?.items ?? []) {
      counts[f.severity] += 1;
    }
    return counts;
  }, [query.data]);

  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const f of query.data?.items ?? []) set.add(f.category);
    return [...set].sort();
  }, [query.data]);

  const columns: ColumnDef<Finding>[] = [
    {
      id: "severity",
      header: "Severity",
      sortValue: (f) => SEVERITY_ORDER.indexOf(f.severity),
      accessor: (f) => <SeverityBadge severity={f.severity} />,
    },
    {
      id: "source",
      header: "Source",
      sortValue: (f) => f.source,
      accessor: (f) => titleCaseSnake(f.source),
    },
    {
      id: "category",
      header: "Category",
      sortValue: (f) => f.category,
      accessor: (f) => titleCaseSnake(f.category),
    },
    {
      id: "title",
      header: "Title",
      accessor: (f) => f.title,
    },
    {
      id: "agent",
      header: "Agent",
      accessor: (f) => <AgentRef agentId={f.agent_id} />,
    },
    {
      id: "state",
      header: "State",
      accessor: (f) => <FindingStateBadge state={f.state} />,
    },
    {
      id: "first",
      header: "First seen",
      sortValue: (f) => f.first_seen_at,
      accessor: (f) => formatTableDate(f.first_seen_at),
    },
    {
      id: "due",
      header: "Remediation due",
      sortValue: (f) => f.remediation_due ?? "",
      // The API reports the due date; whether that date has passed is a question about
      // now, so it is answered here rather than being trusted from a server field that
      // goes stale the moment it is serialised.
      accessor: (f) => {
        if (!f.remediation_due) return "—";
        const overdue = isOverdue(f.remediation_due, f.state);
        return (
          <span className={overdue ? "text-risk-fg font-medium tabular-nums" : "tabular-nums"}>
            {formatTableDate(f.remediation_due)}
            {overdue ? " · overdue" : ""}
          </span>
        );
      },
    },
  ];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Issues"
        explain="Problems found in your agents — known vulnerabilities, broken rules, failed safety checks — with the most urgent first. Formally called findings."
      />

      <Panel title="By severity">
        <div className="flex flex-wrap gap-3">
          {SEVERITY_ORDER.map((sev) => (
            <button
              key={sev}
              type="button"
              className="flex items-center gap-2 rounded-sm border border-line-200 px-3 py-1.5 text-table hover:bg-bg-sunk"
              onClick={() => setSeverity(severity === sev ? "" : sev)}
            >
              <SeverityBadge severity={sev} />
              <span className="tabular-nums text-ink-900">{severityCounts[sev]}</span>
            </button>
          ))}
        </div>
      </Panel>

      <Panel
        noPadding
        toolbar={
          <Toolbar>
            <select
              className="rounded-sm border border-line-200 px-2 py-1 text-table"
              value={source}
              onChange={(e) => setSource(e.target.value as FindingSource | "")}
              aria-label="Filter by source"
            >
              <option value="">All sources</option>
              <option value="probe">Probe</option>
              <option value="cve">CVE</option>
              <option value="drift">Drift</option>
            </select>
            <select
              className="rounded-sm border border-line-200 px-2 py-1 text-table"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              aria-label="Filter by category"
            >
              <option value="">All categories</option>
              {categories.map((c) => (
                <option key={c} value={c}>
                  {titleCaseSnake(c)}
                </option>
              ))}
            </select>
            <select
              className="rounded-sm border border-line-200 px-2 py-1 text-table"
              value={state}
              onChange={(e) => setState(e.target.value as FindingState | "")}
              aria-label="Filter by state"
            >
              <option value="">All states</option>
              <option value="open">Open</option>
              <option value="accepted">Accepted</option>
              <option value="remediated">Remediated</option>
              <option value="false_positive">False positive</option>
            </select>
          </Toolbar>
        }
      >
        <DataTable
          columns={columns}
          data={filtered}
          rowKey={(f) => f.id}
          isLoading={query.isLoading}
          error={
            query.isError
              ? query.error instanceof Error
                ? query.error.message
                : "Failed to load findings"
              : null
          }
          onRetry={() => void query.refetch()}
          emptyTitle="No findings"
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
