import { useState } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { usePolicies, usePolicyDecisions, usePolicyVersions } from "@/api/queries";
import type { PolicyDecision, PolicyVersion } from "@/api/types";
import { AgentRef } from "@/components/AgentRef";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { Digest } from "@/components/Digest";
import { Panel } from "@/components/Panel";
import { Pagination } from "@/components/Pagination";
import { Principal } from "@/components/Principal";
import { formatTableDate } from "@/lib/dates";
import { titleCaseSnake } from "@/lib/formatters";

const PAGE_SIZE = 25;

export default function PolicyScreen() {
  const [offset, setOffset] = useState(0);
  const [selectedPolicy, setSelectedPolicy] = useState<string>("");
  const policiesQuery = usePolicies();
  const policies = policiesQuery.data ?? [];

  // Versions belong to a policy, so a policy has to be chosen before there is anything
  // to show. Defaulting to the first keeps the screen useful on arrival instead of
  // opening on an empty table above a prompt to pick something.
  const activePolicy = selectedPolicy || policies[0]?.id || "";
  const versionsQuery = usePolicyVersions(activePolicy || undefined);
  const decisionsQuery = usePolicyDecisions({ limit: String(PAGE_SIZE), offset: String(offset) });

  const versionColumns: ColumnDef<PolicyVersion>[] = [
    {
      id: "version",
      header: "Version",
      sortValue: (v) => v.semver,
      accessor: (v) => <span className="font-mono-data">{v.semver}</span>,
    },
    {
      id: "effective",
      header: "Effective from",
      sortValue: (v) => v.effective_from,
      accessor: (v) => formatTableDate(v.effective_from),
    },
    {
      id: "to",
      header: "Effective to",
      accessor: (v) => (v.effective_to ? formatTableDate(v.effective_to) : "Current"),
    },
    {
      id: "digest",
      header: "Rules digest",
      accessor: (v) => <Digest value={v.rules_digest} />,
    },
    {
      id: "published",
      header: "Published by",
      accessor: (v) => <Principal principalId={v.published_by} />,
    },
    {
      id: "sig",
      header: "Signature",
      // A version carries a detached signature or it does not. There is no third state
      // on the API — the hand-written type used to claim a "valid | invalid | unsigned"
      // field, so this column rendered blank on every row.
      accessor: (v) =>
        v.signature ? (
          <span className="text-ok-fg" title={v.signing_key_ref ?? undefined}>
            Signed
          </span>
        ) : (
          <span className="text-ink-400">Unsigned</span>
        ),
    },
  ];

  const decisionColumns: ColumnDef<PolicyDecision>[] = [
    {
      id: "when",
      header: "Occurred",
      sortValue: (d) => d.occurred_at,
      accessor: (d) => formatTableDate(d.occurred_at),
    },
    {
      id: "outcome",
      header: "Outcome",
      sortValue: (d) => d.outcome,
      accessor: (d) => titleCaseSnake(d.outcome),
    },
    {
      id: "reason",
      header: "Reason code",
      accessor: (d) => <span className="font-mono-data">{d.reason_code}</span>,
    },
    {
      id: "agent",
      header: "Agent",
      accessor: (d) => <AgentRef agentId={d.agent_id} />,
    },
    {
      id: "region",
      header: "Region",
      // The whole point of a routing decision: where the request wanted to go and where
      // it was allowed to go. When those differ the request was rerouted, and that is
      // the single most useful thing on this screen for anyone auditing residency.
      accessor: (d) => {
        if (!d.requested_region && !d.effective_region) return "—";
        const moved =
          d.requested_region && d.effective_region && d.requested_region !== d.effective_region;
        return moved ? (
          <span className="tabular-nums">
            <span className="text-ink-400 line-through">{d.requested_region}</span>{" "}
            <span className="text-warn-fg">→ {d.effective_region}</span>
          </span>
        ) : (
          <span>{d.effective_region ?? d.requested_region}</span>
        );
      },
    },
    {
      id: "classes",
      header: "Data classes",
      accessor: (d) => (d.data_classes.length > 0 ? d.data_classes.join(", ") : "—"),
    },
    {
      id: "evidence",
      header: "Evidence event",
      accessor: (d) =>
        d.evidence_event_id ? (
          <Link
            to="/evidence"
            className="font-mono-data text-info-fg hover:underline"
            title={d.evidence_event_id}
          >
            {d.evidence_event_id.slice(0, 12)}…
          </Link>
        ) : (
          "—"
        ),
    },
  ];

  return (
    <div className="space-y-4">
      <PageHeader
        title="Rules"
        explain="The rules your agents have to follow, and a record of every time one was applied — what was allowed, what was blocked, and why. Formally called policy."
      />

      <Panel
        title="Rule sets"
        noPadding
        toolbar={
          policies.length > 0 ? (
            <label className="flex items-center gap-2 text-sm">
              <span className="text-ink-400">Rule set</span>
              <select
                className="rounded-sm border border-line-300 bg-bg-panel px-2 py-1 text-sm"
                value={activePolicy}
                onChange={(e) => {
                  setSelectedPolicy(e.target.value);
                }}
              >
                {policies.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                    {p.is_enabled ? "" : " (disabled)"}
                  </option>
                ))}
              </select>
            </label>
          ) : null
        }
      >
        <DataTable
          columns={versionColumns}
          data={versionsQuery.data ?? []}
          rowKey={(v) => v.id}
          isLoading={policiesQuery.isLoading || versionsQuery.isLoading}
          error={
            versionsQuery.isError
              ? versionsQuery.error instanceof Error
                ? versionsQuery.error.message
                : "Failed to load versions"
              : null
          }
          onRetry={() => void versionsQuery.refetch()}
          emptyTitle="No published versions"
          emptyDescription="This rule set exists but has never been published. Publishing records the rules and their digest, so a decision can be traced back to the exact text that produced it."
        />
      </Panel>

      <Panel title="Decisions" noPadding>
        <DataTable
          columns={decisionColumns}
          data={decisionsQuery.data?.items ?? []}
          rowKey={(d) => d.id}
          isLoading={decisionsQuery.isLoading}
          error={
            decisionsQuery.isError
              ? decisionsQuery.error instanceof Error
                ? decisionsQuery.error.message
                : "Failed to load decisions"
              : null
          }
          onRetry={() => void decisionsQuery.refetch()}
          emptyTitle="No decisions"
        />
        {!decisionsQuery.isLoading &&
        !decisionsQuery.isError &&
        (decisionsQuery.data?.total ?? 0) > PAGE_SIZE ? (
          <Pagination
            offset={offset}
            limit={PAGE_SIZE}
            total={decisionsQuery.data?.total ?? 0}
            onPageChange={setOffset}
          />
        ) : null}
      </Panel>
    </div>
  );
}
