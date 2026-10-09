import type { SemanticChange } from "@/api/types";
import { SeverityBadge, MaterialityBadge } from "@/components/StateBadge";
import { changeCategoryLabel } from "./changeCategories";
import { ImpactBadges, ValueDiff } from "./ValueDiff";

type ChangeRowProps = {
  change: SemanticChange;
  highlighted?: boolean;
};

export function ChangeRow({ change, highlighted = false }: ChangeRowProps) {
  return (
    <article
      className={`border-b border-line-200 py-3 last:border-b-0 ${highlighted ? "bg-accent-soft ring-1 ring-inset ring-accent/30" : ""}`}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-xs text-ink-400">{changeCategoryLabel(change.category)}</p>
          <p className="mt-0.5 text-sm text-ink-900">{change.summary}</p>
          {change.detail ? <p className="mt-1 text-table text-ink-600">{change.detail}</p> : null}
        </div>
        <div className="flex flex-wrap items-center gap-2 shrink-0">
          <SeverityBadge severity={change.severity} />
          <MaterialityBadge verdict={change.verdict} />
        </div>
      </div>
      <div className="mt-2 rounded-sm bg-bg-sunk px-3 py-2">
        <ValueDiff before={change.before_value} after={change.after_value} operation={change.operation} />
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-table">
        <span className="text-ink-400">
          Impacts: <ImpactBadges impacts={change.impacts} />
        </span>
        {change.rules_fired.length > 0 ? (
          <span className="inline-flex flex-wrap items-center gap-1">
            <span className="text-ink-400">Rules:</span>
            {change.rules_fired.map((rule) => (
              <code
                key={rule}
                className="rounded-sm bg-bg-panel px-1.5 py-0.5 font-mono-data text-xs text-ink-900 border border-line-200"
              >
                {rule}
              </code>
            ))}
          </span>
        ) : null}
      </div>
    </article>
  );
}
