import { Link, useParams } from "react-router-dom";
import { useTrustPortal } from "@/api/queries";
import type { Severity } from "@/api/types";
import { Digest } from "@/components/Digest";
import { ErrorState } from "@/components/ErrorState";
import { AccreditationStateBadge, SeverityBadge } from "@/components/StateBadge";
import { Skeleton } from "@/components/Skeleton";
import { Urn } from "@/components/Urn";
import { formatPercent } from "@/lib/formatters";

const SEVERITY_ORDER: Severity[] = ["critical", "high", "medium", "low", "info"];

export default function TrustPortalScreen() {
  const { customerSlug = "", engagementSlug = "" } = useParams();
  const query = useTrustPortal(customerSlug, engagementSlug);

  if (query.isLoading) {
    return (
      <div className="min-h-screen bg-bg-base">
        <header className="border-b border-line-200 bg-bg-panel px-6 py-4">
          <Skeleton height="1.5rem" width="12rem" />
        </header>
        <main className="mx-auto max-w-[1440px] px-6 py-6 space-y-4">
          <Skeleton height="4rem" />
          <Skeleton height="10rem" />
        </main>
      </div>
    );
  }

  if (query.isError || !query.data) {
    return (
      <div className="min-h-screen bg-bg-base px-6 py-12">
        <ErrorState
          message={query.error instanceof Error ? query.error.message : "Portal unavailable"}
          onRetry={() => void query.refetch()}
        />
      </div>
    );
  }

  const view = query.data;
  const chain = view.chain_verification;

  // The verification result reports per-batch roots rather than one summary root, so the
  // current head is the highest sequence it checked. Publishing the *last* array element
  // would assume an ordering the API does not promise.
  const latestRoot =
    (chain.batch_results ?? []).reduce<{ seq: number; stored_root: string } | null>(
      (head, b) => (head === null || b.seq > head.seq ? b : head),
      null,
    )?.stored_root ?? "";

  return (
    <div className="min-h-screen bg-bg-base">
      <header className="border-b border-line-200 bg-bg-panel">
        <div className="mx-auto flex max-w-[1440px] flex-wrap items-center justify-between gap-4 px-6 py-4">
          <div>
            <p className="text-xs uppercase tracking-wide text-ink-400">Trust portal</p>
            <h1 className="text-xl font-semibold text-ink-900">{view.customer_display_name}</h1>
            <p className="text-table text-ink-600">{view.engagement_name}</p>
          </div>
          <p className="rounded-sm border border-info-fg/30 bg-info-bg px-3 py-2 text-table text-info-fg">
            {view.scoped_statement}
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-[1440px] space-y-6 px-6 py-6">
        <p className="text-table text-ink-600">
          This view shows only accredited agents and assurance facts for this engagement. No other
          customer names or records appear here.
        </p>

        <section className="bg-bg-panel shadow-hairline rounded-sm">
          <h2 className="border-b border-line-200 px-4 py-3 text-sm font-semibold text-ink-900">
            Accredited agents
          </h2>
          <div className="overflow-auto">
            <table>
              <thead>
                <tr>
                  <th scope="col" className="px-3 py-2 text-left">
                    Agent
                  </th>
                  <th scope="col" className="px-3 py-2 text-left">
                    URN
                  </th>
                  <th scope="col" className="px-3 py-2 text-left">
                    Accreditation
                  </th>
                  <th scope="col" className="px-3 py-2 text-left">
                    Pack
                  </th>
                </tr>
              </thead>
              <tbody>
                {view.agents.length === 0 ? (
                  <tr>
                    <td colSpan={4} className="px-3 py-4 text-table text-ink-400">
                      No accredited agents in this engagement.
                    </td>
                  </tr>
                ) : (
                  view.agents.map((a) => (
                    <tr key={a.agent_urn} className="border-t border-line-200">
                      <td className="px-3 py-2 text-table">{a.display_name}</td>
                      <td className="px-3 py-2">
                        <Urn value={a.agent_urn} />
                      </td>
                      <td className="px-3 py-2">
                        <AccreditationStateBadge state={a.accreditation_state} />
                      </td>
                      <td className="px-3 py-2 text-table">
                        {a.pack_download_uri ? (
                          <a href={a.pack_download_uri} className="text-info-fg hover:underline">
                            Download pack
                          </a>
                        ) : (
                          "—"
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </section>

        <div className="grid gap-4 md:grid-cols-2">
          <section className="bg-bg-panel shadow-hairline rounded-sm p-4">
            <h2 className="text-sm font-semibold text-ink-900">SLO attainment</h2>
            <p className="mt-2 text-2xl font-semibold tabular-nums text-ink-900">
              {formatPercent(view.slo_attainment_pct)}
            </p>
          </section>

          <section className="bg-bg-panel shadow-hairline rounded-sm p-4">
            <h2 className="text-sm font-semibold text-ink-900">Open findings by severity</h2>
            <ul className="mt-3 flex flex-wrap gap-3">
              {SEVERITY_ORDER.map((sev) => (
                <li key={sev} className="flex items-center gap-2 text-table">
                  <SeverityBadge severity={sev} />
                  <span className="tabular-nums">{view.findings_by_severity[sev]}</span>
                </li>
              ))}
            </ul>
            <p className="mt-2 text-xs text-ink-400">Counts only — no internal remediation detail.</p>
          </section>
        </div>

        <section className="bg-bg-panel shadow-hairline rounded-sm p-4">
          <h2 className="text-sm font-semibold text-ink-900">Residency proof</h2>
          <p className="mt-2 text-table text-ink-600">{view.residency_summary}</p>
        </section>

        <section className="bg-bg-panel shadow-hairline rounded-sm p-4">
          <h2 className="text-sm font-semibold text-ink-900">Evidence chain</h2>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-table">
            <span
              className={
                chain.is_valid
                  ? "rounded-sm bg-ok-bg px-2 py-1 text-ok-fg"
                  : "rounded-sm bg-risk-bg px-2 py-1 text-risk-fg"
              }
            >
              {chain.is_valid ? "Verified" : "Broken"}
            </span>
            <span className="text-ink-600">
              {chain.is_valid
                ? "Every sealed batch hashes to the root below."
                : chain.failure_reason}
            </span>
          </div>
          <p className="mt-2 text-table text-ink-600 tabular-nums">
            {chain.batches_checked} batches · {chain.tree_size} events
          </p>
          <div className="mt-2">
            <Digest value={latestRoot} max={48} />
          </div>
        </section>

        <p className="text-xs text-ink-400">
          Assurance console access for your organisation is separate.{" "}
          <Link to="/" className="text-info-fg hover:underline">
            Operator sign-in
          </Link>
        </p>
      </main>
    </div>
  );
}
