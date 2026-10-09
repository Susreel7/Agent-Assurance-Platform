import { Link } from "react-router-dom";
import type { ReleaseAssessment, SemanticChange } from "@/api/types";
import { AccreditationStateBadge } from "@/components/StateBadge";
import { Skeleton } from "@/components/Skeleton";
import { ErrorState } from "@/components/ErrorState";
import { formatTableDate } from "@/lib/dates";
import { AdjudicationPanel } from "./AdjudicationPanel";

type ReleaseImpactRailProps = {
  assessment: ReleaseAssessment | undefined;
  isLoading: boolean;
  error: string | null;
  onRetry: () => void;
  reviewChanges: SemanticChange[];
};

/** What an approver reads before deciding, in the order they need it.
 *
 * The verdict first, because it determines whether anything else matters. Then which
 * accreditations are at stake and who owns them, because that is the consequence. The
 * per-change detail lives in the main column; this rail answers "can I approve this".
 */
const IMPACT_COPY: Record<
  ReleaseAssessment["accreditation_impact"],
  { label: string; detail: string; tone: string }
> = {
  none: {
    label: "No accreditation affected",
    detail: "Nothing in this release touches a control that an accreditation depends on.",
    tone: "bg-ok-bg text-ok-fg",
  },
  requires_revalidation: {
    label: "Revalidation required",
    detail:
      "Approving this release puts the accreditations below back into assessment. They stay valid, but the evidence has to be regathered.",
    tone: "bg-warn-bg text-warn-fg",
  },
  suspends: {
    label: "Suspends accreditation",
    detail:
      "Approving this release suspends the accreditations below. Any client relying on them loses the assurance until it is reissued.",
    tone: "bg-risk-bg text-risk-fg",
  },
};

export function ReleaseImpactRail({
  assessment,
  isLoading,
  error,
  onRetry,
  reviewChanges,
}: ReleaseImpactRailProps) {
  const affected = assessment?.affected_accreditations ?? [];

  return (
    <aside className="space-y-4 lg:w-80 shrink-0">
      <section className="rounded-sm bg-bg-panel shadow-hairline p-4">
        <h2 className="text-sm font-semibold text-ink-900">What this means for approvals</h2>

        {isLoading ? (
          <div className="mt-3 space-y-2">
            <Skeleton height="0.875rem" />
            <Skeleton height="0.875rem" />
            <Skeleton height="2rem" />
          </div>
        ) : error ? (
          <div className="mt-3">
            <ErrorState message={error} onRetry={onRetry} />
          </div>
        ) : assessment ? (
          <div className="mt-3 space-y-4 text-table">
            {/* The API types the state as a plain string, so it is narrowed here rather
                than asserted at the badge, which only renders known states. */}
            <div>
              <span
                className={`inline-block rounded-sm px-2 py-1 text-xs font-medium ${
                  IMPACT_COPY[assessment.accreditation_impact].tone
                }`}
              >
                {IMPACT_COPY[assessment.accreditation_impact].label}
              </span>
              <p className="mt-2 text-ink-600">
                {IMPACT_COPY[assessment.accreditation_impact].detail}
              </p>
            </div>

            <dl className="grid grid-cols-3 gap-2 border-y border-line-200 py-3">
              <div>
                <dt className="text-xs text-ink-400">Material</dt>
                <dd className="tabular-nums text-ink-900">{assessment.material_count}</dd>
              </div>
              <div>
                <dt className="text-xs text-ink-400">Review</dt>
                <dd className="tabular-nums text-ink-900">{assessment.review_count}</dd>
              </div>
              <div>
                <dt className="text-xs text-ink-400">Routine</dt>
                <dd className="tabular-nums text-ink-900">{assessment.immaterial_count}</dd>
              </div>
            </dl>

            <div>
              <p className="text-xs font-medium text-ink-600 uppercase tracking-wide">
                Accreditations at stake
              </p>
              {affected.length === 0 ? (
                <p className="mt-1 text-ink-400">None affected</p>
              ) : (
                <ul className="mt-2 space-y-3">
                  {affected.map((acc) => (
                    <li key={acc.accreditation_id}>
                      <Link
                        to={`/accreditations/${acc.accreditation_id}`}
                        className="text-info-fg hover:underline font-mono-data text-xs"
                      >
                        {acc.reference}
                      </Link>
                      <div className="mt-1 flex flex-wrap items-center gap-2">
                        <AccreditationStateBadge state={acc.state} />
                        <span className="text-xs text-ink-400">{acc.framework_name}</span>
                      </div>
                      {acc.customer_name ? (
                        <p className="mt-1 text-xs text-ink-600">
                          {acc.customer_name}
                          {acc.engagement_name ? ` · ${acc.engagement_name}` : ""}
                        </p>
                      ) : null}
                      {acc.expires_at ? (
                        <p className="text-xs text-ink-400">
                          Expires {formatTableDate(acc.expires_at)}
                        </p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {assessment.rules_fired.length > 0 ? (
              <div>
                <p className="text-xs font-medium text-ink-600 uppercase tracking-wide">
                  Rules that decided this
                </p>
                <ul className="mt-2 space-y-1 font-mono-data text-xs text-ink-600">
                  {assessment.rules_fired.map((rule) => (
                    <li key={rule}>{rule}</li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}
      </section>
      <AdjudicationPanel changes={reviewChanges} />
    </aside>
  );
}
