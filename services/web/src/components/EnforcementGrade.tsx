/**
 * The grade that has to travel with every number on a ledger screen.
 *
 * `design/12-strategic-thesis.md` §5 makes this a first-class field rather than a
 * footnote, and the reason is commercial rather than pedantic. Every competitor renders
 * one undifferentiated "protected" state, and a security team that has been burned once
 * knows that is false. "1,204 mediated · 8,911 veto-capable · 41,002 observed afterwards
 * · 312 sessions we cannot see" is a claim that survives an audit.
 *
 * So a count on a ledger screen without one of these next to it is a defect, not a
 * styling omission — it is the console asserting a coverage it has not measured.
 * `services/web/scripts/check-runtime-contract.mjs` holds `inv_grade_chip`.
 *
 * `unknown` renders as E and says "ungraded". Absence of evidence is Grade E; it is
 * never a blank, because a blank reads as "fine". The vocabulary itself lives in
 * `./grades`.
 */

import { clsx } from "clsx";
import { GRADE_FACTS, type Grade } from "./grades";

export function EnforcementGrade({
  grade,
  showName = false,
  className,
}: {
  grade: Grade;
  /** Adds the word next to the letter. Worth it in a legend, noise in a dense table. */
  showName?: boolean;
  className?: string;
}) {
  const facts = GRADE_FACTS[grade];
  const letter = grade === "unknown" ? "E" : grade;

  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        facts.tone,
        className,
      )}
      title={`Grade ${letter} · ${facts.name}. ${facts.claim}`}
    >
      <span className="font-mono">{letter}</span>
      {showName ? <span className="font-medium normal-case tracking-normal">{facts.name}</span> : null}
    </span>
  );
}

/**
 * A number and the grade it was measured at, together.
 *
 * Exists so that "render the count with its grade" is one import rather than a
 * convention two screens follow and the third forgets.
 */
export function GradedCount({
  value,
  grade,
  label,
}: {
  /** `null` means not measured yet, and renders as an em dash rather than a zero. */
  value: number | null;
  grade: Grade;
  label: string;
}) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="flex items-center gap-2 text-xs text-slate-600 dark:text-slate-400">
        <EnforcementGrade grade={grade} />
        {label}
      </span>
      <span className="font-mono text-sm tabular-nums text-slate-900 dark:text-white">
        {value === null ? "—" : value.toLocaleString()}
      </span>
    </div>
  );
}
