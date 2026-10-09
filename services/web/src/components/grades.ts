/**
 * The grading vocabulary from `design/12-strategic-thesis.md` §5, without the JSX.
 *
 * Split from `EnforcementGrade.tsx` because Fast Refresh can only replace a module that
 * exports components and nothing else; a file mixing the two silently falls back to a
 * full reload. The split is useful anyway — `toGrade` belongs wherever an API row is
 * normalised, including places that render no chip at all.
 *
 * Named `grades.ts` rather than `enforcementGrade.ts` because a name differing from the
 * component's only in case resolves to one file on Windows and macOS and two on Linux,
 * which is a build that passes locally and fails in CI.
 *
 * The letters are a claim about what we could have done, not how alarming something is.
 * A is not "good" and E is not "bad": E is a session we cannot see, which may be entirely
 * benign, and the number exists so the gap is counted rather than assumed empty.
 */

export const GRADES = ["A", "B", "C", "D", "E", "unknown"] as const;

export type Grade = (typeof GRADES)[number];

export type GradeFacts = {
  /** The one-word name from §5. */
  name: string;
  /** What we can actually claim. Shown on hover, because the letter alone is jargon. */
  claim: string;
  tone: string;
};

export const GRADE_FACTS: Record<Grade, GradeFacts> = {
  A: {
    name: "Mediated",
    claim: "We hold the URL and the credential. The action could not occur without passing us.",
    tone: "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
  },
  B: {
    name: "Interposed",
    claim:
      "We run inside the agent's decision loop and can veto before execution — on hardware the user administers.",
    tone: "border-teal-500/30 bg-teal-500/10 text-teal-700 dark:text-teal-300",
  },
  C: {
    name: "Attested",
    claim: "The vendor's own control enforces this. We set it through their admin API and verify it is still set.",
    tone: "border-blue-500/30 bg-blue-500/10 text-blue-700 dark:text-blue-400",
  },
  D: {
    name: "Observed",
    claim: "We learned about this after it happened, from the vendor. Nothing could have been stopped.",
    tone: "border-amber-500/30 bg-amber-500/10 text-amber-700 dark:text-amber-400",
  },
  E: {
    name: "Dark",
    claim: "We cannot see this at all. It is counted here so the gap has a number.",
    tone: "border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-400",
  },
  // Visually E, labelled honestly. A row whose grade the collector did not send has not
  // earned a better one, and rounding it up is exactly the overstatement this exists to
  // prevent — but calling it "Dark" would claim we know it was uncovered, and we do not.
  unknown: {
    name: "Ungraded",
    claim: "This row arrived without a grade, so it counts as E until the collector sends one.",
    tone: "border-rose-500/30 bg-rose-500/10 text-rose-700 dark:text-rose-400",
  },
};

/** Narrows anything the API might send, including nothing at all. */
export function toGrade(value: string | null | undefined): Grade {
  return (GRADES as readonly string[]).includes(value ?? "") ? (value as Grade) : "unknown";
}
