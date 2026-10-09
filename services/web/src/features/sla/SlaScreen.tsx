import { useMemo, useState } from "react";
import { useQueries } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { api } from "@/api/client";
import { qk, useEngagements, useSloDefinitions } from "@/api/queries";
import type { EngagementSloRollup, SloDefinition, SloSummary } from "@/api/types";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { Panel } from "@/components/Panel";
import { formatGbp, titleCaseSnake } from "@/lib/formatters";
import { SloAttainmentChart } from "./SloAttainmentChart";

/** Attainment, breaches and credit are not on the SLO row.
 *
 * `/v1/slos` returns the definitions — target, unit, window. Whether a target is being
 * met means scanning the measurement history, so the API exposes that per engagement on
 * a separate endpoint, and this screen joins the two.
 *
 * One request per engagement rather than one per SLO. An estate has a handful of
 * engagements and tens of SLOs, so this is the cheaper side of the join, and
 * `useQueries` keeps them in one cached, deduped batch.
 */
function useSloSummaries(engagementIds: string[]) {
  const results = useQueries({
    queries: engagementIds.map((id) => ({
      queryKey: qk.engagementSloSummary(id),
      queryFn: () => api.get<EngagementSloRollup>(`/v1/slos/-/engagements/${id}/summary`),
    })),
  });

  return useMemo(() => {
    const bySloId = new Map<string, SloSummary>();
    for (const r of results) {
      for (const s of r.data?.slos ?? []) bySloId.set(s.slo_id, s);
    }
    return { bySloId, isLoading: results.some((r) => r.isLoading) };
  }, [results]);
}

// Every decimal on these endpoints is serialised as a string, because Pydantic renders
// Decimal that way and money must not round-trip through a float. Parsing at the edge
// keeps the rest of the screen working in numbers.
const num = (v: string | null | undefined): number | null =>
  v === null || v === undefined || v === "" ? null : Number(v);

/** A target is met differently depending on which way "good" points.
 *
 * Availability and success rate are floors — higher is better. Latency and resolution
 * time are ceilings. Comparing every kind the same way would report every latency SLO as
 * failing the moment it performed well.
 */
const LOWER_IS_BETTER: SloDefinition["kind"][] = [
  "latency_p50",
  "latency_p95",
  "latency_p99",
  "resolution_p1",
  "resolution_p2",
];

function isMeetingTarget(slo: SloDefinition, attainment: number | null): boolean | null {
  const target = num(slo.target);
  if (attainment === null || target === null) return null;
  return LOWER_IS_BETTER.includes(slo.kind) ? attainment <= target : attainment >= target;
}

export default function SlaScreen() {
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const slosQuery = useSloDefinitions();
  const engagementsQuery = useEngagements({ limit: "200" });

  // Memoised because `?? []` produces a fresh array on every render, which would make
  // the engagement-id memo below recompute forever and refire one query per engagement
  // with it.
  const slos = useMemo(() => slosQuery.data ?? [], [slosQuery.data]);

  const engagementName = new Map(
    (engagementsQuery.data?.items ?? []).map((e) => [
      e.id,
      `${e.customer_display_name} · ${e.name}`,
    ]),
  );

  const engagementIds = useMemo(
    () => [...new Set(slos.map((s) => s.engagement_id).filter((id): id is string => Boolean(id)))],
    [slos],
  );
  const summaries = useSloSummaries(engagementIds);

  const columns: ColumnDef<SloDefinition>[] = [
    {
      id: "engagement",
      header: "Engagement",
      sortValue: (s) => (s.engagement_id ? engagementName.get(s.engagement_id) ?? "" : ""),
      accessor: (s) =>
        s.engagement_id ? (
          <Link to={`/engagements/${s.engagement_id}`} className="text-info-fg hover:underline">
            {engagementName.get(s.engagement_id) ?? "—"}
          </Link>
        ) : (
          <span className="text-ink-400">Estate-wide</span>
        ),
    },
    {
      id: "kind",
      header: "Kind",
      sortValue: (s) => s.kind,
      accessor: (s) => titleCaseSnake(s.kind),
    },
    {
      id: "target",
      header: "Target",
      align: "right",
      sortValue: (s) => num(s.target) ?? 0,
      accessor: (s) => (
        <span className="tabular-nums">
          {s.target}
          {s.unit ? ` ${s.unit}` : ""}
        </span>
      ),
    },
    {
      id: "attainment",
      header: "Measured",
      align: "right",
      sortValue: (s) => num(summaries.bySloId.get(s.id)?.attainment) ?? -1,
      accessor: (s) => {
        const attainment = num(summaries.bySloId.get(s.id)?.attainment);
        if (attainment === null) return <span className="text-ink-400">No data</span>;
        const meeting = isMeetingTarget(s, attainment);
        return (
          <span
            className={
              meeting === false ? "tabular-nums text-risk-fg font-medium" : "tabular-nums"
            }
          >
            {attainment}
            {s.unit ? ` ${s.unit}` : ""}
          </span>
        );
      },
    },
    {
      id: "measurement_window",
      header: "Window",
      accessor: (s) => titleCaseSnake(s.measurement_window),
    },
    {
      id: "breaches",
      header: "Open breaches",
      align: "right",
      sortValue: (s) => summaries.bySloId.get(s.id)?.open_breach_count ?? 0,
      accessor: (s) => {
        const count = summaries.bySloId.get(s.id)?.open_breach_count ?? 0;
        return (
          <span className={count > 0 ? "tabular-nums text-warn-fg font-medium" : "tabular-nums"}>
            {count}
          </span>
        );
      },
    },
    {
      id: "credit",
      header: "Credit owed",
      align: "right",
      sortValue: (s) => num(summaries.bySloId.get(s.id)?.total_credit_gbp) ?? 0,
      accessor: (s) => {
        const credit = num(summaries.bySloId.get(s.id)?.total_credit_gbp);
        if (credit === null || credit === 0) return <span className="text-ink-400">—</span>;
        return <span className="tabular-nums text-risk-fg">{formatGbp(credit)}</span>;
      },
    },
    {
      id: "chart",
      header: "Trend",
      accessor: (s) => (
        <button
          type="button"
          className="text-info-fg text-table underline"
          onClick={(e) => {
            e.stopPropagation();
            setExpandedId(expandedId === s.id ? null : s.id);
          }}
          aria-expanded={expandedId === s.id}
          aria-label={`Toggle attainment chart for ${titleCaseSnake(s.kind)}`}
        >
          {expandedId === s.id ? "Hide" : "Show"}
        </button>
      ),
    },
  ];

  const expanded = expandedId ? slos.find((s) => s.id === expandedId) : undefined;

  return (
    <div className="space-y-4">
      <PageHeader
        title="Service levels"
        explain="The performance you promised each client — uptime, error rates, response times — and whether you are actually meeting it. Missing a target can owe them money."
      />

      <Panel noPadding>
        <DataTable
          columns={columns}
          data={slos}
          rowKey={(s) => s.id}
          isLoading={slosQuery.isLoading}
          error={
            slosQuery.isError
              ? slosQuery.error instanceof Error
                ? slosQuery.error.message
                : "Failed to load service levels"
              : null
          }
          onRetry={() => void slosQuery.refetch()}
          emptyTitle="No service levels defined"
          emptyDescription="Service levels are set per engagement. Until one is defined there is no target to measure against, and no credit can be owed."
        />
        {expanded ? (
          <div className="border-t border-line-200 px-4 py-3">
            <SloAttainmentChart sloId={expanded.id} target={num(expanded.target) ?? 0} />
          </div>
        ) : null}
      </Panel>
    </div>
  );
}
