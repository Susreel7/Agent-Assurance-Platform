import { titleCaseSnake } from "@/lib/formatters";

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function scalarText(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

function KeyDiff({
  before,
  after,
}: {
  before: Record<string, unknown>;
  after: Record<string, unknown>;
}) {
  const keys = [...new Set([...Object.keys(before), ...Object.keys(after)])].sort();
  return (
    <dl className="font-mono-data text-table space-y-0.5">
      {keys.map((key) => {
        const b = before[key];
        const a = after[key];
        const changed = JSON.stringify(b) !== JSON.stringify(a);
        return (
          <div key={key} className={changed ? "text-ink-900" : "text-ink-400"}>
            <dt className="inline text-ink-600">{key}: </dt>
            <dd className="inline">
              {changed ? (
                <>
                  <span className="text-risk-fg line-through">{scalarText(b)}</span>
                  {" → "}
                  <span className="text-ok-fg">{scalarText(a)}</span>
                </>
              ) : (
                scalarText(a)
              )}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

type ValueDiffProps = {
  before: unknown;
  after: unknown;
  operation: "added" | "removed" | "modified" | "renamed";
};

export function ValueDiff({ before, after, operation }: ValueDiffProps) {
  if (operation === "added") {
    return <span className="font-mono-data text-table text-ok-fg">{scalarText(after)}</span>;
  }
  if (operation === "removed") {
    return <span className="font-mono-data text-table text-risk-fg line-through">{scalarText(before)}</span>;
  }
  if (operation === "renamed") {
    return (
      <span className="font-mono-data text-table">
        <span className="text-risk-fg line-through">{scalarText(before)}</span>
        <span className="text-ink-400"> → </span>
        <span className="text-ok-fg">{scalarText(after)}</span>
        <span className="ml-2 text-ink-500">(renamed)</span>
      </span>
    );
  }

  if (isPlainObject(before) && isPlainObject(after)) {
    return <KeyDiff before={before} after={after} />;
  }

  return (
    <span className="font-mono-data text-table">
      <span className="text-risk-fg line-through">{scalarText(before)}</span>
      <span className="text-ink-400"> → </span>
      <span className="text-ok-fg">{scalarText(after)}</span>
    </span>
  );
}

export function ImpactBadges({ impacts }: { impacts: string[] }) {
  if (impacts.length === 0) return <span className="text-ink-400 text-table">None</span>;
  return (
    <span className="inline-flex flex-wrap gap-1">
      {impacts.map((imp) => (
        <span
          key={imp}
          className="rounded-sm bg-mute-bg px-1.5 py-0.5 text-xs text-mute-fg font-medium"
        >
          {titleCaseSnake(imp)}
        </span>
      ))}
    </span>
  );
}
