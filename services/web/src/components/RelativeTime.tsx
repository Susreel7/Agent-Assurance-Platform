import { formatRelative, formatTableDate } from "@/lib/dates";

type RelativeTimeProps = {
  iso: string;
  mode?: "relative" | "table";
};

export function RelativeTime({ iso, mode = "relative" }: RelativeTimeProps) {
  const text = mode === "table" ? formatTableDate(iso) : formatRelative(iso);
  return (
    <time dateTime={iso} title={formatTableDate(iso)} className="tabular-nums">
      {text}
    </time>
  );
}
