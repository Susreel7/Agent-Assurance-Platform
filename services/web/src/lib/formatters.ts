export function formatPercent(value: number, digits = 1): string {
  return `${value.toFixed(digits)}%`;
}

export function formatSemverRange(from: string | null, to: string): string {
  return from ? `${from} → ${to}` : to;
}

export function formatPrincipal(principalId: string): string {
  const idx = principalId.indexOf(":");
  if (idx === -1) return principalId;
  return principalId.slice(idx + 1);
}

export function truncateMiddle(text: string, max = 24): string {
  if (text.length <= max) return text;
  const half = Math.floor((max - 1) / 2);
  return `${text.slice(0, half)}…${text.slice(-half)}`;
}

export function formatGbp(amount: number): string {
  return new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP" }).format(amount);
}

/**
 * Money, from the integer millionths of a dollar the API speaks in.
 *
 * The API never sends a float or a formatted string for money, so this is the one place
 * the conversion happens; see the operations schemas for why. Sub-cent totals are shown
 * to four decimal places rather than rounded to `$0.00`, because a per-run cost really
 * is a fraction of a cent and rounding it away makes a busy agent look free.
 */
export function formatUsdMicros(micros: number, opts?: { compact?: boolean }): string {
  const dollars = micros / 1_000_000;
  if (opts?.compact && Math.abs(dollars) >= 1000) {
    return `$${(dollars / 1000).toFixed(dollars >= 10_000 ? 0 : 1)}k`;
  }
  if (dollars !== 0 && Math.abs(dollars) < 0.01) return `$${dollars.toFixed(4)}`;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: Math.abs(dollars) >= 100 ? 0 : 2,
  }).format(dollars);
}

/** Large counts, shortened. Used in stat cards where four digits is already too many. */
export function formatCompact(value: number): string {
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 10_000) return `${Math.round(value / 1000)}k`;
  if (Math.abs(value) >= 1000) return `${(value / 1000).toFixed(1)}k`;
  return value.toLocaleString();
}

/** A duration in milliseconds, at the precision a person would read it out loud. */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`;
  const minutes = Math.floor(ms / 60_000);
  const seconds = Math.round((ms % 60_000) / 1000);
  return `${minutes}m ${seconds}s`;
}

/** Percentage change from one window to the one before it. */
export function deltaPct(current: number, previous: number): number {
  if (previous === 0) return current === 0 ? 0 : 100;
  return ((current - previous) / previous) * 100;
}

export function titleCaseSnake(value: string): string {
  return value
    .split("_")
    .map((w) => (w ? w[0]?.toUpperCase() + w.slice(1) : w))
    .join(" ");
}
