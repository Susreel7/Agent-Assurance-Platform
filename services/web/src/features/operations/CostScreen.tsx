/**
 * Usage & cost — what the estate spent, and on what.
 *
 * Three attributions, because "why did this go up" has three plausible answers and
 * nobody knows which one applies until they look: a model changed, an agent got busy,
 * or something started running in production that was only ever meant to be in test.
 * The environment split is the one people forget to ask for and the one that most often
 * explains the bill.
 *
 * Every figure comes from `cost_micros`, an integer count of millionths of a dollar.
 * Floating-point money summed over a month of runs gives a total that depends on the
 * order of summation, which is not a property you want in a number that goes to
 * finance.
 */

import { useCostReport } from "@/api/queries";
import { ErrorState } from "@/components/ErrorState";
import { PageHeader } from "@/components/PageHeader";
import { Panel } from "@/components/Panel";
import { Skeleton } from "@/components/Skeleton";
import { Stat } from "@/components/Stat";
import { AreaChart } from "@/components/charts/AreaChart";
import { BarList } from "@/components/charts/BarList";
import { DonutChart, DonutLegend } from "@/components/charts/DonutChart";
import { formatDay } from "@/lib/dates";
import { deltaPct, formatCompact, formatUsdMicros } from "@/lib/formatters";
import { useWindowDays, windowLabel } from "@/lib/windowDays";

const ENV_COLOR: Record<string, string> = {
  production: "var(--series-1)",
  staging: "var(--series-2)",
  test: "var(--series-3)",
  dev: "var(--series-5)",
  retired: "var(--mute-solid)",
};

export default function CostScreen() {
  const { days } = useWindowDays();
  const { data, isLoading, isError, error, refetch } = useCostReport(days);

  if (isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton height="4rem" />
        <div className="grid gap-3 sm:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} height="104px" />
          ))}
        </div>
        <Skeleton height="300px" />
      </div>
    );
  }

  if (isError || !data) {
    return (
      <ErrorState
        title="Could not load usage"
        message={error instanceof Error ? error.message : "Unknown error"}
        onRetry={() => void refetch()}
      />
    );
  }

  const perRun = data.total_runs ? data.total_cost_micros / data.total_runs : 0;
  const envSlices = data.by_environment.map((slice) => ({
    label: slice.label,
    value: slice.cost_micros,
    color: ENV_COLOR[slice.label] ?? "var(--series-6)",
  }));

  return (
    <div className="space-y-4">
      <PageHeader
        title="Usage & cost"
        explain={`What your agents spent over ${windowLabel(days).toLowerCase()}, and which models, agents and environments it went to.`}
      />

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Total spend"
          value={formatUsdMicros(data.total_cost_micros, { compact: true })}
          explain={`against ${formatUsdMicros(data.previous_cost_micros, { compact: true })} the window before`}
          delta={{
            pct: deltaPct(data.total_cost_micros, data.previous_cost_micros),
            upIsGood: false,
          }}
        />
        <Stat
          label="Cost per run"
          value={formatUsdMicros(perRun)}
          explain={`across ${formatCompact(data.total_runs)} runs`}
        />
        <Stat label="Tokens" value={formatCompact(data.total_tokens)} explain="in and out" />
        <Stat
          label="Models in use"
          value={String(data.by_model.length)}
          explain={
            data.by_model[0]
              ? `${data.by_model[0].label} is ${data.by_model[0].share_pct.toFixed(0)}% of spend`
              : "none recorded"
          }
        />
      </div>

      <Panel
        title="Spend per day"
        explain="Runs are overlaid as a dashed line, so a spend spike without a run spike stands out as a change in what each run costs."
      >
        <AreaChart
          labels={data.by_day.map((d) => d.day)}
          series={[
            {
              name: "Spend",
              values: data.by_day.map((d) => d.cost_micros),
              color: "var(--series-1)",
            },
          ]}
          overlay={{
            name: "Runs",
            // Scaled onto the money axis so both fit one chart. The tooltip shows the
            // real run count; the line is only there to show shape.
            values: data.by_day.map((d) =>
              perRun ? Math.round(d.runs * perRun) : 0,
            ),
            color: "var(--series-3)",
          }}
          formatLabel={formatDay}
          formatValue={(v) => formatUsdMicros(v, { compact: true })}
          height={230}
        />
      </Panel>

      <div className="grid gap-3 lg:grid-cols-3">
        <Panel title="By model" explain="Largest first.">
          <BarList
            items={data.by_model.map((slice) => ({
              label: slice.label,
              value: slice.cost_micros,
              display: formatUsdMicros(slice.cost_micros, { compact: true }),
              meta: `${slice.share_pct.toFixed(0)}% · ${formatCompact(slice.tokens)} tokens`,
              color: "color-mix(in srgb, var(--series-1) 16%, transparent)",
            }))}
            emptyMessage="No model attributed any spend."
          />
        </Panel>

        <Panel title="By agent" explain="Top spenders. Click through for that agent's activity.">
          <BarList
            items={data.by_agent.map((slice) => ({
              label: slice.label,
              value: slice.cost_micros,
              display: formatUsdMicros(slice.cost_micros, { compact: true }),
              meta: `${formatCompact(slice.runs)} runs`,
              color: "color-mix(in srgb, var(--series-2) 16%, transparent)",
            }))}
            emptyMessage="No agent recorded any spend."
          />
        </Panel>

        <Panel
          title="By environment"
          explain="Production spend in a non-production environment is usually a mistake worth catching."
        >
          <div className="flex items-center justify-center pb-3 pt-1">
            <DonutChart
              slices={envSlices}
              centerValue={formatUsdMicros(data.total_cost_micros, { compact: true })}
              centerLabel="total"
            />
          </div>
          <DonutLegend slices={envSlices} format={(v) => formatUsdMicros(v, { compact: true })} />
        </Panel>
      </div>
    </div>
  );
}
