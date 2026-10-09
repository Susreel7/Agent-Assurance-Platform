import { Suspense, lazy, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  useAccreditations,
  useAgent,
  useAgentGraphNeighbourhood,
  useAgentOwnership,
  useAgentVersions,
  useEvidenceEvents,
  useFindings,
  useReleases,
} from "@/api/queries";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { Panel } from "@/components/Panel";
import { Tabs } from "@/components/Tabs";
import { ErrorState } from "@/components/ErrorState";
import { Skeleton } from "@/components/Skeleton";
import {
  AccreditationStateBadge,
  LifecycleStateBadge,
  SeverityBadge,
  FindingStateBadge,
  ReleaseStateBadge,
} from "@/components/StateBadge";
import { Urn } from "@/components/Urn";
import { Digest } from "@/components/Digest";
import { RelativeTime } from "@/components/RelativeTime";
import { Principal } from "@/components/Principal";
import { formatSemverRange, titleCaseSnake } from "@/lib/formatters";
import { PostureCard } from "./PostureCard";
import { AgentBomTab } from "./AgentBomTab";
import { AgentActivityTab } from "./AgentActivityTab";
import { AgentCompositionTab } from "./AgentCompositionTab";
import { AgentAssuranceTab } from "./AgentAssuranceTab";
import type { AgentVersion, AccreditationSummary, Finding, ReleaseSummary, EvidenceEvent, Ownership } from "@/api/types";

// Cytoscape is only used on this tab; keep it out of the main bundle (see App.tsx graph route).
const AgentObservedGraphTab = lazy(() =>
  import("./AgentObservedGraphTab").then((mod) => ({ default: mod.AgentObservedGraphTab })),
);

