import { useAgentBom } from "@/api/queries";
import type { BomComponent, ComponentKind } from "@/api/types";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { Digest } from "@/components/Digest";
import { titleCaseSnake } from "@/lib/formatters";

const KIND_ORDER: ComponentKind[] = [
  "model",
  "prompt",
  "tool",
  "mcp_server",
  "library",
  "dataset",
  "sub_agent",
  "vector_store",
  "data_source",
  "guardrail",
];

type AgentBomTabProps = {
  agentId: string;
  versionId?: string;
};

export function AgentBomTab({ agentId, versionId }: AgentBomTabProps) {
  const query = useAgentBom(agentId, versionId);
  const items = query.data ?? [];

  const grouped = KIND_ORDER.map((kind) => ({
    kind,
    rows: items.filter((c) => c.kind === kind),
  })).filter((g) => g.rows.length > 0);

  const columns: ColumnDef<BomComponent>[] = [
    { id: "name", header: "Name", sortValue: (c) => c.name, accessor: (c) => c.name },
    {
      id: "version",
      header: "Version",
      accessor: (c) => c.version ?? "—",
    },
    { id: "provider", header: "Provider", accessor: (c) => c.provider ?? "—" },
    {
      id: "digest",
      header: "Digest",
      accessor: (c) => (c.digest ? <Digest value={c.digest} /> : "—"),
    },
  ];

  if (grouped.length === 0) {
    return (
      <DataTable
        columns={columns}
        data={[]}
        rowKey={(c) => c.id}
        isLoading={query.isLoading}
        error={query.isError ? "Failed to load BOM" : null}
        onRetry={() => void query.refetch()}
        emptyTitle="No BOM components"
      />
    );
  }

  return (
    <div className="space-y-6">
      {grouped.map(({ kind, rows }) => (
        <section key={kind}>
          <h3 className="text-xs font-semibold uppercase text-ink-600 mb-2">
            {titleCaseSnake(kind)}
          </h3>
          <DataTable
            columns={columns}
            data={rows}
            rowKey={(c) => c.id}
            isLoading={query.isLoading}
            error={query.isError ? "Failed to load BOM" : null}
            onRetry={() => void query.refetch()}
            stickyHeader={false}
          />
        </section>
      ))}
    </div>
  );
}
