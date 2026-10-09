/**
 * The signed-in person's own page: who the platform thinks they are, and what that lets
 * them do.
 *
 * Deliberately shows the identity bindings rather than hiding them behind "you are signed
 * in". Somebody debugging why a permission is missing needs to see *which* directory
 * subject the platform matched them to — half of those cases turn out to be two accounts
 * at the same provider, and no amount of role-list staring reveals that.
 *
 * Permissions are listed in full, grouped by resource. A long list is the honest shape of
 * the answer: a security admin genuinely holds thirty of them, and collapsing that to
 * "Security admin" is what makes an over-privileged account invisible.
 */

import { useMemo } from "react";
import KeyRound from "lucide-react/dist/esm/icons/key-round";
import Network from "lucide-react/dist/esm/icons/network";
import ShieldCheck from "lucide-react/dist/esm/icons/shield-check";
import UserRound from "lucide-react/dist/esm/icons/user-round";
import { Link } from "react-router-dom";
import { useMyProfile, useRevokeIdentity } from "@/api/platformQueries";
import { ErrorState } from "@/components/ErrorState";
import {
  NexusBadge,
  NexusCard,
  NexusMetric,
  NexusPageHeader,
} from "@/components/NexusUI";
import { Skeleton } from "@/components/Skeleton";
import { formatTableDate } from "@/lib/dates";
import { titleCaseSnake } from "@/lib/formatters";

function initials(displayName: string): string {
  const parts = displayName.trim().split(/\s+/).slice(0, 2);
  return parts.map((p) => p[0]?.toUpperCase() ?? "").join("") || "?";
}

