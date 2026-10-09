import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { useProbeRunDetail, useProbeRuns, useProbeSuites } from "@/api/queries";
import type { ProbeRun, ProbeSuite, ProbeCaseResult } from "@/api/types";
import { Digest } from "@/components/Digest";
import { RelativeTime } from "@/components/RelativeTime";
import { titleCaseSnake } from "@/lib/formatters";

function OracleBadge({ row }: { row: ProbeCaseResult }) {
  const tone =
    row.oracle_verdict === "pass"
      ? "bg-ok-soft text-ok-fg border-ok-fg/20"
      : row.oracle_verdict === "needs-review"
        ? "bg-warn-soft text-warn-fg border-warn-fg/20"
        : "bg-risk-soft text-risk-fg border-risk-fg/20";
  return (
    <span className={`inline-flex rounded-md border px-2 py-0.5 text-micro font-medium ${tone}`}>
      Oracle: {titleCaseSnake(row.oracle_verdict)}
      {row.execution_verified ? " · verified" : ""}
    </span>
  );
}

function JudgeBadge({ row }: { row: ProbeCaseResult }) {
  if (!row.judge_advisory) {
    return (
      <span className="text-micro text-ink-400">
        No model judge — {row.ambiguous ? "needs human review" : "not consulted"}
      </span>
    );
  }
  return (
    <span className="inline-flex rounded-md border border-line-300 bg-bg-sunk px-2 py-0.5 text-micro text-ink-600">
      Model opinion: {titleCaseSnake(row.judge_advisory.verdict)}
      {row.judge_advisory.disagrees_with_oracle ? " · disagrees with oracle" : ""}
    </span>
  );
}

export default function AssuranceScreen() {
  const suitesQuery = useProbeSuites();
  const runsQuery = useProbeRuns({ limit: "40" });
  const [selectedRunId, setSelectedRunId] = useState<string>("");
  const detailQuery = useProbeRunDetail(selectedRunId);

  const runColumns: ColumnDef<ProbeRun>[] = [
    {
      id: "started",
      header: "Started",
      sortValue: (r) => r.started_at,
      accessor: (r) => (
        <button
          type="button"
          className="text-info-fg hover:underline"
          onClick={() => setSelectedRunId(r.id)}
        >
          <RelativeTime iso={r.started_at} mode="table" />
        </button>
      ),
    },
    {
      id: "result",
      header: "Oracle gate",
      accessor: (r) => (
        <span className={r.result === "pass" ? "text-ok-fg font-medium" : "text-risk-fg font-medium"}>
          {r.result ?? "—"}
        </span>
      ),
    },
    {
      id: "score",
      header: "Passed / run",
      accessor: (r) => (
        <span className="font-mono-data">
          {r.probes_passed}/{r.probes_run}
        </span>
      ),
    },
    {
      id: "agent",
      header: "Agent",
      accessor: (r) => (
        <Link to={`/agents/${r.agent_id}`} className="font-mono-data text-info-fg hover:underline">
          {r.agent_id.slice(0, 8)}…
        </Link>
      ),
    },
  ];

  const suiteColumns: ColumnDef<ProbeSuite>[] = [
    { id: "name", header: "Suite", accessor: (s) => s.name },
    { id: "slug", header: "Slug", accessor: (s) => <span className="font-mono-data">{s.slug}</span> },
    {
      id: "owasp",
      header: "OWASP agentic coverage",
      accessor: (s) => s.owasp_coverage.map(titleCaseSnake).join(", ") || "—",
    },
    {
      id: "digest",
      header: "Content digest",
      accessor: (s) => (s.content_digest ? <Digest value={s.content_digest} /> : "—"),
    },
  ];

  const caseColumns: ColumnDef<ProbeCaseResult>[] = useMemo(
    () => [
      { id: "id", header: "Probe", accessor: (c) => <span className="font-mono-data">{c.probe_id}</span> },
      {
        id: "oracle",
        header: "Deterministic oracle",
        accessor: (c) => <OracleBadge row={c} />,
      },
      {
        id: "judge",
        header: "Advisory judge",
        accessor: (c) => <JudgeBadge row={c} />,
      },
      {
        id: "gap",
        header: "Recognition–execution",
        accessor: (c) =>
          c.recognition_execution_gap ? (
            <span className="text-warn-fg font-medium">Acknowledged rule, still violated</span>
          ) : (
            "—"
          ),
      },
    ],
    [],
  );

  const summary = detailQuery.data?.summary;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Stress testing & rule gaps"
        explain="Probe suites use deterministic oracles over observable runtime effects. Model judges are advisory only and never change the release gate."
      />

      <Panel title="Built-in probe suites">
        <DataTable
          columns={suiteColumns}
          data={suitesQuery.data ?? []}
          rowKey={(s) => s.id}
          isLoading={suitesQuery.isLoading}
          emptyTitle="No probe suites"
        />
      </Panel>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Recent probe runs" noPadding>
          <DataTable
            columns={runColumns}
            data={runsQuery.data?.items ?? []}
            rowKey={(r) => r.id}
            isLoading={runsQuery.isLoading}
            emptyTitle="No probe runs yet"
          />
        </Panel>

        <Panel title="Run detail — oracle vs advisory">
          {!selectedRunId ? (
            <p className="text-body text-ink-secondary">Select a run to inspect per-probe verdicts.</p>
          ) : detailQuery.isLoading ? (
            <p className="text-body text-ink-secondary">Loading…</p>
          ) : detailQuery.data ? (
            <div className="space-y-4">
              {summary ? (
                <dl className="grid grid-cols-2 gap-2 text-table text-ink-600">
                  <div>
                    <dt className="text-ink-400">Execution verified pass</dt>
                    <dd className="font-mono-data text-ok-fg">{summary.execution_verified_pass}</dd>
                  </div>
                  <div>
                    <dt className="text-ink-400">Execution verified fail</dt>
                    <dd className="font-mono-data text-risk-fg">{summary.execution_verified_fail}</dd>
                  </div>
                  <div>
                    <dt className="text-ink-400">Judge advisory pass</dt>
                    <dd className="font-mono-data">{summary.judge_advisory_pass}</dd>
                  </div>
                  <div>
                    <dt className="text-ink-400">Judge advisory fail</dt>
                    <dd className="font-mono-data">{summary.judge_advisory_fail}</dd>
                  </div>
                  <div>
                    <dt className="text-ink-400">Valid rollouts / budget</dt>
                    <dd className="font-mono-data">
                      {summary.valid_rollouts}/{summary.attempt_budget}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-ink-400">Release gate</dt>
                    <dd>
                      {summary.gate_blocks_release ? (
                        <span className="text-risk-fg font-medium">Blocking</span>
                      ) : (
                        <span className="text-ink-600">
                          {titleCaseSnake(summary.gate_level)} — does not block
                        </span>
                      )}
                    </dd>
                  </div>
                </dl>
              ) : null}
              <DataTable
                columns={caseColumns}
                data={detailQuery.data.results}
                rowKey={(c) => c.probe_id}
                emptyTitle="No probe results"
              />
            </div>
          ) : null}
        </Panel>
      </div>
    </div>
  );
}
