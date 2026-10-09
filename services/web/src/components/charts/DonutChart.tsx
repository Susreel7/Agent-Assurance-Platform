/**
 * A ring with a total in the middle, for a breakdown of one population.
 *
 * Only used where the parts genuinely sum to a whole — the health of every agent, the
 * outcome of every run. A donut of things that do not add up to anything is the most
 * common way a dashboard lies by accident.
 *
 * Drawn with `stroke-dasharray` on circles rather than with arc paths. Same picture,
 * a tenth of the arithmetic, and no chance of the large-arc flag being wrong at exactly
 * the moment one slice crosses half the ring.
 */

export type DonutSlice = { label: string; value: number; color: string; href?: string };

type DonutChartProps = {
  slices: DonutSlice[];
  size?: number;
  thickness?: number;
  centerValue?: string;
  centerLabel?: string;
};

export function DonutChart({
  slices,
  size = 148,
  thickness = 16,
  centerValue,
  centerLabel,
}: DonutChartProps) {
  const total = slices.reduce((sum, s) => sum + s.value, 0);
  const radius = (size - thickness) / 2;
  const circumference = 2 * Math.PI * radius;

  let consumed = 0;

  return (
    <svg width={size} height={size} role="img" aria-label={centerLabel ?? "Breakdown"}>
      <g transform={`rotate(-90 ${size / 2} ${size / 2})`}>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          stroke="var(--bg-sunk)"
          strokeWidth={thickness}
        />
        {total > 0 &&
          slices.map((slice) => {
            const fraction = slice.value / total;
            const dash = fraction * circumference;
            const offset = -consumed * circumference;
            consumed += fraction;
            if (slice.value === 0) return null;
            return (
              <circle
                key={slice.label}
                cx={size / 2}
                cy={size / 2}
                r={radius}
                fill="none"
                stroke={slice.color}
                strokeWidth={thickness}
                // The 1-unit gap keeps adjacent slices legible without a border colour
                // that would have to change with the panel background.
                strokeDasharray={`${Math.max(dash - 1, 0)} ${circumference}`}
                strokeDashoffset={offset}
                strokeLinecap="butt"
              >
                <title>{`${slice.label}: ${slice.value.toLocaleString()}`}</title>
              </circle>
            );
          })}
      </g>

      {centerValue ? (
        <text
          x={size / 2}
          y={size / 2 - 2}
          textAnchor="middle"
          className="fill-ink-900 text-[22px] font-semibold"
        >
          {centerValue}
        </text>
      ) : null}
      {centerLabel ? (
        <text
          x={size / 2}
          y={size / 2 + 15}
          textAnchor="middle"
          className="fill-ink-400 text-[11px]"
        >
          {centerLabel}
        </text>
      ) : null}
    </svg>
  );
}

/**
 * The key for a donut, as rows rather than a legend strip, so the numbers line up.
 *
 * `format` exists because the values a donut is drawn from are often in a unit nobody
 * reads — money arrives as millionths of a dollar — and converting before passing them
 * in would change the proportions the ring is drawn at.
 */
export function DonutLegend({
  slices,
  format = (value: number) => value.toLocaleString(),
}: {
  slices: DonutSlice[];
  format?: (value: number) => string;
}) {
  const total = slices.reduce((sum, s) => sum + s.value, 0);
  return (
    <ul className="space-y-1.5">
      {slices.map((slice) => (
        <li key={slice.label} className="flex items-center gap-2 text-body">
          <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: slice.color }} />
          <span className="flex-1 truncate text-ink-600">{slice.label}</span>
          <span className="font-mono text-table text-ink-900">{format(slice.value)}</span>
          <span className="w-11 text-right font-mono text-micro text-ink-400">
            {total ? `${Math.round((slice.value / total) * 100)}%` : "—"}
          </span>
        </li>
      ))}
    </ul>
  );
}
