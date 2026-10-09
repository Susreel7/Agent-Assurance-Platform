/**
 * Roles, who holds them, and the queue of people asking for more.
 *
 * Pending requests come first. A request is somebody blocked right now, and a screen that
 * puts the permanent grant list above the queue is a screen where requests are answered
 * late — which is how standing access gets handed out "to avoid the hassle next time".
 *
 * Temporary grants are shown as temporary rather than merged into the active list. The
 * difference between "holds approver on this project" and "holds approver for the next
 * forty minutes" is the whole point of the request mechanism, and a list that hides it
 * makes elevation look like entitlement.
 */

import { useMemo, useState } from "react";
import {
  useAccessRequests,
  useCreateAccessRequest,
  useCreateGrant,
  useDecideAccessRequest,
  useGrants,
  useMembers,
  useMyAccessRequests,
  useMyProfile,
  useRevokeGrant,
  useRoles,
  useTeams,
} from "@/api/platformQueries";
import { Can } from "@/components/Can";
import { ErrorState } from "@/components/ErrorState";
import { Icon } from "@/components/Icon";
import { MutationBanner } from "@/components/MutationBanner";
import { Panel } from "@/components/Panel";
import { GrantLivenessBadge, RequestStateBadge, RiskBadge, ScopeChip } from "@/components/PlatformBadge";
import { RelativeTime } from "@/components/RelativeTime";
import { Skeleton } from "@/components/Skeleton";
import { Badge } from "@/components/StateBadge";
import { titleCaseSnake } from "@/lib/formatters";
import type { ScopeKind } from "@/api/platformTypes";

/** Offered durations. Deliberately short: the longest is a working day, not a quarter. */
const DURATIONS = [
  { minutes: 30, label: "30 minutes" },
  { minutes: 120, label: "2 hours" },
  { minutes: 480, label: "8 hours" },
];

