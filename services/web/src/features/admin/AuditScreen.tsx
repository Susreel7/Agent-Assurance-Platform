/**
 * The security audit trail.
 *
 * Paginated by cursor with no page numbers and no total, and the reason is visible in the
 * shape of the table it reads: `security_audit_events` is partitioned and append-only, so
 * `OFFSET 40000` makes Postgres produce and discard forty thousand rows, and by the time
 * page 800 painted the rows would have shifted underneath it. A cursor is an index seek at
 * any depth. "Load more" is the honest control for that.
 *
 * There is deliberately no free-text search. Every filter offered here narrows an index the
 * listing already uses; an unindexed `ILIKE` across billions of rows is a way to take the
 * control plane down from the audit page.
 *
 * `detail` holds classifications, digests and decisions — never a prompt, a tool argument
 * or a credential. That is enforced at the API boundary, which is what makes it safe to
 * render every key here without filtering.
 */

import { useState } from "react";
import AlertTriangle from "lucide-react/dist/esm/icons/triangle-alert";
import CheckCircle2 from "lucide-react/dist/esm/icons/circle-check-big";
import ShieldAlert from "lucide-react/dist/esm/icons/shield-alert";
import { useAuditDigest, useAuditEvents } from "@/api/platformQueries";
import { ErrorState } from "@/components/ErrorState";
import { AuditSeverityBadge } from "@/components/PlatformBadge";
import { RelativeTime } from "@/components/RelativeTime";
import { Skeleton } from "@/components/Skeleton";
import { NexusBadge, NexusCard, NexusMetric, NexusPageHeader } from "@/components/NexusUI";
import { formatCompact, titleCaseSnake } from "@/lib/formatters";
import type { AuditCategory, AuditOutcome, AuditSeverity } from "@/api/platformTypes";

const CATEGORIES: { value: AuditCategory | ""; label: string }[] = [
  { value: "", label: "Everything" },
  { value: "identity", label: "Identity" },
  { value: "access", label: "Access" },
  { value: "credential", label: "Credentials" },
  { value: "mcp", label: "Tools" },
  { value: "routing", label: "Routing" },
  { value: "data", label: "Data" },
  { value: "admin", label: "Admin" },
];

const OUTCOMES: { value: AuditOutcome | ""; label: string }[] = [
  { value: "", label: "Any outcome" },
  { value: "denied", label: "Denied" },
  { value: "allowed", label: "Allowed" },
  { value: "created", label: "Created" },
  { value: "updated", label: "Updated" },
  { value: "revoked", label: "Revoked" },
  { value: "failed", label: "Failed" },
  { value: "expired", label: "Expired" },
];

const SEVERITIES: { value: AuditSeverity | ""; label: string }[] = [
  { value: "", label: "Any severity" },
  { value: "critical", label: "Critical" },
  { value: "warning", label: "Warning" },
  { value: "notice", label: "Notice" },
  { value: "info", label: "Info" },
];

const SELECT =
  "rounded-xl border border-slate-200 bg-white/80 px-3 py-2 text-xs text-slate-800 outline-none transition focus:border-indigo-400 dark:border-white/10 dark:bg-black/30 dark:text-slate-200 dark:focus:border-cyan-500/50";

function OutcomeBadge({ outcome }: { outcome: AuditOutcome }) {
  const tone =
    outcome === "denied" || outcome === "failed"
      ? "risk"
      : outcome === "revoked" || outcome === "expired"
        ? "warn"
        : outcome === "allowed"
          ? "ok"
          : "info";
  return (
    <NexusBadge
      tone={tone === "risk" ? "risk" : tone === "warn" ? "warn" : tone === "ok" ? "ok" : "info"}
    >
      {titleCaseSnake(outcome)}
    </NexusBadge>
  );
}

