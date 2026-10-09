const TABLE_FMT: Intl.DateTimeFormatOptions = {
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: "UTC",
};

export function formatTableDate(iso: string): string {
  const d = new Date(iso);
  const parts = new Intl.DateTimeFormat("en-GB", TABLE_FMT).formatToParts(d);
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? "";
  return `${get("year")}-${get("month")}-${get("day")} ${get("hour")}:${get("minute")} UTC`;
}

/**
 * A bare date, for a chart axis or a day bucket.
 *
 * Parsed as UTC rather than through `new Date("2026-09-14")`, which is UTC midnight and
 * so renders as the *previous* day for anyone west of Greenwich. The API buckets by UTC
 * day, so the label has to be read the same way or a chart is silently off by one for
 * half the world.
 */
export function formatDay(day: string): string {
  const [year, month, date] = day.slice(0, 10).split("-").map(Number);
  if (!year || !month || !date) return day;
  return new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(Date.UTC(year, month - 1, date));
}

export function formatRelative(iso: string, now = new Date()): string {
  const then = new Date(iso).getTime();
  const diffMs = now.getTime() - then;
  const abs = Math.abs(diffMs);
  const future = diffMs < 0;
  const minute = 60_000;
  const hour = 60 * minute;
  const day = 24 * hour;

  let label: string;
  if (abs < minute) label = "just now";
  else if (abs < hour) label = `${Math.round(abs / minute)} minutes`;
  else if (abs < day) label = `${Math.round(abs / hour)} hours`;
  else label = `${Math.round(abs / day)} days`;

  if (label === "just now") return label;
  return future ? `in ${label}` : `${label} ago`;
}
