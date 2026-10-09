import clsx from "clsx";
import type { AccreditationImpact, SemanticChange } from "@/api/types";
import {
  accreditationImpactLabel,
  accreditationImpactTone,
} from "@/lib/materiality";

const toneClass = {
  ok: "bg-ok-bg border-ok-fg/30 text-ok-fg",
  warn: "bg-warn-bg border-warn-fg/30 text-warn-fg",
  risk: "bg-risk-bg border-risk-fg/30 text-risk-fg",
} as const;

type ReleaseConsequenceBannerProps = {
  impact: AccreditationImpact;
  changes: SemanticChange[];
};

function primaryRule(changes: SemanticChange[]): string | null {
  for (const change of changes) {
    const first = change.rules_fired[0];
    if (first) return first;
  }
  return null;
}

export function ReleaseConsequenceBanner({ impact, changes }: ReleaseConsequenceBannerProps) {
  const tone = accreditationImpactTone(impact);
  const rule = primaryRule(changes);
  const headline = accreditationImpactLabel(impact);

  return (
    <div
      className={clsx("rounded-sm border px-4 py-3", toneClass[tone])}
      role="status"
      aria-live="polite"
    >
      <p className="text-sm font-semibold">{headline}</p>
      {rule ? (
        <p className="mt-1 text-sm text-ink-900">
          Governing rule: <code className="font-mono-data">{rule}</code>
        </p>
      ) : impact !== "none" ? (
        <p className="mt-1 text-sm text-ink-600">Review materiality verdicts below for detail.</p>
      ) : (
        <p className="mt-1 text-sm text-ink-600">No accreditation state transition required.</p>
      )}
    </div>
  );
}
