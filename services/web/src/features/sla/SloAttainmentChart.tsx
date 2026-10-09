import { useSloMeasurements } from "@/api/queries";
import { ErrorState } from "@/components/ErrorState";
import { Skeleton } from "@/components/Skeleton";
import { formatPercent } from "@/lib/formatters";

type SloAttainmentChartProps = {
  sloId: string;
  target: number;
  width?: number;
  height?: number;
};

export function SloAttainmentChart({ sloId, target, width = 280, height = 64 }: SloAttainmentChartProps) {
  const query = useSloMeasurements(sloId);

  if (query.isLoading) {
    return <Skeleton height={`${height}px`} width={`${width}px`} />;
  }

  if (query.isError) {
    return (
      <ErrorState
        message={query.error instanceof Error ? query.error.message : "Measurements unavailable"}
        onRetry={() => void query.refetch()}
      />
    );
  }

  // A measurement covers a bucket, not an instant, and `value` arrives as a string
  // because it is a Pydantic Decimal. Both of those used to be assumed away here: the
  // sort read a `measured_at` field that does not exist, and the arithmetic below ran on
  // strings, so `max - min` produced NaN and the polyline never drew.
  const values = [...(query.data?.items ?? [])]
    .sort((a, b) => a.bucket_start.localeCompare(b.bucket_start))
    .map((m) => Number(m.value))
    .filter((v) => Number.isFinite(v));

  if (values.length === 0) {
    return <span className="text-table text-ink-400">No measurements</span>;
  }

  const min = Math.min(...values, target);
  const max = Math.max(...values, target);
  const range = max - min || 1;
  const step = values.length > 1 ? width / (values.length - 1) : width;
  const targetY = height - ((target - min) / range) * (height - 8) - 4;

  const points = values
    .map((v, i) => {
      const x = i * step;
      const y = height - ((v - min) / range) * (height - 8) - 4;
      return `${x},${y}`;
    })
    .join(" ");

  const last = values[values.length - 1];
  const lastLabel = last !== undefined ? formatPercent(last) : "";

  return (
    <svg width={width} height={height} role="img" aria-label={`SLO attainment trend, latest ${lastLabel}`}>
      <line
        x1={0}
        y1={targetY}
        x2={width}
        y2={targetY}
        stroke="var(--warn-fg)"
        strokeDasharray="4 3"
        strokeWidth={1}
      />
      <polyline fill="none" stroke="var(--info-fg)" strokeWidth={1.5} points={points} />
    </svg>
  );
}