function RequestForm({ onDone }: { onDone: () => void }) {
  const roles = useRoles();
  const create = useCreateAccessRequest();
  const [roleKey, setRoleKey] = useState("");
  const [minutes, setMinutes] = useState(120);
  const [reason, setReason] = useState("");
  const [ticket, setTicket] = useState("");

  return (
    <form
      className="grid gap-3 sm:grid-cols-2"
      onSubmit={(event) => {
        event.preventDefault();
        create.mutate(
          {
            role_key: roleKey,
            // Account scope only from this form. A project-scoped request needs a project
            // picker, and offering the scope without the picker produces requests nobody
            // can approve because the scope id is missing.
            scope_kind: "account",
            duration_minutes: minutes,
            reason,
            ticket_ref: ticket || null,
          },
          { onSuccess: onDone },
        );
      }}
    >
      <label className="flex flex-col gap-1">
        <span className="text-micro font-medium text-ink-600">Role</span>
        <select
          required
          value={roleKey}
          onChange={(event) => setRoleKey(event.target.value)}
          className="rounded-md border border-line-200 bg-bg-panel px-2.5 py-1.5 text-table text-ink-900"
        >
          <option value="">Choose a role…</option>
          {(roles.data ?? [])
            .filter((role) => role.assignable_scopes.includes("account"))
            .map((role) => (
              <option key={role.key} value={role.key}>
                {role.name}
              </option>
            ))}
        </select>
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-micro font-medium text-ink-600">For how long</span>
        <select
          value={minutes}
          onChange={(event) => setMinutes(Number(event.target.value))}
          className="rounded-md border border-line-200 bg-bg-panel px-2.5 py-1.5 text-table text-ink-900"
        >
          {DURATIONS.map((option) => (
            <option key={option.minutes} value={option.minutes}>
              {option.label}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1 sm:col-span-2">
        <span className="text-micro font-medium text-ink-600">
          Why you need it — the approver sees only this
        </span>
        <input
          required
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          placeholder="Investigating the denial spike on the payments agent"
          className="rounded-md border border-line-200 bg-bg-panel px-2.5 py-1.5 text-table text-ink-900"
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-micro font-medium text-ink-600">Ticket (optional)</span>
        <input
          value={ticket}
          onChange={(event) => setTicket(event.target.value)}
          className="rounded-md border border-line-200 bg-bg-panel px-2.5 py-1.5 text-table text-ink-900"
        />
      </label>

      <div className="flex items-end gap-2">
        <button
          type="submit"
          disabled={create.isPending}
          className="rounded-md bg-accent px-3 py-1.5 text-table font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-50"
        >
          {create.isPending ? "Requesting…" : "Request access"}
        </button>
        <button
          type="button"
          onClick={onDone}
          className="rounded-md px-3 py-1.5 text-table text-ink-600 transition-colors hover:bg-bg-hover"
        >
          Cancel
        </button>
      </div>

      {create.isError ? (
        <div className="sm:col-span-2">
          <MutationBanner
            tone="error"
            message={create.error instanceof Error ? create.error.message : "Could not request"}
            onDismiss={() => create.reset()}
          />
        </div>
      ) : null}
    </form>
  );
}

function GrantForm({ onDone }: { onDone: () => void }) {
  const roles = useRoles();
  const members = useMembers({ limit: 200, member_status: "active" });
  const teams = useTeams();
  const create = useCreateGrant();

  const [subjectKind, setSubjectKind] = useState<"member" | "team">("member");
  const [subjectId, setSubjectId] = useState("");
  const [roleKey, setRoleKey] = useState("");
  const [scopeKind, setScopeKind] = useState<ScopeKind>("account");
  const [scopeId, setScopeId] = useState("");

  const role = (roles.data ?? []).find((entry) => entry.key === roleKey);

  return (
    <form
      className="grid gap-3 sm:grid-cols-2"
      onSubmit={(event) => {
        event.preventDefault();
        create.mutate(
          {
            subject_kind: subjectKind,
            subject_id: subjectId,
            role_key: roleKey,
            scope_kind: scopeKind,
            // The API rejects a scope id on account scope and requires one everywhere
            // else, so send exactly what the chosen scope permits.
            scope_id: scopeKind === "account" ? null : scopeId,
          },
          { onSuccess: onDone },
        );
      }}
    >
      <label className="flex flex-col gap-1">
        <span className="text-micro font-medium text-ink-600">Grant to</span>
        <select
          value={subjectKind}
          onChange={(event) => {
            setSubjectKind(event.target.value as "member" | "team");
            setSubjectId("");
          }}
          className="rounded-md border border-line-200 bg-bg-panel px-2.5 py-1.5 text-table text-ink-900"
        >
          <option value="member">A member</option>
          <option value="team">A team</option>
        </select>
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-micro font-medium text-ink-600">
          {subjectKind === "member" ? "Member" : "Team"}
        </span>
        <select
          required
          value={subjectId}
          onChange={(event) => setSubjectId(event.target.value)}
          className="rounded-md border border-line-200 bg-bg-panel px-2.5 py-1.5 text-table text-ink-900"
        >
          <option value="">Choose…</option>
          {subjectKind === "member"
            ? (members.data?.items ?? []).map((row) => (
                <option key={row.member.id} value={row.member.id}>
                  {row.member.display_name} — {row.member.email}
                </option>
              ))
            : (teams.data?.items ?? []).map((row) => (
                <option key={row.team.id} value={row.team.id}>
                  {row.team.name}
                </option>
              ))}
        </select>
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-micro font-medium text-ink-600">Role</span>
        <select
          required
          value={roleKey}
          onChange={(event) => {
            setRoleKey(event.target.value);
            setScopeKind("account");
          }}
          className="rounded-md border border-line-200 bg-bg-panel px-2.5 py-1.5 text-table text-ink-900"
        >
          <option value="">Choose a role…</option>
          {(roles.data ?? []).map((entry) => (
            <option key={entry.key} value={entry.key}>
              {entry.name}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-micro font-medium text-ink-600">Scope</span>
        <select
          value={scopeKind}
          onChange={(event) => setScopeKind(event.target.value as ScopeKind)}
          disabled={!role}
          className="rounded-md border border-line-200 bg-bg-panel px-2.5 py-1.5 text-table text-ink-900 disabled:opacity-50"
        >
          {/* Only the scopes this role is allowed at — the API refuses the rest anyway. */}
          {(role?.assignable_scopes ?? ["account"]).map((kind) => (
            <option key={kind} value={kind}>
              {titleCaseSnake(kind)}
            </option>
          ))}
        </select>
      </label>

      {scopeKind !== "account" ? (
        <label className="flex flex-col gap-1 sm:col-span-2">
          <span className="text-micro font-medium text-ink-600">
            {titleCaseSnake(scopeKind)} identifier
          </span>
          <input
            required
            value={scopeId}
            onChange={(event) => setScopeId(event.target.value)}
            placeholder="UUID of the resource this grant is limited to"
            className="rounded-md border border-line-200 bg-bg-panel px-2.5 py-1.5 font-mono-data text-table text-ink-900"
          />
        </label>
      ) : null}

      {role ? (
        <p className="sm:col-span-2 text-micro text-ink-400">
          {role.description} Carries {role.permissions.length} permission
          {role.permissions.length === 1 ? "" : "s"}.
          {role.separation_of_duty
            ? " Separation of duty applies: the holder cannot approve their own work."
            : ""}
        </p>
      ) : null}

      <div className="sm:col-span-2 flex items-center gap-2">
        <button
          type="submit"
          disabled={create.isPending}
          className="rounded-md bg-accent px-3 py-1.5 text-table font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-50"
        >
          {create.isPending ? "Granting…" : "Grant role"}
        </button>
        <button
          type="button"
          onClick={onDone}
          className="rounded-md px-3 py-1.5 text-table text-ink-600 transition-colors hover:bg-bg-hover"
        >
          Cancel
        </button>
      </div>

      {create.isError ? (
        <div className="sm:col-span-2">
          <MutationBanner
            tone="error"
            message={create.error instanceof Error ? create.error.message : "Could not grant"}
            onDismiss={() => create.reset()}
          />
        </div>
      ) : null}
    </form>
  );
}

function PendingQueue() {
  const requests = useAccessRequests({ state: "pending", limit: 50 });
  const decide = useDecideAccessRequest();
  const profile = useMyProfile();
  const members = useMembers({ limit: 200 });

  const nameOf = useMemo(() => {
    const byId = new Map<string, string>();
    for (const row of members.data?.items ?? []) byId.set(row.member.id, row.member.display_name);
    return byId;
  }, [members.data?.items]);

  const rows = requests.data?.items ?? [];
  if (rows.length === 0) return null;

  return (
    <Panel
      title={`${rows.length} request${rows.length === 1 ? "" : "s"} waiting`}
      explain="Each one is somebody blocked. Approving grants the role for the requested window only; it lapses without anybody remembering to revoke it."
    >
      {decide.isError ? (
        <MutationBanner
          tone="error"
          message={decide.error instanceof Error ? decide.error.message : "Could not decide"}
          onDismiss={() => decide.reset()}
        />
      ) : null}

      <ul className="flex flex-col gap-2">
        {rows.map((request) => {
          // The API refuses this too, but a button that always fails is worse than no button.
          const ownRequest = request.requester_member_id === profile.data?.member.id;
          return (
            <li
              key={request.id}
              className="flex flex-wrap items-start gap-3 rounded-lg border border-line-200 bg-bg-sunk px-3 py-2.5"
            >
              <div className="min-w-0 flex-1">
                <p className="flex flex-wrap items-center gap-2">
                  <span className="text-table font-medium text-ink-900">
                    {nameOf.get(request.requester_member_id) ?? "A member"}
                  </span>
                  <span className="text-table text-ink-600">wants</span>
                  <Badge label={titleCaseSnake(request.role_key)} tone="info" />
                  <ScopeChip kind={request.scope_kind} id={request.scope_id} />
                  <RiskBadge risk={request.risk} />
                </p>
                <p className="mt-1 text-table text-ink-700">{request.reason}</p>
                <p className="mt-0.5 text-micro text-ink-400">
                  {request.duration_minutes} minutes · asked <RelativeTime iso={request.created_at} />
                  {request.ticket_ref ? ` · ${request.ticket_ref}` : ""}
                </p>
              </div>

              <Can
                permission="access:approve"
                fallback={<span className="text-micro text-ink-400">awaiting an approver</span>}
              >
                <div className="flex shrink-0 items-center gap-1.5">
                  <button
                    type="button"
                    disabled={decide.isPending || ownRequest}
                    title={ownRequest ? "You cannot approve your own request." : undefined}
                    onClick={() =>
                      decide.mutate({ requestId: request.id, payload: { approve: true } })
                    }
                    className="rounded-md bg-accent px-2.5 py-1 text-micro font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-40"
                  >
                    Approve
                  </button>
                  <button
                    type="button"
                    disabled={decide.isPending || ownRequest}
                    onClick={() =>
                      decide.mutate({ requestId: request.id, payload: { approve: false } })
                    }
                    className="rounded-md border border-line-200 px-2.5 py-1 text-micro font-medium text-ink-700 transition-colors hover:bg-bg-hover disabled:opacity-40"
                  >
                    Deny
                  </button>
                </div>
              </Can>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}

export default function AccessScreen() {
  const [granting, setGranting] = useState(false);
  const [requesting, setRequesting] = useState(false);
  const [includeRevoked, setIncludeRevoked] = useState(false);

  const roles = useRoles();
  const grants = useGrants({ limit: 100, include_revoked: includeRevoked });
  const mine = useMyAccessRequests();
  const revoke = useRevokeGrant();

  // One clock reading for the whole table, so every row agrees on what "expired" means.
  const asOf = grants.dataUpdatedAt;

  if (roles.isPending || grants.isPending) {
    return (
      <div className="space-y-4">
        <Skeleton height="200px" />
        <Skeleton height="340px" />
      </div>
    );
  }

  if (grants.isError || !grants.data) {
    return (
      <ErrorState
        title="Could not load access"
        message={grants.error instanceof Error ? grants.error.message : "Unknown error"}
        onRetry={() => void grants.refetch()}
      />
    );
  }

  const myPending = (mine.data?.items ?? []).filter((request) => request.state === "pending");

  return (
    <div className="space-y-4">
      <PendingQueue />

      {myPending.length > 0 ? (
        <div className="flex items-start gap-2.5 rounded-card bg-info-bg px-4 py-3 text-body text-info-fg shadow-card">
          <Icon name="clock" size={18} className="mt-0.5 shrink-0" />
          <p>
            You have {myPending.length} request{myPending.length === 1 ? "" : "s"} waiting on an
            approver. Nothing changes for you until somebody decides.
          </p>
        </div>
      ) : null}

      <Panel
        title="Live grants"
        explain="A grant is a role at a scope. Account scope subsumes the narrower ones, which is why an account-level security admin needs no per-project grant."
        noPadding
        toolbar={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setIncludeRevoked((value) => !value)}
              aria-pressed={includeRevoked}
              className={`rounded-md px-2.5 py-1 text-table transition-colors ${
                includeRevoked
                  ? "bg-accent text-white"
                  : "bg-bg-sunk text-ink-600 hover:bg-bg-hover hover:text-ink-900"
              }`}
            >
              Include revoked
            </button>
            <button
              type="button"
              onClick={() => setRequesting((open) => !open)}
              className="rounded-md border border-line-200 px-2.5 py-1 text-table text-ink-700 transition-colors hover:bg-bg-hover"
            >
              Request access
            </button>
            <Can permission="access:write">
              <button
                type="button"
                onClick={() => setGranting((open) => !open)}
                className="rounded-md bg-accent px-2.5 py-1 text-table font-medium text-white transition-colors hover:bg-accent-hover"
              >
                Grant role
              </button>
            </Can>
          </div>
        }
      >
        {requesting ? (
          <div className="border-b border-line-200 px-4 py-4">
            <RequestForm onDone={() => setRequesting(false)} />
          </div>
        ) : null}
        {granting ? (
          <div className="border-b border-line-200 px-4 py-4">
            <GrantForm onDone={() => setGranting(false)} />
          </div>
        ) : null}

        {revoke.isError ? (
          <div className="px-4 pt-4">
            <MutationBanner
              tone="error"
              message={revoke.error instanceof Error ? revoke.error.message : "Could not revoke"}
              onDismiss={() => revoke.reset()}
            />
          </div>
        ) : null}

        <div className="overflow-x-auto scrollbar-thin">
          <table className="min-w-[900px]">
            <thead>
              <tr>
                <th className="px-3 py-2">Holder</th>
                <th className="px-3 py-2">Role</th>
                <th className="px-3 py-2">Scope</th>
                <th className="px-3 py-2 text-right">Permissions</th>
                <th className="px-3 py-2">State</th>
                <th className="px-3 py-2">Granted</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {grants.data.items.map((entry) => (
                <tr key={entry.grant.id} className="hover:bg-bg-hover">
                  <td className="px-3 py-2">
                    <span className="block font-medium text-ink-900">{entry.subject_label}</span>
                    <span className="block text-micro text-ink-400">
                      {titleCaseSnake(entry.grant.subject_kind)}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-ink-900">{entry.role_name}</td>
                  <td className="px-3 py-2">
                    <span title={entry.scope_label}>
                      <ScopeChip kind={entry.grant.scope_kind} id={entry.grant.scope_id} />
                    </span>
                  </td>
                  <td
                    className="px-3 py-2 text-right font-mono tabular-nums text-ink-600"
                    title={entry.permissions.join(", ")}
                  >
                    {entry.permissions.length}
                  </td>
                  <td className="px-3 py-2">
                    <GrantLivenessBadge
                      revokedAt={entry.grant.revoked_at}
                      expiresAt={entry.grant.expires_at}
                      now={asOf}
                    />
                  </td>
                  <td className="px-3 py-2 text-ink-600">
                    <RelativeTime iso={entry.grant.created_at} />
                    <span className="ml-1 text-micro text-ink-400">
                      by {entry.grant.granted_by}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right">
                    {entry.grant.revoked_at ? null : (
                      <Can permission="access:write">
                        <button
                          type="button"
                          disabled={revoke.isPending}
                          onClick={() => revoke.mutate(entry.grant.id)}
                          className="rounded-md px-2 py-1 text-micro font-medium text-risk-fg transition-colors hover:bg-risk-bg disabled:opacity-50"
                        >
                          Revoke
                        </button>
                      </Can>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {grants.data.items.length === 0 ? (
          <p className="px-4 py-10 text-center text-body text-ink-400">
            Nobody holds a role yet. Until somebody does, this account can be signed into and
            nothing more.
          </p>
        ) : null}
      </Panel>

      <Panel
        title="Roles"
        explain="Built-in roles are seeded and immutable so they mean the same thing in every account. A tenant role is yours to define."
      >
        <div className="grid gap-2 lg:grid-cols-2">
          {(roles.data ?? []).map((role) => (
            <div
              key={role.id}
              className="rounded-lg border border-line-200 bg-bg-sunk px-3 py-2.5"
            >
              <div className="flex items-start justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-table font-medium text-ink-900">{role.name}</p>
                  <p className="mt-0.5 text-micro text-ink-400">{role.description}</p>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-1">
                  {role.builtin ? <Badge label="Built in" tone="mute" /> : null}
                  {role.separation_of_duty ? (
                    <Badge label="Separated duty" tone="info" />
                  ) : null}
                </div>
              </div>
              <p className="mt-2 flex flex-wrap gap-1">
                {role.permissions.slice(0, 8).map((permission) => (
                  <span
                    key={permission}
                    className="rounded border border-line-200 bg-bg-panel px-1.5 py-0.5 font-mono-data text-micro text-ink-600"
                  >
                    {permission}
                  </span>
                ))}
                {role.permissions.length > 8 ? (
                  <span className="px-1 py-0.5 text-micro text-ink-400">
                    +{role.permissions.length - 8} more
                  </span>
                ) : null}
              </p>
            </div>
          ))}
        </div>
      </Panel>

      {(mine.data?.items ?? []).length > 0 ? (
        <Panel title="Your requests" explain="Including the ones already decided.">
          <ul className="flex flex-col gap-1.5">
            {(mine.data?.items ?? []).map((request) => (
              <li
                key={request.id}
                className="flex flex-wrap items-center gap-2 rounded-lg border border-line-200 bg-bg-sunk px-3 py-2 text-table"
              >
                <RequestStateBadge state={request.state} />
                <span className="font-medium text-ink-900">{titleCaseSnake(request.role_key)}</span>
                <ScopeChip kind={request.scope_kind} id={request.scope_id} />
                <span className="text-ink-600">{request.duration_minutes} min</span>
                <span className="ml-auto text-micro text-ink-400">
                  {request.decided_at ? (
                    <>
                      decided <RelativeTime iso={request.decided_at} /> by {request.decided_by}
                    </>
                  ) : (
                    <>
                      asked <RelativeTime iso={request.created_at} />
                    </>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </Panel>
      ) : null}
    </div>
  );
}
