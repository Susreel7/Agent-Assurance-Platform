import { useState, type FormEvent } from "react";
import Activity from "lucide-react/dist/esm/icons/activity";
import FolderTree from "lucide-react/dist/esm/icons/folder-tree";
import Layers from "lucide-react/dist/esm/icons/layers";
import ShieldCheck from "lucide-react/dist/esm/icons/shield-check";
import UserPlus from "lucide-react/dist/esm/icons/user-plus";
import Users from "lucide-react/dist/esm/icons/users";
import X from "lucide-react/dist/esm/icons/x";
import { Link } from "react-router-dom";
import {
  useCreateTeam,
  useInviteMember,
  useMembers,
  useRoles,
  useTeams,
} from "@/api/platformQueries";
import { useObservedUsers } from "@/api/suiteQueries";
import { ErrorState } from "@/components/ErrorState";
import {
  NexusBadge,
  NexusCard,
  NexusMetric,
  NexusPageHeader,
} from "@/components/NexusUI";
import { SuiteProjectProvider, ProjectSelect } from "@/features/suite/SuiteProjectProvider";
import { useSuiteProject } from "@/features/suite/useSuiteProject";
import { formatTableDate } from "@/lib/dates";
import { titleCaseSnake } from "@/lib/formatters";

const INPUT =
  "w-full rounded-xl border border-slate-200 bg-white/80 px-3 py-2 text-xs font-normal text-slate-900 outline-none transition focus:border-indigo-400 dark:border-white/10 dark:bg-black/30 dark:text-white dark:focus:border-cyan-500/50";

export default function PeopleScreen() {
  return (
    <SuiteProjectProvider>
      <PeopleContent />
    </SuiteProjectProvider>
  );
}

