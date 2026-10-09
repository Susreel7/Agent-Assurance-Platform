import type { ControlGap, ReadinessByFramework, RequirementLevel } from "@/api/types";
import { ErrorState } from "@/components/ErrorState";
import { Panel } from "@/components/Panel";
import { Skeleton } from "@/components/Skeleton";
import { StackedBar } from "@/components/StackedBar";
import { formatPercent, titleCaseSnake } from "@/lib/formatters";

function levelLabel(level: RequirementLevel): string {
  return titleCaseSnake(level);
}

type ReadinessPanelProps = {
  headline: string | undefined;
  coveragePct: number | undefined;
  frameworks: ReadinessByFramework[] | undefined;
  gaps: ControlGap[] | undefined;
  isLoading: boolean;
  isError: boolean;
  errorMessage: string | null;
  onRetry: () => void;
};

export function ReadinessPanel({
  headline,
  coveragePct,
  frameworks,
  gaps,
  isLoading,
  isError,
  errorMessage,
  onRetry,
}: ReadinessPanelProps) {
  if (isLoading) {
    return (
      <Panel title="Readiness">
        <Skeleton height="1rem" width="40%" />
        <div className="mt-3 space-y-2">
          <Skeleton height="4rem" />
          <Skeleton height="12rem" />
        </div>
      </Panel>
    );
  }

  if (isError) {
    return (
      <Panel title="Readiness">
        <ErrorState message={errorMessage ?? "Readiness unavailable"} onRetry={onRetry} />
      </Panel>
    );
  }

  const fw = frameworks ?? [];
  const gapList = gaps ?? [];

  if (fw.length === 0) {
    return (
      <Panel title="Readiness">
        <p className="text-table text-ink-600">No required frameworks configured for this customer.</p>
      </Panel>
    );
  }

  return (
    <Panel title="Readiness">
      <div className="space-y-4">
        <div>
          <p className="text-sm font-medium text-ink-900">{headline}</p>
          {coveragePct !== undefined ? (
            <p className="text-table text-ink-600 tabular-nums">
              Overall coverage {formatPercent(coveragePct)}
            </p>
          ) : null}
        </div>

        <div className="space-y-4">
          {fw.map((row) => {
            const unanswerable =
              row.partial + row.narrative_only + row.unmapped;
            const segments = [
              { label: "Evidence answerable", value: row.answerable, color: "var(--ok-fg)" },
              { label: "Partial", value: row.partial, color: "var(--warn-fg)" },
              { label: "Narrative only", value: row.narrative_only, color: "var(--info-fg)" },
              { label: "Unmapped", value: row.unmapped, color: "var(--risk-fg)" },
            ].filter((s) => s.value > 0);

            const frameworkGaps = gapList.filter((g) => g.framework_slug === row.framework.slug);

            return (
              <div key={row.framework.id} className="border-t border-line-200 pt-4 first:border-0 first:pt-0">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <h3 className="text-sm font-semibold text-ink-900">{row.framework.name}</h3>
                  <span className="text-xs text-ink-400">
                    Requirement level: {levelLabel(row.level)}
                  </span>
                </div>
                <p className="mt-1 text-table text-ink-600 tabular-nums">
                  {row.answerable} of {row.controls_in_scope} controls can be evidenced (
                  {formatPercent(row.coverage_pct)})
                </p>
                <div className="mt-2">
                  <StackedBar
                    segments={
                      segments.length
                        ? segments
                        : [{ label: "None", value: 1, color: "var(--line-200)" }]
                    }
                    ariaLabel={`Coverage for ${row.framework.name}`}
                  />
                </div>
                {unanswerable > 0 && frameworkGaps.length > 0 ? (
                  <div className="mt-3">
                    <h4 className="text-xs font-semibold text-ink-900">Gaps ({frameworkGaps.length})</h4>
                    <ul className="mt-2 space-y-2">
                      {frameworkGaps.map((g) => (
                        <li key={`${g.control_ref}-${g.title}`} className="text-table text-ink-600">
                          <span className="font-mono-data text-ink-900">{g.control_ref}</span>{" "}
                          {g.title} — {g.reason}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}
              </div>
            );
          })}
        </div>
      </div>
    </Panel>
  );
}
