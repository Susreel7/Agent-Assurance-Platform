/**
 * Declared agent makeup vs what runtime observation saw in the selected window.
 */

import { useMemo } from "react";
import { useAgent, useAgentReconciliation } from "@/api/queries";
import type { CompositionElement } from "@/api/types";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { ErrorState } from "@/components/ErrorState";
import { Panel } from "@/components/Panel";
import { Skeleton } from "@/components/Skeleton";
import { Badge } from "@/components/StateBadge";
import { titleCaseSnake } from "@/lib/formatters";
import { useWindowDays, windowLabel } from "@/lib/windowDays";

const KIND_ORDER = [
  "tool",
  "mcp_server",
  "model",
  "skill",
  "sub_agent",
  "config",
  "rule_obligation",
  "memory_retrieval",
  "guardrail",
];

function statusBadge(status: CompositionElement["status"]) {
  const label = titleCaseSnake(status);
  if (status === "observed_only" || status === "conflict") {
    return <Badge tone="risk" label={label} />;
  }
  if (status === "declared_only") {
    return <Badge tone="warn" label={label} />;
  }
  return <Badge tone="ok" label={label} />;
}

export function AgentCompositionTab({ agentId }: { agentId: string }) {
  const { days } = useWindowDays();
  const agentQuery = useAgent(agentId);
  const versionId = agentQuery.data?.current_version_id;
  const reconciliationQuery = useAgentReconciliation(agentId, days);

  const grouped = useMemo(() => {
    const elements = reconciliationQuery.data?.elements ?? [];
    const buckets = new Map<string, CompositionElement[]>();
    for (const el of elements) {
      const list = buckets.get(el.kind) ?? [];
      list.push(el);
      buckets.set(el.kind, list);
    }
    for (const list of buckets.values()) {
      list.sort((a, b) => a.key.localeCompare(b.key));
    }
    return buckets;
  }, [reconciliationQuery.data?.elements]);

  if (agentQuery.isLoading || reconciliationQuery.isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton height="2rem" width="40%" />
        <Skeleton height="320px" />
      </div>
    );
  }

  if (reconciliationQuery.isError || !reconciliationQuery.data) {
    return (
      <ErrorState
        title="Could not load composition"
        message={
          reconciliationQuery.error instanceof Error
            ? reconciliationQuery.error.message
            : "Unknown error"
        }
        onRetry={() => void reconciliationQuery.refetch()}
      />
    );
  }

  if (!versionId) {
    return (
      <div className="rounded-card border border-line bg-bg px-4 py-8 text-center text-body text-ink-600">
        Publish a version before composition can be reconciled.
      </div>
    );
  }

  const columns: ColumnDef<CompositionElement>[] = [
    {
      id: "key",
      header: "Element",
      sortValue: (r) => r.key,
      accessor: (r) => <span className="font-mono-data text-ink-900">{r.key}</span>,
    },
    {
      id: "declared",
      header: "Declared",
      accessor: (r) => (r.declared ? "Yes" : "—"),
    },
    {
      id: "observed",
      header: `Observed (${windowLabel(days).toLowerCase()})`,
      accessor: (r) =>
        r.observed ? `${r.observed_count > 0 ? r.observed_count : "Yes"}` : "—",
    },
    {
      id: "status",
      header: "Status",
      sortValue: (r) => r.status,
      accessor: (r) => statusBadge(r.status),
    },
  ];

  const undeclared = reconciliationQuery.data.elements.filter(
    (e) => e.status === "observed_only" || e.status === "conflict",
  );

  return (
    <div className="space-y-4">
      {undeclared.length > 0 ? (
        <Panel>
          <div className="border-b border-line px-4 py-3">
            <h3 className="text-body font-medium text-risk-fg">
              {undeclared.length} undeclared or out-of-policy element
              {undeclared.length === 1 ? "" : "s"}
            </h3>
            <p className="mt-1 text-table text-ink-500">
              Runtime reported these in {windowLabel(days).toLowerCase()} but they are missing
              from the published descriptor (or violate model policy).
            </p>
          </div>
          <DataTable
            columns={columns}
            data={undeclared}
            rowKey={(r) => `${r.kind}:${r.key}`}
          />
        </Panel>
      ) : null}

      {KIND_ORDER.filter((k) => grouped.has(k)).map((kind) => (
        <Panel key={kind} noPadding>
          <div className="border-b border-line px-4 py-2">
            <h3 className="text-table font-medium text-ink-800">{titleCaseSnake(kind)}</h3>
          </div>
          <DataTable
            columns={columns}
            data={grouped.get(kind) ?? []}
            rowKey={(r) => `${r.kind}:${r.key}`}
          />
        </Panel>
      ))}
    </div>
  );
}
