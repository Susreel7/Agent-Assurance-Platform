/**
 * Badges for the governance vocabulary: server state, trust, risk, grant liveness.
 *
 * Kept out of `StateBadge.tsx` because these encode a different judgement. The badges
 * there describe how something is going; these describe whether something is permitted,
 * and the two use opposite colour logic. `quarantined` is red here even though it is the
 * system working correctly, because the operator needs to see a stopped tool as stopped.
 */

import { Badge } from "./StateBadge";
import { titleCaseSnake } from "@/lib/formatters";
import type {
  AuditSeverity,
  ConnectionStatus,
  HealthState,
  MemberStatus,
  RequestState,
  RiskTier,
  ServerState,
  TrustTier,
} from "@/api/platformTypes";

/**
 * Audit severity, which is a different scale from finding severity.
 *
 * Syslog's ladder — info, notice, warning, critical — rather than the low/medium/high a
 * finding carries, because these two answer different questions: a finding's severity is
 * how bad the problem is, an event's is how much it deserves someone's attention now. They
 * are kept as separate types on the server for the same reason, and sharing one badge here
 * would quietly imply they are comparable.
 */
export function AuditSeverityBadge({ severity }: { severity: AuditSeverity }) {
  const tone =
    severity === "critical"
      ? "risk"
      : severity === "warning"
        ? "warn"
        : severity === "notice"
          ? "info"
          : "mute";
  return <Badge label={titleCaseSnake(severity)} tone={tone} />;
}

export function MemberStatusBadge({ status }: { status: MemberStatus }) {
  const tone =
    status === "active"
      ? "ok"
      : status === "invited"
        ? "info"
        : status === "suspended"
          ? "warn"
          : "mute";
  return <Badge label={titleCaseSnake(status)} tone={tone} />;
}

/**
 * How much damage a capability can do, as reviewed rather than as claimed.
 *
 * `critical` and `high` are both red because the distinction between them changes who
 * signs off, not whether anyone does.
 */
export function RiskBadge({ risk }: { risk: RiskTier }) {
  const tone =
    risk === "critical" || risk === "high" ? "risk" : risk === "medium" ? "warn" : "mute";
  return <Badge label={titleCaseSnake(risk)} tone={tone} />;
}

export function ServerStateBadge({ state }: { state: ServerState }) {
  const tone =
    state === "approved"
      ? "ok"
      : state === "quarantined"
        ? "risk"
        : state === "in_review"
          ? "warn"
          : state === "retired"
            ? "mute"
            : "info";
  return <Badge label={titleCaseSnake(state)} tone={tone} />;
}

/**
 * Where a server came from.
 *
 * `unverified` is amber rather than red: an unverified server is not yet trusted, which
 * is a fact about the paperwork, not evidence that it is dangerous. What actually stops
 * it is having no approved snapshot.
 */
export function TrustBadge({ tier }: { tier: TrustTier }) {
  const tone =
    tier === "internal" || tier === "accredited"
      ? "ok"
      : tier === "partner"
        ? "info"
        : tier === "community"
          ? "mute"
          : "warn";
  return <Badge label={titleCaseSnake(tier)} tone={tone} />;
}

/**
 * What discovery last saw.
 *
 * `drift` is red, and this is the badge the whole registry exists to render: the tools a
 * server offers today are not the ones somebody reviewed and approved.
 */
export function HealthBadge({ health }: { health: HealthState }) {
  const tone =
    health === "healthy"
      ? "ok"
      : health === "drift" || health === "unreachable"
        ? "risk"
        : health === "degraded"
          ? "warn"
          : "mute";
  return <Badge label={health === "drift" ? "Drifted" : titleCaseSnake(health)} tone={tone} />;
}

export function ConnectionStatusBadge({ status }: { status: ConnectionStatus }) {
  const tone =
    status === "healthy"
      ? "ok"
      : status === "degraded"
        ? "risk"
        : status === "rotating"
          ? "info"
          : status === "pending"
            ? "warn"
            : "mute";
  return <Badge label={titleCaseSnake(status)} tone={tone} />;
}

export function RequestStateBadge({ state }: { state: RequestState }) {
  const tone =
    state === "approved"
      ? "ok"
      : state === "denied"
        ? "risk"
        : state === "pending"
          ? "warn"
          : "mute";
  return <Badge label={titleCaseSnake(state)} tone={tone} />;
}

/**
 * Whether a grant is actually in force.
 *
 * Four states, not two. A revoked grant and an expired one look identical in a list that
 * only says "inactive", and they mean different things during an incident review: one was
 * taken away, the other was always going to lapse. "Temporary" is separated from "active"
 * for the same reason — the difference between holding approver on a project and holding it
 * for the next forty minutes is the whole point of the request mechanism.
 *
 * `now` is a parameter rather than a `Date.now()` call because reading the clock during
 * render makes the component non-idempotent: it can produce two different badges for the
 * same props depending on when React happens to re-render. The caller reads the clock once
 * per list, which is also the reading every row in that list should agree on.
 */
export function GrantLivenessBadge({
  revokedAt,
  expiresAt,
  now,
}: {
  revokedAt: string | null;
  expiresAt: string | null;
  now: number;
}) {
  if (revokedAt) return <Badge label="Revoked" tone="mute" />;
  if (expiresAt && new Date(expiresAt).getTime() <= now) {
    return <Badge label="Expired" tone="mute" />;
  }
  if (expiresAt) return <Badge label="Temporary" tone="info" />;
  return <Badge label="Active" tone="ok" />;
}

/** `account`, or `project:4f2a…`. Rendered as a chip so a scoped grant reads as narrower. */
export function ScopeChip({ kind, id }: { kind: string; id: string | null }) {
  return (
    <span className="inline-flex items-center gap-1 rounded border border-line-200 bg-bg-sunk px-1.5 py-0.5 text-micro text-ink-600">
      {titleCaseSnake(kind)}
      {id ? <span className="font-mono-data text-ink-400">{id.slice(0, 8)}</span> : null}
    </span>
  );
}
