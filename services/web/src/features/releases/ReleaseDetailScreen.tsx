import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import type { ChangeCategory, SemanticChange } from "@/api/types";
import { useAgentVersions, useRelease, useReleaseAssessment } from "@/api/queries";
import { Panel } from "@/components/Panel";
import { Tabs } from "@/components/Tabs";
import { ReleaseStateBadge } from "@/components/StateBadge";
import { Urn } from "@/components/Urn";
import { Principal } from "@/components/Principal";
import { RelativeTime } from "@/components/RelativeTime";
import { ErrorState } from "@/components/ErrorState";
import { Skeleton } from "@/components/Skeleton";
import { formatSemverRange } from "@/lib/formatters";
import { CHANGE_CATEGORY_ORDER, changeCategoryLabel } from "./changeCategories";
import { ChangeRow } from "./ChangeRow";
import { ReleaseConsequenceBanner } from "./ReleaseConsequenceBanner";
import { ReleaseImpactRail } from "./ReleaseImpactRail";
import { RawDescriptorDiff } from "./RawDescriptorDiff";
import { ReviewBriefPanel } from "./ReviewBriefPanel";
import { ImpactBadges } from "./ValueDiff";

function groupByCategory(changes: SemanticChange[]): Map<ChangeCategory, SemanticChange[]> {
  const map = new Map<ChangeCategory, SemanticChange[]>();
  for (const change of changes) {
    const list = map.get(change.category) ?? [];
    list.push(change);
    map.set(change.category, list);
  }
  return map;
}

export default function ReleaseDetailScreen() {
  const { releaseId = "" } = useParams();
  const releaseQuery = useRelease(releaseId);
  const impactQuery = useReleaseAssessment(releaseId);
  const release = releaseQuery.data;

  const versionsQuery = useAgentVersions(release?.agent_id ?? "", { limit: "50", offset: "0" });
  const [tab, setTab] = useState("changes");
  const [highlightPath, setHighlightPath] = useState<string | null>(null);

  const grouped = useMemo(
    () =>
      release ? groupByCategory(release.changes) : new Map<ChangeCategory, SemanticChange[]>(),
    [release],
  );

  const reviewChanges = useMemo(
    () => release?.changes.filter((c) => c.verdict === "needs_review") ?? [],
    [release],
  );

  const fromVersion = useMemo(() => {
    const items = versionsQuery.data?.items ?? [];
    return items.find((v) => v.semver === release?.from_semver) ?? null;
  }, [versionsQuery.data, release?.from_semver]);

  const toVersion = useMemo(() => {
    const items = versionsQuery.data?.items ?? [];
    return items.find((v) => v.semver === release?.to_semver) ?? null;
  }, [versionsQuery.data, release?.to_semver]);

  if (releaseQuery.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton height="2rem" width="60%" />
        <Skeleton height="4rem" />
        <Skeleton height="20rem" />
      </div>
    );
  }

  if (releaseQuery.isError || !release) {
    return (
      <ErrorState
        message={releaseQuery.error instanceof Error ? releaseQuery.error.message : "Release not found"}
        onRetry={() => void releaseQuery.refetch()}
      />
    );
  }

  return (
    <div className="space-y-4">
      <header className="space-y-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <p className="text-xs text-ink-400">{release.release_tag}</p>
            <h1 className="text-lg font-semibold text-ink-900">{release.title ?? "Release"}</h1>
            <p className="mt-1">
              <Link to={`/agents/${release.agent_id}`} className="hover:underline">
                <Urn value={release.agent_urn} />
              </Link>
            </p>
            <p className="mt-2 font-mono-data text-sm tabular-nums">
              {formatSemverRange(release.from_semver, release.to_semver)}
            </p>
          </div>
          <div className="flex flex-col items-end gap-2">
            <ReleaseStateBadge state={release.state} />
            {release.proposed_by ? (
              <p className="text-table text-ink-600">
                Proposed by <Principal principalId={release.proposed_by} />
              </p>
            ) : null}
            <RelativeTime iso={release.created_at} mode="table" />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-table">
          <span className="text-ink-400">Impacts:</span>
          <ImpactBadges impacts={release.impacts} />
        </div>
        <ReleaseConsequenceBanner impact={release.accreditation_impact} changes={release.changes} />
        {release.notes ? <p className="text-table text-ink-600">{release.notes}</p> : null}
      </header>

      {release.review_brief ? (
        <ReviewBriefPanel
          brief={release.review_brief}
          onSelectChange={(path) => {
            setHighlightPath(path);
            setTab("changes");
          }}
        />
      ) : null}

      <Tabs
        ariaLabel="Release views"
        activeId={tab}
        onChange={setTab}
        tabs={[
          { id: "changes", label: "Structured changes" },
          { id: "raw", label: "Raw descriptor diff" },
        ]}
      />

      <div className="flex flex-col lg:flex-row gap-4 items-start">
        <div className="flex-1 min-w-0 w-full">
          {tab === "changes" ? (
            <Panel title="Changes by category" noPadding>
              <div className="px-4 py-2">
                {CHANGE_CATEGORY_ORDER.map((category) => {
                  const rows = grouped.get(category);
                  if (!rows || rows.length === 0) return null;
                  return (
                    <section key={category} className="mb-6 last:mb-0">
                      <h3 className="sticky top-0 bg-bg-panel py-2 text-xs font-semibold uppercase tracking-wide text-ink-600 border-b border-line-200">
                        {changeCategoryLabel(category)}
                        <span className="ml-2 font-normal text-ink-400">({rows.length})</span>
                      </h3>
                      <div className="px-1">
                        {rows.map((change) => (
                          <ChangeRow
                            key={`${change.path}-${change.subject}-${change.operation}`}
                            change={change}
                            highlighted={highlightPath !== null && change.path === highlightPath}
                          />
                        ))}
                      </div>
                    </section>
                  );
                })}
                {release.changes.length === 0 ? (
                  <p className="py-8 text-center text-table text-ink-400">No governed changes recorded.</p>
                ) : null}
              </div>
            </Panel>
          ) : (
            <Panel title="Raw descriptor diff">
              <p className="mb-3 text-table text-ink-600">
                Side-by-side JSON is what a source-control diff shows. It hides accreditation consequence.
              </p>
              <RawDescriptorDiff
                fromVersion={fromVersion}
                toVersion={toVersion}
                fromSemver={release.from_semver}
                toSemver={release.to_semver}
                isLoading={versionsQuery.isLoading}
              />
            </Panel>
          )}
        </div>

        <ReleaseImpactRail
          assessment={impactQuery.data}
          isLoading={impactQuery.isLoading}
          error={
            impactQuery.isError
              ? impactQuery.error instanceof Error
                ? impactQuery.error.message
                : "Failed to load impact"
              : null
          }
          onRetry={() => void impactQuery.refetch()}
          reviewChanges={reviewChanges}
        />
      </div>
    </div>
  );
}
