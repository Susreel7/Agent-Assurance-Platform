import { useMemo, useState } from "react";
import {
  useEvidenceBatches,
  useEvidenceChain,
  useEvidenceEvents,
  useInclusionProof,
  useAgents,
} from "@/api/queries";
import { AgentRef } from "@/components/AgentRef";
import { PageHeader } from "@/components/PageHeader";
import type { EvidenceEvent, EvidenceKind } from "@/api/types";
import { type ColumnDef } from "@/components/DataTable";
import { Panel } from "@/components/Panel";
import { Toolbar } from "@/components/Toolbar";
import { Pagination } from "@/components/Pagination";
import { Digest } from "@/components/Digest";
import { RelativeTime } from "@/components/RelativeTime";
import { Principal } from "@/components/Principal";
import { titleCaseSnake } from "@/lib/formatters";
import { ChainVerificationPanel } from "./ChainVerificationPanel";
import clsx from "clsx";

const PAGE_SIZE = 25;

const EVIDENCE_KINDS: EvidenceKind[] = [
  "bom_completeness",
  "model_inventory",
  "tool_permission_inventory",
  "data_class_inventory",
  "residency_proof",
  "redaction_record",
  "approval_record",
  "ownership_record",
  "oversight_record",
  "change_history",
  "materiality_verdict",
  "vulnerability_scan",
  "adversarial_probe",
  "service_level_attainment",
  "chain_integrity",
  "incident_record",
];

export default function EvidenceExplorerScreen() {
  const [offset, setOffset] = useState(0);
  const [kind, setKind] = useState<EvidenceKind | "">("");
  const [agentId, setAgentId] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [proofRequested, setProofRequested] = useState(false);

  const eventsQuery = useEvidenceEvents({
    limit: String(PAGE_SIZE),
    offset: String(offset),
    kind: kind || undefined,
    agent_id: agentId || undefined,
  });
  const chainQuery = useEvidenceChain();
  const batchesQuery = useEvidenceBatches({ limit: "50", offset: "0" });
  const agentsQuery = useAgents({ limit: "50" });
  const proofQuery = useInclusionProof(selectedId ?? "", proofRequested);

  const latestBatch = useMemo(() => {
    const items = batchesQuery.data?.items ?? [];
    if (items.length === 0) return undefined;
    return [...items].sort((a, b) => b.seq - a.seq)[0];
  }, [batchesQuery.data]);

  const columns: ColumnDef<EvidenceEvent>[] = [
    {
      id: "occurred",
      header: "Occurred",
      sortValue: (e) => e.occurred_at,
      accessor: (e) => <RelativeTime iso={e.occurred_at} mode="table" />,
    },
    {
      id: "recorded",
      header: "Recorded",
      sortValue: (e) => e.recorded_at,
      accessor: (e) => <RelativeTime iso={e.recorded_at} mode="table" />,
    },
    {
      id: "kind",
      header: "Kind",
      sortValue: (e) => e.kind,
      accessor: (e) => titleCaseSnake(e.kind),
    },
    {
      id: "agent",
      header: "Agent",
      accessor: (e) => <AgentRef agentId={e.agent_id} />,
    },
    {
      id: "actor",
      header: "Actor",
      accessor: (e) => <Principal principalId={e.actor} />,
    },
    { id: "action", header: "Action", accessor: (e) => e.action },
    { id: "outcome", header: "Outcome", accessor: (e) => e.outcome },
    { id: "region", header: "Region", accessor: (e) => e.region ?? "—" },
    {
      id: "classes",
      header: "Data classes",
      accessor: (e) => e.data_classes.join(", ") || "—",
    },
    {
      id: "digest",
      header: "Digest",
      accessor: (e) => <Digest value={e.content_digest} />,
    },
  ];

  const items = eventsQuery.data?.items ?? [];
  const total = eventsQuery.data?.total ?? 0;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Evidence"
        explain="A tamper-proof record of what your agents did. It stores fingerprints and decisions, never the customer's own content, and a client or auditor can check it independently without trusting you."
      />

      <Panel title="Chain verification">
        <ChainVerificationPanel
          chain={chainQuery.data}
          latestBatch={latestBatch}
          chainLoading={chainQuery.isLoading}
          chainError={
            chainQuery.isError
              ? chainQuery.error instanceof Error
                ? chainQuery.error.message
                : "Chain verification failed"
              : null
          }
          onRetryChain={() => void chainQuery.refetch()}
          batchesLoading={batchesQuery.isLoading}
          selectedEventId={selectedId}
          onVerifyInclusion={() => setProofRequested(true)}
          inclusionProof={proofQuery.data}
          inclusionLoading={proofQuery.isLoading}
          inclusionEnabled={proofRequested && Boolean(selectedId)}
        />
      </Panel>

      <Panel
        title="Events"
        toolbar={
          <Toolbar>
            <select
              className="rounded-sm border border-line-200 px-2 py-1 text-table"
              value={kind}
              onChange={(e) => {
                setKind(e.target.value as EvidenceKind | "");
                setOffset(0);
              }}
              aria-label="Filter by evidence kind"
            >
              <option value="">All kinds</option>
              {EVIDENCE_KINDS.map((k) => (
                <option key={k} value={k}>
                  {titleCaseSnake(k)}
                </option>
              ))}
            </select>
            <select
              className="rounded-sm border border-line-200 px-2 py-1 text-table"
              value={agentId}
              onChange={(e) => {
                setAgentId(e.target.value);
                setOffset(0);
              }}
              aria-label="Filter by agent"
            >
              <option value="">All agents</option>
              {(agentsQuery.data?.items ?? []).map((a) => (
                <option key={a.id} value={a.id}>
                  {a.display_name}
                </option>
              ))}
            </select>
          </Toolbar>
        }
        noPadding
      >
        <div className="overflow-auto">
          <table>
            <thead className="sticky top-0 z-10 bg-bg-panel">
              <tr>
                <th scope="col" className="w-8 px-2 py-2" aria-label="Select" />
                {columns.map((col) => (
                  <th key={col.id} scope="col" className="px-3 py-2 text-left whitespace-nowrap">
                    {col.header}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {eventsQuery.isLoading ? (
                <tr>
                  <td colSpan={columns.length + 1} className="p-4 text-ink-400">
                    Loading…
                  </td>
                </tr>
              ) : eventsQuery.isError ? (
                <tr>
                  <td colSpan={columns.length + 1} className="p-4 text-risk-fg">
                    Failed to load events
                  </td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={columns.length + 1} className="p-8 text-center text-ink-400">
                    No evidence events match filters.
                  </td>
                </tr>
              ) : (
                items.map((row) => {
                  const selected = selectedId === row.id;
                  return (
                    <tr
                      key={row.id}
                      className={clsx(selected && "bg-info-bg/40", "hover:bg-bg-sunk")}
                    >
                      <td className="px-2 py-2">
                        <input
                          type="radio"
                          name="evidence-select"
                          checked={selected}
                          onChange={() => {
                            setSelectedId(row.id);
                            setProofRequested(false);
                          }}
                          aria-label={`Select event ${row.id}`}
                        />
                      </td>
                      {columns.map((col) => (
                        <td key={col.id} className="px-3 py-2 text-table">
                          {col.accessor ? col.accessor(row) : null}
                        </td>
                      ))}
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
        {!eventsQuery.isLoading && !eventsQuery.isError && total > 0 ? (
          <div className="border-t border-line-200 px-4 py-3">
            <Pagination total={total} limit={PAGE_SIZE} offset={offset} onPageChange={setOffset} />
          </div>
        ) : null}
      </Panel>
    </div>
  );
}
