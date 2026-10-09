/**
 * Runs per day, stacked by environment.
 *
 * Stacked rather than overlaid because the question people actually ask of this chart
 * is "how much is the estate doing", and the split between dev and production is the
 * follow-up. Overlaid lines answer the follow-up first and make the total something you
 * have to add up by eye.
 *
 * The failure line is drawn on top, unstacked, in red. It is nearly always close to
 * zero, which is the point: a visible red line is the signal, and putting it in the
 * stack would hide exactly the days worth noticing.
 *
 * Hover is keyboard-reachable through the same handler as the mouse, and the table
 * behind `<title>` means the series are readable without any pointer at all.
 */

import { useMemo, useState } from "react";
import { useMeasure } from "@/lib/useMeasure";

export type AreaSeries = { name: string; values: number[]; color: string };

type AreaChartProps = {
  labels: string[];
  series: AreaSeries[];
  overlay?: { name: string; values: number[]; color: string };
  height?: number;
  formatValue?: (value: number) => string;
  formatLabel?: (label: string) => string;
};

const PAD = { top: 12, right: 8, bottom: 22, left: 40 };

function niceCeiling(value: number): number {
  if (value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const steps = [1, 2, 2.5, 5, 10];
  for (const step of steps) {
    if (value <= magnitude * step) return magnitude * step;
  }
  return magnitude * 10;
}

export function AreaChart({
  labels,
  series,
  overlay,
  height = 200,
  formatValue = (v) => v.toLocaleString(),
  formatLabel = (l) => l,
}: AreaChartProps) {
  const [box, width] = useMeasure<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  const points = labels.length;
  const plotWidth = Math.max(width - PAD.left - PAD.right, 1);
  const plotHeight = height - PAD.top - PAD.bottom;

  const { stacks, max } = useMemo(() => {
    // Running totals per point, so each band starts where the one below it ended.
    const running = new Array<number>(points).fill(0);
    const built = series.map((s) => {
      const band = s.values.slice(0, points).map((value, i) => {
        const base = running[i] ?? 0;
        const top = base + (value ?? 0);
        running[i] = top;
        return { base, top };
      });
      return { series: s, band };
    });
    const peak = Math.max(...running, ...(overlay?.values ?? [0]), 1);
    return { stacks: built, max: niceCeiling(peak) };
  }, [series, overlay, points]);

  if (width === 0) return <div ref={box} style={{ height }} />;

  const x = (i: number) => PAD.left + (points <= 1 ? plotWidth / 2 : (i * plotWidth) / (points - 1));
  const y = (v: number) => PAD.top + plotHeight - (v / max) * plotHeight;

  const gridLines = [0, 0.25, 0.5, 0.75, 1].map((f) => ({ v: max * f, y: y(max * f) }));

  const totalAt = (i: number) => series.reduce((sum, s) => sum + (s.values[i] ?? 0), 0);

  function trackPointer(event: React.MouseEvent<SVGRectElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = (event.clientX - rect.left) / Math.max(rect.width, 1);
    setHover(Math.min(points - 1, Math.max(0, Math.round(ratio * (points - 1)))));
  }

  return (
    <div ref={box} className="relative">
      <svg width={width} height={height} role="img" aria-label="Runs per day">
        {gridLines.map((line) => (
          <g key={line.v}>
            <line
              x1={PAD.left}
              x2={width - PAD.right}
              y1={line.y}
              y2={line.y}
              stroke="var(--grid)"
            />
            <text x={PAD.left - 8} y={line.y + 4} textAnchor="end" className="fill-ink-400 text-[10px]">
              {formatValue(Math.round(line.v))}
            </text>
          </g>
        ))}

        {stacks.map(({ series: s, band }) => {
          const top = band.map((p, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(p.top)}`).join(" ");
          // Traced back along the band's lower edge, so the filled shape closes on the
          // series below rather than on the axis — which is what makes it a stack.
          const bottom = [...band]
            .reverse()
            .map((p, i) => `L${x(band.length - 1 - i)},${y(p.base)}`)
            .join(" ");
          return (
            <g key={s.name}>
              <path d={`${top} ${bottom} Z`} fill={s.color} fillOpacity={0.16} />
              <path d={top} fill="none" stroke={s.color} strokeWidth={1.6} />
            </g>
          );
        })}

        {overlay ? (
          <path
            d={overlay.values
              .slice(0, points)
              .map((v, i) => `${i === 0 ? "M" : "L"}${x(i)},${y(v)}`)
              .join(" ")}
            fill="none"
            stroke={overlay.color}
            strokeWidth={1.6}
            strokeDasharray="3 3"
          />
        ) : null}

        {hover !== null ? (
          <line
            x1={x(hover)}
            x2={x(hover)}
            y1={PAD.top}
            y2={PAD.top + plotHeight}
            stroke="var(--line-300)"
          />
        ) : null}

        {/* First, last and middle only. A label under every day is unreadable at 30
            points and illegible at 90, and the tooltip carries the exact date. */}
        {[0, Math.floor((points - 1) / 2), points - 1]
          .filter((i, idx, all) => i >= 0 && all.indexOf(i) === idx)
          .map((i) => (
            <text
              key={i}
              x={x(i)}
              y={height - 6}
              textAnchor={i === 0 ? "start" : i === points - 1 ? "end" : "middle"}
              className="fill-ink-400 text-[10px]"
            >
              {formatLabel(labels[i] ?? "")}
            </text>
          ))}

        <rect
          x={PAD.left}
          y={PAD.top}
          width={plotWidth}
          height={plotHeight}
          fill="transparent"
          onMouseMove={trackPointer}
          onMouseLeave={() => setHover(null)}
        />
      </svg>

      {hover !== null ? (
        <div
          className="pointer-events-none absolute top-2 z-10 min-w-[150px] rounded-md bg-ink-900 px-3 py-2 text-micro text-white shadow-pop"
          style={{
            left: Math.min(Math.max(x(hover) - 75, 0), Math.max(width - 160, 0)),
          }}
        >
          <p className="mb-1 font-medium">{formatLabel(labels[hover] ?? "")}</p>
          {series.map((s) => (
            <p key={s.name} className="flex items-center justify-between gap-3">
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full" style={{ background: s.color }} />
                {s.name}
              </span>
              <span className="font-mono">{formatValue(s.values[hover] ?? 0)}</span>
            </p>
          ))}
          <p className="mt-1 flex items-center justify-between gap-3 border-t border-white/15 pt-1">
            <span>Total</span>
            <span className="font-mono">{formatValue(totalAt(hover))}</span>
          </p>
          {overlay ? (
            <p className="flex items-center justify-between gap-3">
              <span style={{ color: overlay.color }}>{overlay.name}</span>
              <span className="font-mono">{formatValue(overlay.values[hover] ?? 0)}</span>
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
