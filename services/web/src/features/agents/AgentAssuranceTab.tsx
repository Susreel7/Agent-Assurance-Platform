import { useAgent, useRuleGaps } from "@/api/queries";
import { Panel } from "@/components/Panel";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import type { RuleGap } from "@/api/types";
import { titleCaseSnake } from "@/lib/formatters";

type Props = {
  agentId: string;
};

export function AgentAssuranceTab({ agentId }: Props) {
  const agentQuery = useAgent(agentId);
  const versionId = agentQuery.data?.current_version_id ?? "";
  const gapsQuery = useRuleGaps(agentId, versionId);

  const columns: ColumnDef<RuleGap>[] = [
    {
      id: "framework",
      header: "Framework",
      accessor: (g) => g.framework_slug,
    },
    {
      id: "control",
      header: "Control",
      accessor: (g) => <span className="font-mono-data">{g.control_ref}</span>,
    },
    {
      id: "template",
      header: "Template",
      accessor: (g) => g.template_id,
    },
    {
      id: "status",
      header: "Status",
      accessor: (g) => (
        <span
          className={
            g.status === "missing" || g.status === "conflict"
              ? "font-medium text-risk-fg"
              : g.status === "partial"
                ? "text-warn-fg"
                : "text-ok-fg"
          }
        >
          {titleCaseSnake(g.status)}
        </span>
      ),
    },
    {
      id: "required",
      header: "Required obligation (template)",
      accessor: (g) => <span className="text-table">{g.required_statement}</span>,
    },
    {
      id: "suggest",
      header: "Suggested import",
      accessor: (g) =>
        g.suggested_obligation ? (
          <button
            type="button"
            className="text-info-fg hover:underline text-table"
            onClick={() => void navigator.clipboard.writeText(JSON.stringify(g.suggested_obligation, null, 2))}
          >
            Copy JSON
          </button>
        ) : (
          "—"
        ),
    },
  ];

  return (
    <div className="flex flex-col gap-4 p-4">
      <Panel title="Rule gap analysis (template mapped)">
        <p className="mb-3 text-body text-ink-secondary">
          Compares regulation controls with mapped obligation templates against this agent&apos;s
          declared rule obligations. This is explicit template matching — not semantic inference.
        </p>
        <DataTable
          columns={columns}
          data={gapsQuery.data?.gaps ?? []}
          rowKey={(g) => `${g.framework_slug}:${g.template_id}`}
          isLoading={gapsQuery.isLoading || agentQuery.isLoading}
          error={gapsQuery.isError ? "Failed to load rule gaps" : null}
          onRetry={() => void gapsQuery.refetch()}
          emptyTitle="No mapped templates for this agent's frameworks"
          emptyDescription="Bind customer frameworks and control mappings with obligation templates to see gaps."
        />
      </Panel>
    </div>
  );
}