function PeopleContent() {
  const { projectId, projects } = useSuiteProject();
  const [showInvite, setShowInvite] = useState(false);
  const [showTeam, setShowTeam] = useState(false);
  const members = useMembers({ limit: 200 });
  const teams = useTeams();
  const roles = useRoles();
  const observed = useObservedUsers(projectId, { limit: "200" });
  const memberRows = members.data?.items ?? [];
  const teamRows = teams.data?.items ?? [];
  const observedRows = observed.data?.items ?? [];

  if (members.isError || teams.isError) {
    return (
      <ErrorState
        title="People directory is unavailable"
        message={
          members.error instanceof Error
            ? members.error.message
            : teams.error instanceof Error
              ? teams.error.message
              : "Could not load account membership."
        }
        onRetry={() => {
          void members.refetch();
          void teams.refetch();
        }}
      />
    );
  }

  return (
    <div className="space-y-6">
      <NexusPageHeader
        crumbs={["Admin", "People & teams"]}
        title="People & teams"
        lede="Verified account members, directory-backed teams, role assignments, and attributed AI activity. This page contains no generated employees or demo productivity."
        actions={
          <>
            {projects.length ? <ProjectSelect /> : null}
            <button
              type="button"
              onClick={() => setShowTeam(true)}
              className="glass-button flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-semibold"
            >
              <FolderTree size={14} />
              Create team
            </button>
            <button
              type="button"
              onClick={() => setShowInvite(true)}
              className="glass-button-primary flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-bold"
            >
              <UserPlus size={14} />
              Invite employee
            </button>
          </>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <NexusMetric
          label="Members"
          value={members.isPending ? "—" : String(memberRows.length)}
          meta={`${memberRows.filter((row) => row.member.status === "active").length} active`}
        />
        <NexusMetric
          label="Teams"
          value={teams.isPending ? "—" : String(teamRows.length)}
          meta={`${teamRows.filter((row) => row.team.source === "directory").length} directory managed`}
        />
        <NexusMetric
          label="Observed people"
          value={observed.isPending ? "—" : String(observedRows.length)}
          meta="Attributed in selected project"
        />
        <NexusMetric
          label="Unbound identities"
          value={
            members.isPending
              ? "—"
              : String(memberRows.filter((row) => row.identity_count === 0).length)
          }
          meta="Cannot sign in"
          tone={memberRows.some((row) => row.identity_count === 0) ? "negative" : "positive"}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
        <NexusCard className="overflow-x-auto">
          <div className="flex items-center gap-2 border-b border-slate-200 px-5 py-4 dark:border-white/10">
            <Users size={16} className="text-indigo-600 dark:text-cyan-400" />
            <h2 className="text-sm font-bold text-slate-900 dark:text-white">
              Member directory
            </h2>
          </div>
          <table className="min-w-[820px] text-left">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50/70 dark:border-white/10 dark:bg-white/[0.02]">
                {["Person", "Teams", "Roles", "Identity", "MFA", "Last seen"].map((heading) => (
                  <th key={heading} className="px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-slate-500">
                    {heading}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-white/5">
              {memberRows.map((row) => (
                <tr key={row.member.id}>
                  <td className="px-4 py-3">
                    <p className="text-xs font-bold text-slate-900 dark:text-white">
                      {row.member.display_name}
                    </p>
                    <p className="font-mono text-[10px] text-slate-500">{row.member.email}</p>
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {row.team_names.join(", ") || "No team"}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {row.role_keys.map(titleCaseSnake).join(", ") || "No role"}
                  </td>
                  <td className="px-4 py-3">
                    <NexusBadge tone={row.identity_count > 0 ? "ok" : "risk"}>
                      {row.identity_count > 0 ? `${row.identity_count} bound` : "unbound"}
                    </NexusBadge>
                  </td>
                  <td className="px-4 py-3">
                    <NexusBadge tone={row.mfa_verified ? "ok" : "warn"}>
                      {row.mfa_verified ? "verified" : "not recorded"}
                    </NexusBadge>
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-500">
                    {row.member.last_seen_at ? formatTableDate(row.member.last_seen_at) : "Never"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!members.isPending && memberRows.length === 0 ? (
            <p className="p-8 text-center text-xs text-slate-500">No members are registered.</p>
          ) : null}
        </NexusCard>

        <NexusCard pad>
          <div className="mb-4 flex items-center gap-2">
            <Layers size={16} className="text-indigo-600 dark:text-cyan-400" />
            <h2 className="text-sm font-bold text-slate-900 dark:text-white">Team hierarchy</h2>
          </div>
          <div className="space-y-2">
            {teamRows.map((row) => {
              const parent = teamRows.find((candidate) => candidate.team.id === row.team.parent_team_id);
              return (
                <div key={row.team.id} className="rounded-xl border border-slate-200 bg-slate-50/70 p-3 dark:border-white/10 dark:bg-white/[0.03]">
                  <p className="text-xs font-bold text-slate-900 dark:text-white">{row.team.name}</p>
                  <p className="mt-1 text-[10px] text-slate-500">
                    {parent ? `Reports through ${parent.team.name}` : "Top-level team"} ·{" "}
                    {row.member_count} members
                  </p>
                  <p className="mt-1 text-[10px] text-slate-500">
                    Leads: {row.lead_names.join(", ") || "None assigned"}
                  </p>
                </div>
              );
            })}
            {!teams.isPending && teamRows.length === 0 ? (
              <p className="py-6 text-center text-xs text-slate-500">No team hierarchy exists.</p>
            ) : null}
          </div>
        </NexusCard>
      </div>

      <NexusCard className="overflow-x-auto">
        <div className="flex items-start gap-3 border-b border-slate-200 px-5 py-4 dark:border-white/10">
          <Activity size={16} className="mt-0.5 text-indigo-600 dark:text-cyan-400" />
          <div>
            <h2 className="text-sm font-bold text-slate-900 dark:text-white">
              Attributed AI activity
            </h2>
            <p className="mt-1 text-xs text-slate-500">
              Observe-derived totals for the selected project; identities remain separate until an explicit binding is recorded.
            </p>
          </div>
        </div>
        <table className="min-w-[920px] text-left">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50/70 dark:border-white/10 dark:bg-white/[0.02]">
              {["Observed identity", "Team", "Executions", "Model generations", "Tools", "MCP tools", "SDK calls", "Last seen", "Explore"].map((heading) => (
                <th key={heading} className="px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-slate-500">{heading}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 dark:divide-white/5">
            {observedRows.map((row) => (
              <tr key={row.user_id}>
                <td className="px-4 py-3">
                  <p className="text-xs font-semibold text-slate-800 dark:text-slate-200">
                    {row.display_label ?? row.user_id}
                  </p>
                  <p className="font-mono text-[10px] text-slate-500">{row.user_id}</p>
                </td>
                <td className="px-4 py-3 text-xs text-slate-500">{row.team ?? "Unmapped"}</td>
                <td className="px-4 py-3 font-mono text-xs text-slate-500">{row.execution_count}</td>
                <td className="px-4 py-3 font-mono text-xs text-slate-500">{row.generation_count}</td>
                <td className="px-4 py-3 font-mono text-xs text-slate-500">{row.tool_count}</td>
                <td className="px-4 py-3 font-mono text-xs text-slate-500">{row.mcp_tool_count}</td>
                <td className="px-4 py-3 font-mono text-xs text-slate-500">{row.sdk_count}</td>
                <td className="whitespace-nowrap px-4 py-3 text-xs text-slate-500">
                  {row.last_seen_at ? formatTableDate(row.last_seen_at) : "—"}
                </td>
                <td className="whitespace-nowrap px-4 py-3 text-[10px] font-semibold">
                  <Link
                    to={`/observe/executions?user=${encodeURIComponent(row.user_id)}`}
                    className="text-indigo-600 hover:underline dark:text-cyan-400"
                  >
                    Runs
                  </Link>
                  <span className="px-1 text-slate-400">·</span>
                  <Link
                    to={`/observe/sessions?user=${encodeURIComponent(row.user_id)}`}
                    className="text-indigo-600 hover:underline dark:text-cyan-400"
                  >
                    Sessions
                  </Link>
                  <span className="px-1 text-slate-400">·</span>
                  <Link
                    to={`/observe/traces?user=${encodeURIComponent(row.user_id)}`}
                    className="text-indigo-600 hover:underline dark:text-cyan-400"
                  >
                    Traces
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!observed.isPending && observedRows.length === 0 ? (
          <p className="p-8 text-center text-xs text-slate-500">No user-attributed activity has been observed.</p>
        ) : null}
      </NexusCard>

      <NexusCard pad>
        <div className="flex items-start gap-3">
          <ShieldCheck size={18} className="mt-0.5 shrink-0 text-indigo-600 dark:text-cyan-400" />
          <div>
            <h2 className="text-sm font-bold text-slate-900 dark:text-white">
              Visibility follows grants, not job titles
            </h2>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">
              Team and account data is returned only when the signed-in member has platform
              read permission at that scope. A title such as “manager” is descriptive and
              never grants access by itself. Directory groups and reporting relationships
              must be explicitly mapped before a manager can see subordinate rollups.
            </p>
          </div>
        </div>
      </NexusCard>

      {showInvite ? (
        <InviteEmployeeModal
          teams={teamRows.map((row) => row.team)}
          roles={roles.data ?? []}
          onClose={() => setShowInvite(false)}
        />
      ) : null}
      {showTeam ? (
        <CreateTeamModal
          teams={teamRows.map((row) => row.team)}
          onClose={() => setShowTeam(false)}
        />
      ) : null}
    </div>
  );
}

type TeamOption = { id: string; name: string };
type RoleOption = { key: string; name: string };

function ModalFrame({
  title,
  description,
  onClose,
  children,
}: {
  title: string;
  description: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm">
      <div className="glass-card w-full max-w-lg rounded-2xl">
        <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4 dark:border-white/10">
          <div>
            <h2 className="text-base font-bold text-slate-900 dark:text-white">{title}</h2>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">{description}</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-lg p-1.5 hover:bg-white/10">
            <X size={16} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function InviteEmployeeModal({
  teams,
  roles,
  onClose,
}: {
  teams: TeamOption[];
  roles: RoleOption[];
  onClose: () => void;
}) {
  const invite = useInviteMember();
  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [jobTitle, setJobTitle] = useState("");
  const [teamId, setTeamId] = useState("");
  const [roleKey, setRoleKey] = useState("viewer");

  async function submit(event: FormEvent) {
    event.preventDefault();
    await invite.mutateAsync({
      email,
      display_name: displayName,
      job_title: jobTitle || null,
      primary_team_id: teamId || null,
      team_ids: teamId ? [teamId] : [],
      role_keys: roleKey ? [roleKey] : [],
    });
    onClose();
  }

  return (
    <ModalFrame
      title="Invite an employee"
      description="The invitation is matched to the employee's verified Entra email. Their immutable directory subject is bound on first sign-in; an uninvited tenant user receives no access."
      onClose={onClose}
    >
      <form onSubmit={(event) => void submit(event)} className="space-y-4 p-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Work email">
            <input required type="email" value={email} onChange={(event) => setEmail(event.target.value)} className={INPUT} placeholder="name@example.com" />
          </Field>
          <Field label="Display name">
            <input required value={displayName} onChange={(event) => setDisplayName(event.target.value)} className={INPUT} placeholder="Employee name" />
          </Field>
        </div>
        <Field label="Job title">
          <input value={jobTitle} onChange={(event) => setJobTitle(event.target.value)} className={INPUT} placeholder="Optional" />
        </Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Primary team">
            <select value={teamId} onChange={(event) => setTeamId(event.target.value)} className={INPUT}>
              <option value="">No team</option>
              {teams.map((team) => <option key={team.id} value={team.id}>{team.name}</option>)}
            </select>
          </Field>
          <Field label="Initial role">
            <select value={roleKey} onChange={(event) => setRoleKey(event.target.value)} className={INPUT}>
              <option value="">No role</option>
              {roles.map((role) => <option key={role.key} value={role.key}>{role.name}</option>)}
            </select>
          </Field>
        </div>
        {invite.isError ? (
          <p className="text-xs text-rose-600">{invite.error instanceof Error ? invite.error.message : "Invitation failed"}</p>
        ) : null}
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="glass-button rounded-xl px-4 py-2 text-xs font-semibold">Cancel</button>
          <button disabled={invite.isPending} className="glass-button-primary rounded-xl px-4 py-2 text-xs font-bold disabled:opacity-50">
            {invite.isPending ? "Inviting…" : "Invite employee"}
          </button>
        </div>
      </form>
    </ModalFrame>
  );
}

function CreateTeamModal({ teams, onClose }: { teams: TeamOption[]; onClose: () => void }) {
  const create = useCreateTeam();
  const [name, setName] = useState("");
  const [parentId, setParentId] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    const slug = name.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
    await create.mutateAsync({
      slug,
      name,
      parent_team_id: parentId || null,
      source: "manual",
    });
    onClose();
  }

  return (
    <ModalFrame
      title="Create a team"
      description="Teams form the reporting hierarchy and receive roles and MCP grants as a unit. Directory synchronization can later take ownership through an Entra group ID."
      onClose={onClose}
    >
      <form onSubmit={(event) => void submit(event)} className="space-y-4 p-5">
        <Field label="Team name">
          <input required value={name} onChange={(event) => setName(event.target.value)} className={INPUT} placeholder="Platform Engineering" />
        </Field>
        <Field label="Reports through">
          <select value={parentId} onChange={(event) => setParentId(event.target.value)} className={INPUT}>
            <option value="">Top-level team</option>
            {teams.map((team) => <option key={team.id} value={team.id}>{team.name}</option>)}
          </select>
        </Field>
        {create.isError ? (
          <p className="text-xs text-rose-600">{create.error instanceof Error ? create.error.message : "Team creation failed"}</p>
        ) : null}
        <div className="flex justify-end gap-2 pt-2">
          <button type="button" onClick={onClose} className="glass-button rounded-xl px-4 py-2 text-xs font-semibold">Cancel</button>
          <button disabled={create.isPending} className="glass-button-primary rounded-xl px-4 py-2 text-xs font-bold disabled:opacity-50">
            {create.isPending ? "Creating…" : "Create team"}
          </button>
        </div>
      </form>
    </ModalFrame>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-[10px] font-bold uppercase tracking-wider text-slate-500">
      {label}
      <span className="mt-1.5 block">{children}</span>
    </label>
  );
}
