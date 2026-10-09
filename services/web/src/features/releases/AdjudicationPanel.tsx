import { useState } from "react";
import type { SemanticChange } from "@/api/types";

type AdjudicationPanelProps = {
  changes: SemanticChange[];
};

export function AdjudicationPanel({ changes }: AdjudicationPanelProps) {
  const [decisions, setDecisions] = useState<Record<string, "material" | "immaterial">>({});

  if (changes.length === 0) {
    return null;
  }

  return (
    <section className="rounded-sm bg-bg-panel shadow-hairline p-4">
      <h2 className="text-sm font-semibold text-ink-900">Adjudication</h2>
      <p className="mt-1 text-table text-ink-600">
        Changes marked needs review require an explicit materiality decision before rollout proceeds.
      </p>
      <ul className="mt-3 space-y-3">
        {changes.map((change) => {
          const key = `${change.path}:${change.subject}`;
          const decision = decisions[key];
          return (
            <li key={key} className="border-t border-line-200 pt-3 first:border-t-0 first:pt-0">
              <p className="text-table text-ink-900">{change.summary}</p>
              <div className="mt-2 flex flex-wrap gap-2">
                <label className="flex items-center gap-1.5 text-table">
                  <input
                    type="radio"
                    name={`adj-${key}`}
                    checked={decision === "material"}
                    onChange={() => setDecisions((d) => ({ ...d, [key]: "material" }))}
                  />
                  Material
                </label>
                <label className="flex items-center gap-1.5 text-table">
                  <input
                    type="radio"
                    name={`adj-${key}`}
                    checked={decision === "immaterial"}
                    onChange={() => setDecisions((d) => ({ ...d, [key]: "immaterial" }))}
                  />
                  Immaterial
                </label>
              </div>
            </li>
          );
        })}
      </ul>
      <button
        type="button"
        className="mt-4 w-full rounded-sm border border-line-300 bg-bg-sunk px-3 py-2 text-sm font-medium text-ink-900 hover:bg-bg-base disabled:opacity-40"
        disabled={changes.some((c) => !decisions[`${c.path}:${c.subject}`])}
        aria-label="Record adjudication decisions"
      >
        Record decisions
      </button>
      <p className="mt-2 text-xs text-ink-400">Mock console — decisions are not persisted.</p>
    </section>
  );
}