export default function ProfileScreen() {
  const profile = useMyProfile();
  const revoke = useRevokeIdentity();

  /** `mcp:grant` and `mcp:read` belong together; forty flat strings do not. */
  const grouped = useMemo(() => {
    const byResource = new Map<string, string[]>();
    for (const permission of profile.data?.permissions ?? []) {
      const [resource, action] = permission.split(":");
      if (!resource || !action) continue;
      const actions = byResource.get(resource);
      if (actions) actions.push(action);
      else byResource.set(resource, [action]);
    }
    return [...byResource.entries()].sort(([a], [b]) => a.localeCompare(b));
  }, [profile.data?.permissions]);

  if (profile.isPending) {
    return (
      <div className="space-y-4">
        <Skeleton height="4rem" />
        <Skeleton height="220px" />
        <Skeleton height="200px" />
      </div>
    );
  }

  if (profile.isError || !profile.data) {
    return (
      <ErrorState
        title="Could not load your profile"
        message={profile.error instanceof Error ? profile.error.message : "Unknown error"}
        onRetry={() => void profile.refetch()}
      />
    );
  }

  const { account_name, member, identities, teams, role_keys } = profile.data;
  const liveIdentities = identities.filter((identity) => !identity.revoked_at);

  return (
    <div className="space-y-6">
      <NexusPageHeader
        crumbs={["Account", "Profile"]}
        title="Your profile"
        lede={`Your verified ${account_name} directory identity, team membership, and effective access. Provider secrets remain in the connection vault and never enter profile data.`}
      />

      {revoke.isError ? (
        <div className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-4 py-3 text-xs text-rose-700 dark:text-rose-300">
          {revoke.error instanceof Error ? revoke.error.message : "Could not revoke identity"}
        </div>
      ) : null}

      <NexusCard pad>
        <div className="flex flex-wrap items-start gap-5">
          <span
            aria-hidden
            className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-slate-900 text-lg font-bold text-white dark:bg-white dark:text-black"
          >
            {initials(member.display_name)}
          </span>

          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2.5">
              <h2 className="text-xl font-bold tracking-tight text-slate-900 dark:text-white">
                {member.display_name}
              </h2>
              <NexusBadge tone={member.status === "active" ? "ok" : "warn"}>
                {member.status}
              </NexusBadge>
            </div>
            <p className="mt-1 text-sm text-slate-600 dark:text-slate-400">
              {member.job_title ? `${member.job_title} · ` : ""}
              {member.email}
            </p>

            <dl className="mt-5 grid gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-4">
              <div>
                <dt className="text-[10px] uppercase tracking-wide text-slate-500">Company</dt>
                <dd className="mt-1 text-xs font-semibold text-slate-800 dark:text-slate-200">
                  {account_name}
                </dd>
              </div>
              <div>
                <dt className="text-[10px] uppercase tracking-wide text-slate-500">Time zone</dt>
                <dd className="mt-1 text-xs font-semibold text-slate-800 dark:text-slate-200">
                  {member.timezone}
                </dd>
              </div>
              <div>
                <dt className="text-[10px] uppercase tracking-wide text-slate-500">Member since</dt>
                <dd className="mt-1 text-xs font-semibold text-slate-800 dark:text-slate-200">
                  {formatTableDate(member.created_at)}
                </dd>
              </div>
              <div>
                <dt className="text-[10px] uppercase tracking-wide text-slate-500">Last seen</dt>
                <dd className="mt-1 text-xs font-semibold text-slate-800 dark:text-slate-200">
                  {member.last_seen_at ? formatTableDate(member.last_seen_at) : "—"}
                </dd>
              </div>
            </dl>
          </div>
        </div>
      </NexusCard>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <NexusMetric
          label="Verified identities"
          value={String(liveIdentities.length)}
          meta={liveIdentities.some((identity) => identity.mfa_verified) ? "MFA verified" : "MFA not recorded"}
        />
        <NexusMetric
          label="Teams"
          value={String(teams.length)}
          meta={teams.map((team) => team.name).join(" · ") || "No team membership"}
        />
        <NexusMetric
          label="Effective permissions"
          value={String(profile.data.permissions.length)}
          meta={role_keys.map(titleCaseSnake).join(" · ") || "No roles"}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <NexusCard pad>
          <div className="mb-4 flex items-center gap-2">
            <UserRound size={16} className="text-indigo-600 dark:text-cyan-400" />
            <h2 className="text-sm font-bold text-slate-900 dark:text-white">Teams and roles</h2>
          </div>
          {teams.length === 0 ? (
            <p className="py-4 text-xs text-slate-500">You are not in a team yet.</p>
          ) : (
            <ul className="space-y-2">
              {teams.map((team) => (
                <li
                  key={team.id}
                  className="rounded-xl border border-slate-200 bg-slate-50/70 px-3 py-2 dark:border-white/10 dark:bg-white/[0.03]"
                >
                  <p className="text-xs font-semibold text-slate-800 dark:text-slate-200">
                    {team.name}
                  </p>
                  <p className="mt-0.5 text-[10px] text-slate-500">
                    {team.id === member.primary_team_id ? "Primary team · " : ""}
                    {team.source === "directory" ? "Directory managed" : "Platform managed"}
                  </p>
                </li>
              ))}
            </ul>
          )}
          <div className="mt-4 flex flex-wrap gap-2">
            {role_keys.map((role) => (
              <NexusBadge key={role} tone="info">{titleCaseSnake(role)}</NexusBadge>
            ))}
          </div>
        </NexusCard>

        <NexusCard pad>
          <div className="mb-4 flex items-center gap-2">
            <ShieldCheck size={16} className="text-indigo-600 dark:text-cyan-400" />
            <h2 className="text-sm font-bold text-slate-900 dark:text-white">Sign-in identities</h2>
          </div>
          {liveIdentities.length === 0 ? (
            <p className="rounded-xl border border-amber-500/20 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-300">
              No verified identity is bound to this member.
            </p>
          ) : (
            <ul className="space-y-2">
              {liveIdentities.map((identity) => (
                <li
                  key={identity.id}
                  className="rounded-xl border border-slate-200 bg-slate-50/70 px-3 py-2.5 dark:border-white/10 dark:bg-white/[0.03]"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate text-xs font-semibold text-slate-800 dark:text-slate-200">
                        {identity.issuer}
                      </p>
                      <p className="truncate font-mono text-[10px] text-slate-500">
                        {identity.subject}
                      </p>
                    </div>
                    <button
                      type="button"
                      onClick={() => revoke.mutate(identity.id)}
                      disabled={revoke.isPending}
                      className="shrink-0 rounded-lg px-2 py-1 text-[10px] font-semibold text-rose-600 hover:bg-rose-500/10 disabled:opacity-50"
                    >
                      Revoke
                    </button>
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    <NexusBadge tone={identity.mfa_verified ? "ok" : "warn"}>
                      {identity.mfa_verified ? "MFA verified" : "MFA not recorded"}
                    </NexusBadge>
                    <NexusBadge tone={identity.email_verified ? "ok" : "warn"}>
                      {identity.email_verified ? "Email verified" : "Email unverified"}
                    </NexusBadge>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </NexusCard>
      </div>

      <NexusCard pad>
        <div className="mb-4 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h2 className="text-sm font-bold text-slate-900 dark:text-white">Agent authentication</h2>
            <p className="mt-1 max-w-2xl text-xs text-slate-500">
              Agents receive a revocable Platform Key. LLM and MCP provider secrets stay in
              vaulted Connections and are leased only to the gateway; they are never stored on
              this profile or returned to the browser. Personal keys are bound to your verified
              profile so model and MCP activity is attributed without trusting a caller-supplied
              user header.
            </p>
          </div>
          <div className="flex gap-2">
            <Link to="/platform-keys" className="glass-button-primary flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-bold">
              <KeyRound size={13} /> Platform Keys
            </Link>
            <Link to="/admin/connections" className="glass-button flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-semibold">
              <Network size={13} /> Connections
            </Link>
          </div>
        </div>
      </NexusCard>

      <NexusCard pad>
        <h2 className="mb-1 text-sm font-bold text-slate-900 dark:text-white">
          Effective permissions
        </h2>
        <p className="mb-4 text-xs text-slate-500">
          Expanded from direct and team roles so over-privilege remains visible.
        </p>
        {grouped.length === 0 ? (
          <p className="py-6 text-center text-xs text-slate-500">You hold no permissions.</p>
        ) : (
          <div className="grid gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-3">
            {grouped.map(([resource, actions]) => (
              <div key={resource}>
                <p className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
                  {titleCaseSnake(resource)}
                </p>
                <p className="mt-1 flex flex-wrap gap-1">
                  {actions.sort().map((action) => (
                    <span
                      key={action}
                      className="rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[10px] text-slate-700 dark:border-white/10 dark:bg-white/[0.03] dark:text-slate-300"
                    >
                      {action}
                    </span>
                  ))}
                </p>
              </div>
            ))}
          </div>
        )}
      </NexusCard>
    </div>
  );
}
