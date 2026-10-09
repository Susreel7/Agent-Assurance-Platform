/**
 * Administration overview: the four things that are wrong, in the order they matter.
 *
 * Not a dashboard. Every panel here is either empty or actionable, and an empty one says so
 * plainly instead of showing a zero. A governance screen full of green counters is how a
 * drifted server sits unnoticed for a month — the screen was "healthy" the whole time
 * because nobody scrolled past the chart.
 *
 * The ordering is deliberate: a drifted tool server is live exposure, a stale credential is
 * a future incident, a pending request is somebody blocked right now, and a member holding
 * no role is only untidy.
 */

import { Link } from "react-router-dom";
import {
  useAccessRequests,
  useAuditDigest,
  useConnections,
  useMcpServers,
  useMembers,
} from "@/api/platformQueries";
import { Icon, type IconName } from "@/components/Icon";
import { Panel } from "@/components/Panel";
import { RiskBadge, ScopeChip } from "@/components/PlatformBadge";
import { RelativeTime } from "@/components/RelativeTime";
import { Skeleton } from "@/components/Skeleton";
import { Stat } from "@/components/Stat";
import { formatCompact, titleCaseSnake } from "@/lib/formatters";

/** One thing that needs a person, with somewhere to go and do it. */
function AttentionItem({
  icon,
  tone,
  title,
  detail,
  to,
  action,
}: {
  icon: IconName;
  tone: "risk" | "warn" | "info";
  title: string;
  detail: string;
  to: string;
  action: string;
}) {
  const tint =
    tone === "risk"
      ? "bg-risk-bg text-risk-fg"
      : tone === "warn"
        ? "bg-warn-bg text-warn-fg"
        : "bg-info-bg text-info-fg";
  return (
    <li>
      <Link
        to={to}
        className="glass-card glass-card-hover flex items-start gap-3 rounded-lg px-3 py-3 hover:no-underline"
      >
        <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-lg ${tint}`}>
          <Icon name={icon} size={18} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-table font-semibold text-ink-900">{title}</span>
          <span className="mt-0.5 block text-micro text-ink-600">{detail}</span>
        </span>
        <span className="flex shrink-0 items-center gap-1 text-micro font-medium text-accent-ink">
          {action}
          <Icon name="arrowRight" size={13} />
        </span>
      </Link>
    </li>
  );
}

export default function AdminOverviewScreen() {
  const members = useMembers({ limit: 100 });
  const servers = useMcpServers({ limit: 100 });
  const connections = useConnections({ limit: 100 });
  const requests = useAccessRequests({ state: "pending", limit: 20 });
  const digest = useAuditDigest(7);

  if (members.isPending || servers.isPending || connections.isPending) {
    return (
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} height="104px" />
          ))}
        </div>
        <Skeleton height="260px" />
      </div>
    );
  }

  const serverRows = servers.data?.items ?? [];
  const connectionRows = connections.data?.items ?? [];
  const memberRows = members.data?.items ?? [];
  const pending = requests.data?.items ?? [];

  const drifted = serverRows.filter((row) => row.drifted);
  const unapproved = serverRows.filter((row) => row.server.approved_snapshot_id === null);
  const quarantined = serverRows.filter((row) => row.server.state === "quarantined");
  const overdue = connectionRows.filter((row) => row.rotation_overdue);
  const noMfa = memberRows.filter((row) => !row.mfa_verified && row.member.status === "active");
  const noRole = memberRows.filter((row) => row.role_keys.length === 0);

  const nothingWrong =
    drifted.length === 0 &&
    overdue.length === 0 &&
    pending.length === 0 &&
    noMfa.length === 0 &&
    quarantined.length === 0;

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Members"
          value={(members.data?.total ?? 0).toLocaleString()}
          explain={`${noRole.length} hold no role`}
          icon="team"
          href="/admin/people"
        />
        <Stat
          label="Tool servers"
          value={(servers.data?.total ?? 0).toLocaleString()}
          explain={`${unapproved.length} with nothing approved`}
          icon="mcp"
          iconTint={drifted.length > 0 ? "risk" : "accent"}
          tone={drifted.length > 0 ? "risk" : "neutral"}
          href="/admin/mcp"
        />
        <Stat
          label="Credentials"
          value={(connections.data?.total ?? 0).toLocaleString()}
          explain={`${overdue.length} overdue for rotation`}
          icon="key"
          iconTint={overdue.length > 0 ? "warn" : "accent"}
          tone={overdue.length > 0 ? "warn" : "neutral"}
          href="/admin/connections"
        />
        <Stat
          label="Denials, 7 days"
          value={formatCompact(digest.data?.denied_count ?? 0)}
          explain="a control refused something"
          icon="shield"
          iconTint="info"
          href="/admin/audit"
        />
      </div>

      <Panel
        title="Needs a person"
        explain="Ordered by exposure rather than by age. An empty list here means the estate is genuinely governed, not that nothing was checked."
      >
        {nothingWrong ? (
          <div className="flex items-center gap-2.5 py-6 text-body text-ink-600">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-ok-bg text-ok-fg">
              <Icon name="check" size={18} />
            </span>
            <p>
              Every tool server matches an approved capability set, no credential is past its
              rotation date, and nobody is waiting on an approver.
            </p>
          </div>
        ) : (
          <ul className="flex flex-col gap-2">
            {drifted.length > 0 ? (
              <AttentionItem
                icon="alert"
                tone="risk"
                title={`${drifted.length} tool server${drifted.length === 1 ? "" : "s"} drifted`}
                detail={`${drifted
                  .slice(0, 3)
                  .map((row) => row.server.name)
                  .join(", ")}${drifted.length > 3 ? ` and ${drifted.length - 3} more` : ""} offer tools nobody has reviewed. Pinned grants still hold, so nothing widened — but the new capabilities need a decision.`}
                to="/admin/mcp"
                action="Review"
              />
            ) : null}

            {quarantined.length > 0 ? (
              <AttentionItem
                icon="ban"
                tone="warn"
                title={`${quarantined.length} server${quarantined.length === 1 ? "" : "s"} quarantined`}
                detail="Calls are being refused. Grants are intact, so lifting the quarantine restores access exactly as it was."
                to="/admin/mcp"
                action="Open"
              />
            ) : null}

            {overdue.length > 0 ? (
              <AttentionItem
                icon="refresh"
                tone="warn"
                title={`${overdue.length} credential${overdue.length === 1 ? "" : "s"} overdue for rotation`}
                detail={`${overdue
                  .slice(0, 3)
                  .map((row) => row.connection.name)
                  .join(", ")}${overdue.length > 3 ? ` and ${overdue.length - 3} more` : ""}. The key moves in your own secret store; this records the change.`}
                to="/admin/connections"
                action="Rotate"
              />
            ) : null}

            {pending.length > 0 ? (
              <AttentionItem
                icon="clock"
                tone="info"
                title={`${pending.length} access request${pending.length === 1 ? "" : "s"} waiting`}
                detail="Each one is somebody blocked right now. Approving grants the role for the requested window only, so it lapses without anybody remembering to revoke it."
                to="/admin/access"
                action="Decide"
              />
            ) : null}

            {noMfa.length > 0 ? (
              <AttentionItem
                icon="fingerprint"
                tone="warn"
                title={`${noMfa.length} active member${noMfa.length === 1 ? "" : "s"} without MFA`}
                detail="They have signed in but never proved a second factor. Worth fixing before an auditor asks, not after."
                to="/admin/people"
                action="Open"
              />
            ) : null}
          </ul>
        )}
      </Panel>

      {pending.length > 0 ? (
        <Panel
          title="Pending access requests"
          explain="Shown here as well as on the access screen, because this is the page somebody lands on."
          more={{ label: "All requests", to: "/admin/access" }}
        >
          <ul className="flex flex-col gap-1.5">
            {pending.slice(0, 5).map((request) => (
              <li
                key={request.id}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-line-200 bg-bg-sunk px-3 py-2 text-table"
              >
                <RiskBadge risk={request.risk} />
                <span className="font-medium text-ink-900">
                  {titleCaseSnake(request.role_key)}
                </span>
                <ScopeChip kind={request.scope_kind} id={request.scope_id} />
                <span className="min-w-0 flex-1 truncate text-ink-600">{request.reason}</span>
                <span className="shrink-0 text-micro text-ink-400">
                  <RelativeTime iso={request.created_at} />
                </span>
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
    </div>
  );
}
