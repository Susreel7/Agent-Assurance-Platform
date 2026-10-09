/**
 * A run-rate sparkline sized to sit inside a table cell.
 *
 * Bars rather than a line, because these series are counts of discrete days and a line
 * implies something continuous between them. At this size the only readable question is
 * "is this agent busy, and is it steady" — anything more precise belongs on its own
 * page, which is one click away from the row this sits in.
 */

type MiniBarsProps = {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
  /** Share one scale across a column of these so the rows are comparable. */
  max?: number;
  label?: string;
};

export function MiniBars({
  values,
  width = 84,
  height = 22,
  color = "var(--accent)",
  max,
  label,
}: MiniBarsProps) {
  if (values.length === 0) {
    return <span className="text-micro text-ink-300">no runs</span>;
  }

  const peak = Math.max(max ?? Math.max(...values), 1);
  const slot = width / values.length;
  const barWidth = Math.max(slot - 1, 1);

  return (
    <svg width={width} height={height} role="img" aria-label={label ?? "Daily runs"}>
      {values.map((value, i) => {
        // Every day with any activity gets at least a pixel. A day that ran once and a
        // day that ran not at all must not look the same.
        const h = value > 0 ? Math.max((value / peak) * height, 1.5) : 0;
        return (
          <rect
            key={i}
            x={i * slot}
            y={height - h}
            width={barWidth}
            height={h}
            rx={1}
            fill={color}
            opacity={value > 0 ? 0.85 : 0}
          />
        );
      })}
    </svg>
  );
}
