/**
 * A ranked list where the bar is the row.
 *
 * Used for everything shaped "which of these is biggest" — models by spend, frameworks
 * by share, tools by calls. A pie would need a legend, and a legend forces the reader
 * to look somewhere else to find out what a slice is.
 *
 * Bars are scaled against the largest value in the list, not against the total. Scaling
 * against the total makes a list of ten roughly-equal things look like ten empty rows.
 */

import clsx from "clsx";
import { Link } from "react-router-dom";

export type BarListItem = {
  label: string;
  value: number;
  /** What appears at the right of the row. Defaults to the value, comma-grouped. */
  display?: string;
  /** Small grey text under the label, for a denominator or a second metric. */
  meta?: string;
  color?: string;
  href?: string;
};

type BarListProps = {
  items: BarListItem[];
  emptyMessage?: string;
  max?: number;
};

export function BarList({ items, emptyMessage = "Nothing recorded yet.", max }: BarListProps) {
  if (items.length === 0) {
    return <p className="py-6 text-center text-body text-ink-400">{emptyMessage}</p>;
  }

  const peak = max ?? Math.max(...items.map((i) => i.value), 1);

  return (
    <ul className="space-y-1">
      {items.map((item) => {
        const pct = Math.max((item.value / peak) * 100, item.value > 0 ? 1.5 : 0);
        const body = (
          <>
            <span
              aria-hidden
              className="absolute inset-y-0 left-0 rounded-[5px] transition-[width] duration-300"
              style={{ width: `${pct}%`, background: item.color ?? "var(--accent-soft)" }}
            />
            <span className="relative flex min-w-0 flex-col">
              <span className="truncate text-body text-ink-900">{item.label}</span>
              {item.meta ? <span className="text-micro text-ink-400">{item.meta}</span> : null}
            </span>
            <span className="relative shrink-0 font-mono text-table text-ink-700">
              {item.display ?? item.value.toLocaleString()}
            </span>
          </>
        );

        const shell =
          "relative flex items-center justify-between gap-3 overflow-hidden rounded-md px-2.5 py-1.5";

        return (
          <li key={item.label}>
            {item.href ? (
              <Link to={item.href} className={clsx(shell, "hover:no-underline hover:brightness-95")}>
                {body}
              </Link>
            ) : (
              <div className={shell}>{body}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