export default function AgentDetailScreen() {
  const { agentId = "" } = useParams();
  const agentQuery = useAgent(agentId);
  const [tab, setTab] = useState<string>("overview");

  const versionsQuery = useAgentVersions(agentId, { limit: "50" });
  const releasesQuery = useReleases({ agent_id: agentId, limit: "20" });
  const evidenceQuery = useEvidenceEvents({ agent_id: agentId, limit: "30" });
  const graphQuery = useAgentGraphNeighbourhood(agentId, 2);
  const ownershipQuery = useAgentOwnership(agentId);
  const accQuery = useAccreditations({ limit: "100" });
  const findingsQuery = useFindings({ limit: "100" });

  const agent = agentQuery.data;

  const accForAgent = useMemo(
    () => (accQuery.data?.items ?? []).filter((a) => a.agent_id === agentId),
    [accQuery.data, agentId],
  );
  const findingsForAgent = useMemo(
    () => (findingsQuery.data?.items ?? []).filter((f) => f.agent_id === agentId),
    [findingsQuery.data, agentId],
  );

  if (agentQuery.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton height="2rem" width="50%" />
        <Skeleton height="8rem" />
      </div>
    );
  }

  if (agentQuery.isError || !agent) {
    return (
      <ErrorState
        message={agentQuery.error instanceof Error ? agentQuery.error.message : "Agent not found"}
        onRetry={() => void agentQuery.refetch()}
      />
    );
  }

  const versionColumns: ColumnDef<AgentVersion>[] = [
    {
      id: "semver",
      header: "Version",
      sortValue: (v) => v.semver,
      accessor: (v) => (
        <Link to={`/agents/${agentId}/versions/${v.id}`} className="font-mono-data text-info-fg hover:underline">
          {v.semver}
          {v.is_baseline ? (
            <span className="ml-2 text-xs text-ink-400">(baseline)</span>
          ) : null}
          {v.is_current ? <span className="ml-1 text-xs text-ok-fg">current</span> : null}
        </Link>
      ),
    },
    {
      id: "digest",
      header: "Descriptor digest",
      accessor: (v) => <Digest value={v.descriptor_digest} />,
    },
    {
      id: "published",
      header: "Published",
      sortValue: (v) => v.published_at,
      accessor: (v) => <RelativeTime iso={v.published_at} mode="table" />,
    },
    {
      id: "by",
      header: "Published by",
      accessor: (v) => <Principal principalId={v.published_by} />,
    },
  ];

  const releaseColumns: ColumnDef<ReleaseSummary>[] = [
    {
      id: "tag",
      header: "Release",
      accessor: (r) => (
        <Link to={`/releases/${r.id}`} className="font-mono-data text-info-fg hover:underline">
          {r.release_tag}
        </Link>
      ),
    },
    {
      id: "range",
      header: "Version",
      accessor: (r) => formatSemverRange(r.from_semver, r.to_semver),
    },
    { id: "state", header: "State", accessor: (r) => <ReleaseStateBadge state={r.state} /> },
    {
      id: "created",
      header: "Created",
      accessor: (r) => <RelativeTime iso={r.created_at} mode="table" />,
    },
  ];

  const evidenceColumns: ColumnDef<EvidenceEvent>[] = [
    {
      id: "occurred",
      header: "Occurred",
      accessor: (e) => <RelativeTime iso={e.occurred_at} mode="table" />,
    },
    { id: "kind", header: "Kind", accessor: (e) => titleCaseSnake(e.kind) },
    { id: "action", header: "Action", accessor: (e) => e.action },
    { id: "outcome", header: "Outcome", accessor: (e) => e.outcome },
    { id: "digest", header: "Digest", accessor: (e) => <Digest value={e.content_digest} /> },
  ];

  const ownershipColumns: ColumnDef<Ownership>[] = [
    { id: "role", header: "Role", accessor: (o) => titleCaseSnake(o.role) },
    { id: "principal", header: "Principal", accessor: (o) => <Principal principalId={o.principal_id} /> },
    {
      id: "valid",
      header: "Valid from",
      accessor: (o) => <RelativeTime iso={o.valid_from} mode="table" />,
    },
  ];

  const accColumns: ColumnDef<AccreditationSummary>[] = [
    {
      id: "ref",
      header: "Reference",
      accessor: (a) => (
        <Link to={`/accreditations/${a.id}`} className="font-mono-data text-info-fg hover:underline">
          {a.reference}
        </Link>
      ),
    },
    { id: "customer", header: "Customer", accessor: (a) => a.customer_display_name },
    { id: "state", header: "State", accessor: (a) => <AccreditationStateBadge state={a.state} /> },
    { id: "framework", header: "Framework", accessor: (a) => a.framework_name },
  ];

  const findingColumns: ColumnDef<Finding>[] = [
    { id: "severity", header: "Severity", accessor: (f) => <SeverityBadge severity={f.severity} /> },
    { id: "title", header: "Title", accessor: (f) => f.title },
    { id: "source", header: "Source", accessor: (f) => titleCaseSnake(f.source) },
    { id: "state", header: "State", accessor: (f) => <FindingStateBadge state={f.state} /> },
    {
      id: "due",
      header: "Remediation due",
      accessor: (f) =>
        f.remediation_due ? <RelativeTime iso={f.remediation_due} mode="table" /> : "—",
    },
  ];

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-ink-900">{agent.display_name}</h1>
          <Urn value={agent.urn} />
          <div className="mt-2 flex flex-wrap gap-2">
            <LifecycleStateBadge state={agent.lifecycle_state} />
            {agent.accreditation_state ? (
              <AccreditationStateBadge state={agent.accreditation_state} />
            ) : null}
            {agent.has_drift ? (
              <span className="text-table font-medium text-risk-fg">Version drift</span>
            ) : null}
          </div>
        </div>
        <dl className="text-table text-ink-600 space-y-1">
          <div>
            <dt className="inline text-ink-400">Current: </dt>
            <dd className="inline font-mono-data">{agent.current_semver ?? "—"}</dd>
          </div>
          <div>
            <dt className="inline text-ink-400">Baseline: </dt>
            <dd className="inline font-mono-data">{agent.baseline_semver ?? "—"}</dd>
          </div>
          <div>
            <dt className="inline text-ink-400">Accredited: </dt>
            <dd className="inline font-mono-data">{agent.accredited_semver ?? "—"}</dd>
          </div>
        </dl>
      </header>

      <Tabs
        ariaLabel="Agent detail sections"
        activeId={tab}
        onChange={setTab}
        tabs={[
          { id: "overview", label: "Overview" },
          // Second, not last. What an agent has been doing is the question people
          // arrive with; the governance record is what they check afterwards.
          { id: "activity", label: "Activity" },
          { id: "composition", label: "Composition" },
          { id: "assurance", label: "Assurance" },
          { id: "observed-graph", label: "Observed graph" },
          { id: "bom", label: "Bill of materials" },
          { id: "versions", label: "Versions" },
          { id: "releases", label: "Releases" },
          { id: "evidence", label: "Evidence" },
          { id: "graph", label: "Graph neighbourhood" },
          { id: "ownership", label: "Ownership" },
          { id: "accreditations", label: "Accreditations" },
          { id: "findings", label: "Findings" },
        ]}
      />

      {/* Activity brings its own panels — it is a small dashboard rather than a table,
          so wrapping it in one more card would nest a grid inside a box for no reason. */}
      {tab === "activity" ? (
        <AgentActivityTab agentId={agentId} />
      ) : tab === "composition" ? (
        <AgentCompositionTab agentId={agentId} />
      ) : tab === "assurance" ? (
        <AgentAssuranceTab agentId={agentId} />
      ) : tab === "observed-graph" ? (
        <Suspense fallback={<Skeleton height="420px" />}>
          <AgentObservedGraphTab agentId={agentId} />
        </Suspense>
      ) : (
      <Panel noPadding={tab !== "overview"}>
        {tab === "overview" ? (
          <div className="grid md:grid-cols-2 gap-4 p-4">
            <PostureCard posture={agent.posture} />
            <div className="text-table text-ink-600 space-y-2">
              <p>{agent.description ?? "No description recorded."}</p>
              <p>
                Owning team: <strong className="text-ink-900">{agent.owning_team ?? "—"}</strong>
              </p>
              <p>
                Runtime: {agent.runtime_framework ?? "—"} · Environment{" "}
                {titleCaseSnake(agent.environment)}
              </p>
            </div>
          </div>
        ) : null}

        {tab === "bom" ? (
          <div className="p-4">
            <AgentBomTab agentId={agentId} />
          </div>
        ) : null}

        {tab === "versions" ? (
          <DataTable
            columns={versionColumns}
            data={versionsQuery.data?.items ?? []}
            rowKey={(v) => v.id}
            isLoading={versionsQuery.isLoading}
            error={versionsQuery.isError ? "Failed to load versions" : null}
            onRetry={() => void versionsQuery.refetch()}
            emptyTitle="No versions"
          />
        ) : null}

        {tab === "releases" ? (
          <DataTable
            columns={releaseColumns}
            data={releasesQuery.data?.items ?? []}
            rowKey={(r) => r.id}
            isLoading={releasesQuery.isLoading}
            error={releasesQuery.isError ? "Failed to load releases" : null}
            onRetry={() => void releasesQuery.refetch()}
            emptyTitle="No releases"
          />
        ) : null}

        {tab === "evidence" ? (
          <DataTable
            columns={evidenceColumns}
            data={evidenceQuery.data?.items ?? []}
            rowKey={(e) => e.id}
            isLoading={evidenceQuery.isLoading}
            error={evidenceQuery.isError ? "Failed to load evidence" : null}
            onRetry={() => void evidenceQuery.refetch()}
            emptyTitle="No evidence events"
          />
        ) : null}

        {tab === "graph" ? (
          <div className="p-4 text-table">
            {graphQuery.isLoading ? (
              <Skeleton height="8rem" />
            ) : graphQuery.isError ? (
              <ErrorState message="Failed to load graph" onRetry={() => void graphQuery.refetch()} />
            ) : (
              <>
                {/* The endpoint returns the reachable nodes and the edge kind each was
                    reached through — not a separate edge list. This used to read
                    `.edges`, which does not exist, so the whole tab threw. */}
                <p className="text-ink-600 mb-3">
                  Depth {graphQuery.data?.depth ?? 0}:{" "}
                  {(graphQuery.data?.nodes ?? []).length} connected{" "}
                  {(graphQuery.data?.nodes ?? []).length === 1 ? "node" : "nodes"}
                </p>
                <ul className="space-y-1 max-h-64 overflow-auto">
                  {(graphQuery.data?.nodes ?? []).map((n) => (
                    <li key={n.node_id} className="font-mono-data text-xs">
                      {titleCaseSnake(n.kind)} · {n.label}
                      <span className="ml-2 text-ink-400">
                        via {titleCaseSnake(n.via_edge_kind)}
                      </span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        ) : null}

        {tab === "ownership" ? (
          <DataTable
            columns={ownershipColumns}
            data={ownershipQuery.data ?? []}
            rowKey={(o) => o.id}
            isLoading={ownershipQuery.isLoading}
            error={ownershipQuery.isError ? "Failed to load ownership" : null}
            onRetry={() => void ownershipQuery.refetch()}
            emptyTitle="No ownership records"
          />
        ) : null}

        {tab === "accreditations" ? (
          <DataTable
            columns={accColumns}
            data={accForAgent}
            rowKey={(a) => a.id}
            isLoading={accQuery.isLoading}
            error={accQuery.isError ? "Failed to load accreditations" : null}
            onRetry={() => void accQuery.refetch()}
            emptyTitle="No accreditations"
          />
        ) : null}

        {tab === "findings" ? (
          <DataTable
            columns={findingColumns}
            data={findingsForAgent}
            rowKey={(f) => f.id}
            isLoading={findingsQuery.isLoading}
            error={findingsQuery.isError ? "Failed to load findings" : null}
            onRetry={() => void findingsQuery.refetch()}
            emptyTitle="No findings"
          />
        ) : null}
      </Panel>
      )}
    </div>
  );
}