export default function AuditScreen() {
  const [category, setCategory] = useState<AuditCategory | "">("");
  const [outcome, setOutcome] = useState<AuditOutcome | "">("");
  const [severity, setSeverity] = useState<AuditSeverity | "">("");

  const digest = useAuditDigest(7);
  const events = useAuditEvents({
    category: category || undefined,
    outcome: outcome || undefined,
    severity: severity || undefined,
    page_size: 50,
  });

  if (events.isPending) {
    return (
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} height="104px" />
          ))}
        </div>
        <Skeleton height="420px" />
      </div>
    );
  }

  if (events.isError) {
    return (
      <ErrorState
        title="Could not load the audit trail"
        message={events.error instanceof Error ? events.error.message : "Unknown error"}
        onRetry={() => void events.refetch()}
      />
    );
  }

  const rows = (events.data?.pages ?? []).flatMap((page) => page.items);
  const windowTotal = (digest.data?.counts ?? []).reduce((sum, row) => sum + row.event_count, 0);
  const dataEvents = (digest.data?.counts ?? [])
    .filter((row) => row.category === "data")
    .reduce((sum, row) => sum + row.event_count, 0);

  return (
    <div className="space-y-6">
      <NexusPageHeader
        crumbs={["Admin", "Security & audit"]}
        title="Security & audit"
        lede="A live, append-only record of identity, tool, model-routing, credential, and data-protection decisions. Prompts, tool arguments, results, and detected secret values are never copied into this trail."
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <NexusMetric
          label="Events, 7 days"
          value={formatCompact(windowTotal)}
          meta="Control-plane evidence"
        />
        <NexusMetric
          label="Denials"
          value={formatCompact(digest.data?.denied_count ?? 0)}
          meta="Requests stopped by policy"
          tone={(digest.data?.denied_count ?? 0) > 0 ? "negative" : "positive"}
        />
        <NexusMetric
          label="Critical"
          value={formatCompact(digest.data?.critical_count ?? 0)}
          meta="Requires operator review"
          tone={(digest.data?.critical_count ?? 0) > 0 ? "negative" : "positive"}
        />
        <NexusMetric
          label="Data controls"
          value={formatCompact(dataEvents)}
          meta="Secret and classification decisions"
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        {[
          {
            icon: ShieldAlert,
            title: "Inline prevention",
            detail: "Secrets are scanned before provider dispatch. Block mode fails closed; audit mode records without copying the matched value.",
          },
          {
            icon: AlertTriangle,
            title: "Attributable decisions",
            detail: "Personal Platform Keys bind every model and MCP decision to a verified member, then retain project, agent, policy, and trace identifiers.",
          },
          {
            icon: CheckCircle2,
            title: "Regional enforcement",
            detail: "Signed routes restrict approved provider deployments and regions. Network egress and provider metadata supply independent drift evidence.",
          },
        ].map(({ icon: SecurityIcon, title, detail }) => (
          <NexusCard key={title} pad>
            <SecurityIcon size={17} className="text-indigo-600 dark:text-cyan-400" />
            <h2 className="mt-3 text-sm font-bold text-slate-900 dark:text-white">{title}</h2>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">{detail}</p>
          </NexusCard>
        ))}
      </div>

      {(digest.data?.counts ?? []).length > 0 ? (
        <NexusCard pad>
          <h2 className="text-sm font-bold text-slate-900 dark:text-white">
            Last 7 days by category
          </h2>
          <p className="mt-1 text-xs text-slate-500">
            A bounded, partition-pruned aggregate over live security events.
          </p>
          <div className="grid gap-x-8 gap-y-2 sm:grid-cols-2 lg:grid-cols-4">
            {(digest.data?.counts ?? []).map((row) => (
              <div
                key={`${row.category}:${row.severity}`}
                className="flex items-center justify-between gap-2 border-b border-slate-200 py-2 dark:border-white/10"
              >
                <span className="flex min-w-0 items-center gap-1.5">
                  <AuditSeverityBadge severity={row.severity} />
                  <span className="truncate text-xs text-slate-600 dark:text-slate-300">
                    {titleCaseSnake(row.category)}
                  </span>
                </span>
                <span className="shrink-0 font-mono text-xs tabular-nums text-slate-900 dark:text-white">
                  {formatCompact(row.event_count)}
                </span>
              </div>
            ))}
          </div>
        </NexusCard>
      ) : null}

      <NexusCard>
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 px-5 py-4 dark:border-white/10">
          <div>
            <h2 className="text-sm font-bold text-slate-900 dark:text-white">Audit trail</h2>
            <p className="mt-1 text-xs text-slate-500">
              Append-only and newest first. Retention is controlled by partition policy.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <select
              value={category}
              onChange={(event) => setCategory(event.target.value as AuditCategory | "")}
              className={SELECT}
            >
              {CATEGORIES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <select
              value={outcome}
              onChange={(event) => setOutcome(event.target.value as AuditOutcome | "")}
              className={SELECT}
            >
              {OUTCOMES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <select
              value={severity}
              onChange={(event) => setSeverity(event.target.value as AuditSeverity | "")}
              className={SELECT}
            >
              {SEVERITIES.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="overflow-x-auto scrollbar-thin">
          <table className="min-w-[1040px] text-left">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50/70 dark:border-white/10 dark:bg-white/[0.02]">
                {["When", "Event", "Outcome", "Who", "What", "Why", "Detail"].map((heading) => (
                  <th
                    key={heading}
                    className="px-3 py-3 text-[10px] font-bold uppercase tracking-wider text-slate-500"
                  >
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-white/5">
              {rows.map((event) => (
                <tr key={event.id} className="transition-colors hover:bg-slate-50/70 dark:hover:bg-white/[0.02]">
                  <td className="px-3 py-3 text-xs text-slate-500" title={event.occurred_at}>
                    <RelativeTime iso={event.occurred_at} />
                  </td>
                  <td className="px-3 py-3">
                    <span className="block font-mono text-xs text-slate-900 dark:text-white">
                      {event.event_type}
                    </span>
                    <span className="mt-0.5 flex items-center gap-1.5">
                      <AuditSeverityBadge severity={event.severity} />
                      <span className="text-[10px] text-slate-500">
                        {titleCaseSnake(event.category)}
                      </span>
                    </span>
                  </td>
                  <td className="px-3 py-3">
                    <OutcomeBadge outcome={event.outcome} />
                  </td>
                  <td className="px-3 py-3">
                    <span className="block text-xs text-slate-900 dark:text-white">{event.actor_label}</span>
                    <span className="block text-[10px] text-slate-500">
                      {titleCaseSnake(event.actor_kind)}
                      {event.source_ip ? ` · ${event.source_ip}` : ""}
                    </span>
                  </td>
                  <td className="px-3 py-3 text-xs text-slate-600 dark:text-slate-300">
                    {event.target_label ?? event.target_kind ?? "—"}
                  </td>
                  <td className="px-3 py-3">
                    {event.reason_code ? (
                      <span className="font-mono text-[10px] text-slate-600 dark:text-slate-300">
                        {event.reason_code}
                      </span>
                    ) : (
                      <span className="text-[10px] text-slate-400">—</span>
                    )}
                  </td>
                  <td className="px-3 py-3">
                    {Object.keys(event.detail).length === 0 ? (
                      <span className="text-[10px] text-slate-400">—</span>
                    ) : (
                      <span className="flex flex-wrap gap-1">
                        {Object.entries(event.detail).map(([key, value]) => (
                          <span
                            key={key}
                            className="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[10px] text-slate-600 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-300"
                          >
                            {key}={String(value)}
                          </span>
                        ))}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {rows.length === 0 ? (
          <p className="px-4 py-10 text-center text-sm text-slate-500">
            Nothing matches those filters.
          </p>
        ) : null}

        <div className="flex items-center justify-between gap-4 border-t border-slate-200 px-4 py-3 text-xs text-slate-500 dark:border-white/10">
          <span>
            {rows.length.toLocaleString()} event{rows.length === 1 ? "" : "s"} loaded
            {/* No total. See the note at the top of this file. */}
          </span>
          {events.hasNextPage ? (
            <button
              type="button"
              disabled={events.isFetchingNextPage}
              onClick={() => void events.fetchNextPage()}
              className="glass-button rounded-xl px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
            >
              {events.isFetchingNextPage ? "Loading…" : "Load more"}
            </button>
          ) : (
            <span className="flex items-center gap-1.5 text-[10px] text-slate-500">
              <CheckCircle2 size={13} />
              end of the trail for these filters
            </span>
          )}
        </div>
      </NexusCard>
    </div>
  );
}
