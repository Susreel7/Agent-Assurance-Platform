/**
 * Compact line spark for stat cards — last N daily values from real series only.
 */

type SparklineProps = {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
  label?: string;
};

export function Sparkline({
  values,
  width = 72,
  height = 28,
  color = "var(--accent)",
  label,
}: SparklineProps) {
  if (values.length === 0) return null;

  const peak = Math.max(...values, 1);
  const step = width / Math.max(values.length - 1, 1);
  const points = values.map((v, i) => {
    const x = i * step;
    const y = height - (v / peak) * (height - 2) - 1;
    return `${x},${y}`;
  });

  return (
    <svg width={width} height={height} role="img" aria-label={label ?? "Trend"} className="shrink-0">
      <polyline
        fill="none"
        stroke={color}
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
        points={points.join(" ")}
        opacity={0.9}
      />
    </svg>
  );
}
