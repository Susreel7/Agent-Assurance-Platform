import { useMemo, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Copy from "lucide-react/dist/esm/icons/copy";
import Key from "lucide-react/dist/esm/icons/key";
import Plus from "lucide-react/dist/esm/icons/plus";
import X from "lucide-react/dist/esm/icons/x";
import { api } from "@/api/client";
import { useMembers } from "@/api/platformQueries";
import type { Wire } from "@/api/types";
import {
  NexusBadge,
  NexusCard,
  NexusMetric,
  NexusPageHeader,
} from "@/components/NexusUI";

type WorkloadCredentialPage = Wire<"WorkloadCredentialPage">;
type WorkloadCredentialCreate = Wire<"WorkloadCredentialCreate">;
type WorkloadCredentialCreated = Wire<"WorkloadCredentialCreated">;
type WorkloadCredentialOut = Wire<"WorkloadCredentialOut">;
type ProjectPage = Wire<"ProjectPage">;

const SCOPE_OPTIONS = [
  ["mcp:invoke", "Invoke granted MCP tools"],
  ["router:models", "List approved model aliases"],
  ["router:chat", "OpenAI-compatible chat completions"],
  ["router:responses", "OpenAI-compatible responses"],
  ["router:embeddings", "OpenAI-compatible embeddings"],
] as const;

function relativeDate(value: string | null, now: number): string {
  if (!value) return "Never";
  const milliseconds = now - new Date(value).getTime();
  const minutes = Math.max(0, Math.floor(milliseconds / 60_000));
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
}

export default function PlatformKeysScreen() {
  const queryClient = useQueryClient();
  const [issueOpen, setIssueOpen] = useState(false);
  const [issued, setIssued] = useState<WorkloadCredentialCreated | null>(null);
  const credentials = useQuery({
    queryKey: ["workload-credentials", "platform-keys"],
    queryFn: () =>
      api.get<WorkloadCredentialPage>("/v1/workload-credentials", {
        limit: "200",
        offset: "0",
      }),
  });
  const members = useMembers({ limit: 200 });
  const projects = useQuery({
    queryKey: ["workload-credentials", "projects", "key-issuer"],
    queryFn: () =>
      api.get<ProjectPage>("/v1/workload-credentials/projects", {
        limit: "200",
        offset: "0",
      }),
  });
  const create = useMutation({
    mutationFn: (payload: WorkloadCredentialCreate) =>
      api.post<WorkloadCredentialCreated>("/v1/workload-credentials", payload),
    onSuccess: (credential) => {
      setIssueOpen(false);
      setIssued(credential);
      void queryClient.invalidateQueries({ queryKey: ["workload-credentials"] });
    },
  });
  const rotate = useMutation({
    mutationFn: (credentialId: string) =>
      api.post<WorkloadCredentialCreated>(
        `/v1/workload-credentials/${credentialId}/rotate`,
      ),
    onSuccess: (credential) => {
      setIssued(credential);
      void queryClient.invalidateQueries({ queryKey: ["workload-credentials"] });
    },
  });
  const revoke = useMutation({
    mutationFn: (credentialId: string) =>
      api.post<WorkloadCredentialOut>(
        `/v1/workload-credentials/${credentialId}/revoke`,
      ),
    onSuccess: () =>
      void queryClient.invalidateQueries({ queryKey: ["workload-credentials"] }),
  });
  const rows = credentials.data?.items ?? [];
  const memberById = useMemo(
    () => new Map((members.data?.items ?? []).map((row) => [row.member.id, row.member])),
    [members.data?.items],
  );
  const now = credentials.dataUpdatedAt;
  const active = rows.filter((row) => row.revoked_at === null);
  const expiring = active.filter((row) => {
    if (!row.expires_at) return false;
    const remaining = new Date(row.expires_at).getTime() - now;
    return remaining > 0 && remaining <= 14 * 86_400_000;
  });
  const idle = active.filter(
    (row) => !row.last_used_at || now - new Date(row.last_used_at).getTime() > 30 * 86_400_000,
  );

  return (
    <div className="space-y-6">
      <NexusPageHeader
        crumbs={["Control", "Platform Keys"]}
        title="Platform Workload Keys"
        lede="Cryptographically revocable workload identities for agents, SDKs and collectors. These are distinct from provider API keys and enforce project, environment, module and model scope."
        actions={
          <button
            type="button"
            onClick={() => setIssueOpen(true)}
            className="glass-button-primary flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-bold shadow"
          >
            <Plus size={14} />
            Issue Platform Key
          </button>
        }
      />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <NexusMetric
          label="Active workload keys"
          value={credentials.isPending ? "—" : String(active.length)}
          meta={`${active.filter((row) => row.agent_id).length} agent-bound`}
        />
        <NexusMetric
          label="Expiring soon"
          value={credentials.isPending ? "—" : String(expiring.length)}
          meta="Within 14 days"
          tone={expiring.length > 0 ? "negative" : "positive"}
        />
        <NexusMetric
          label="Idle & unused"
          value={credentials.isPending ? "—" : String(idle.length)}
          meta="No activity for 30+ days"
        />
        <NexusMetric
          label="Revoked"
          value={credentials.isPending ? "—" : String(rows.length - active.length)}
          meta="Denied immediately at introspection"
        />
      </div>

      <div className="glass-card overflow-x-auto rounded-2xl">
        <table className="min-w-[1080px] text-left">
          <thead>
            <tr>
              {[
                "Key identity",
                "Environment",
                "Attributed person",
                "Bound agent",
                "Granted scopes",
                "Last used",
                "Expires",
                "Status",
                "Actions",
              ].map((heading) => (
                <th
                  key={heading}
                  className="border-b border-slate-200 bg-slate-50/70 px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-slate-500 dark:border-white/10 dark:bg-white/[0.02] dark:text-slate-400"
                >
                  {heading}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 dark:divide-white/5">
            {rows.map((credential) => (
              <tr
                key={credential.id}
                className="transition-colors hover:bg-slate-50 dark:hover:bg-white/[0.03]"
              >
                <td className="px-4 py-3">
                  <div className="text-sm font-bold text-slate-900 dark:text-white">
                    {credential.name}
                  </div>
                  <div className="font-mono text-[10px] text-slate-500">
                    {credential.id.slice(0, 8)}… generation{" "}
                    {credential.active_generation_number ?? "—"}
                  </div>
                </td>
                <td className="px-4 py-3 text-xs capitalize text-slate-600 dark:text-slate-300">
                  {credential.environment}
                </td>
                <td className="px-4 py-3 text-xs text-slate-600 dark:text-slate-300">
                  {credential.member_id
                    ? memberById.get(credential.member_id)?.display_name ?? credential.member_id
                    : "Service credential"}
                </td>
                <td className="px-4 py-3 font-mono text-xs text-slate-600 dark:text-slate-300">
                  {credential.agent_id?.slice(0, 12) ?? "Collector / service"}
                </td>
                <td className="max-w-xs px-4 py-3 font-mono text-xs text-slate-500 dark:text-slate-400">
                  {[...credential.modules, ...credential.scopes].join(" · ")}
                </td>
                <td className="px-4 py-3 text-xs text-slate-500">
                  {relativeDate(credential.last_used_at, now)}
                </td>
                <td className="px-4 py-3 text-xs text-slate-600 dark:text-slate-300">
                  {credential.expires_at
                    ? new Date(credential.expires_at).toLocaleDateString()
                    : "No expiry"}
                </td>
                <td className="px-4 py-3">
                  <NexusBadge tone={credential.revoked_at ? "risk" : "ok"}>
                    {credential.revoked_at ? "Revoked" : "Active"}
                  </NexusBadge>
                </td>
                <td className="px-4 py-3">
                  <button
                    type="button"
                    onClick={() => {
                      if (
                        window.confirm(
                          `Rotate ${credential.name}? Its current secret will stop working immediately.`,
                        )
                      ) {
                        rotate.mutate(credential.id);
                      }
                    }}
                    className="glass-button rounded-lg px-3 py-1.5 text-xs font-semibold"
                    disabled={Boolean(credential.revoked_at) || rotate.isPending}
                  >
                    Rotate
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      if (
                        window.confirm(
                          `Revoke ${credential.name}? Every client using it will be denied.`,
                        )
                      ) {
                        revoke.mutate(credential.id);
                      }
                    }}
                    className="ml-2 rounded-lg px-2 py-1.5 text-xs font-semibold text-rose-600 hover:bg-rose-500/10"
                    disabled={Boolean(credential.revoked_at) || revoke.isPending}
                  >
                    Revoke
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!credentials.isPending && rows.length === 0 ? (
          <div className="p-8 text-center text-sm text-slate-500">
            No Platform Keys have been issued.
          </div>
        ) : null}
      </div>

      <NexusCard pad className="max-w-4xl border-indigo-500/20 bg-indigo-500/5">
        <h2 className="mb-2 text-lg font-bold text-slate-900 dark:text-white">
          Two-key workload isolation
        </h2>
        <p className="text-xs leading-relaxed text-slate-600 dark:text-indigo-200/70">
          The workload presents an AAP Platform Key. The gateway verifies its digest and scope,
          then leases the customer-owned provider credential in memory. Provider secrets never
          enter agent configuration, PostgreSQL responses or signed routing snapshots.
        </p>
      </NexusCard>

      {issueOpen ? (
        <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <form
            onSubmit={(event) => submitCredential(event, create.mutate)}
            className="glass-card w-full max-w-2xl rounded-2xl bg-white p-6 dark:bg-slate-950"
          >
            <div className="mb-5 flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-bold text-slate-900 dark:text-white">
                  Issue Platform Key
                </h2>
                <p className="mt-1 text-xs text-slate-500">
                  The secret is shown once. Choose only the scopes this workload needs.
                </p>
              </div>
              <button type="button" onClick={() => setIssueOpen(false)} aria-label="Close">
                <X size={18} className="text-slate-500" />
              </button>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <label>
                <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-500">Name</span>
                <input name="name" required placeholder="cursor-workspace" className="glass-input h-10 w-full rounded-xl px-3 text-xs" />
              </label>
              <label>
                <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-500">Project</span>
                <select name="project_id" required className="glass-input h-10 w-full rounded-xl px-3 text-xs">
                  {(projects.data?.items ?? []).map((project) => (
                    <option key={project.id} value={project.id}>{project.name}</option>
                  ))}
                </select>
              </label>
              <label>
                <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-500">Environment</span>
                <select name="environment" defaultValue="production" className="glass-input h-10 w-full rounded-xl px-3 text-xs">
                  <option value="dev">Development</option>
                  <option value="test">Test</option>
                  <option value="staging">Staging</option>
                  <option value="production">Production</option>
                </select>
              </label>
              <label>
                <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-500">Agent ID (optional)</span>
                <input name="agent_id" placeholder="UUID for a single agent" className="glass-input h-10 w-full rounded-xl px-3 font-mono text-xs" />
              </label>
              <label>
                <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-500">Attributed person (optional)</span>
                <select name="member_id" defaultValue="" className="glass-input h-10 w-full rounded-xl px-3 text-xs">
                  <option value="">Shared service / no person</option>
                  {(members.data?.items ?? []).map((row) => (
                    <option key={row.member.id} value={row.member.id}>
                      {row.member.display_name} · {row.member.email}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-500">Expires (optional)</span>
                <input name="expires_at" type="datetime-local" className="glass-input h-10 w-full rounded-xl px-3 text-xs" />
              </label>
              <label>
                <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-500">Allowed model patterns</span>
                <input name="model_patterns" placeholder="company/*, approved-alias" className="glass-input h-10 w-full rounded-xl px-3 font-mono text-xs" />
              </label>
              <fieldset className="sm:col-span-2">
                <legend className="mb-2 text-[10px] font-bold uppercase tracking-wider text-slate-500">Scopes</legend>
                <div className="grid gap-2 sm:grid-cols-2">
                  {SCOPE_OPTIONS.map(([scope, label]) => (
                    <label key={scope} className="flex gap-2 rounded-xl border border-slate-200 p-3 text-xs dark:border-white/10">
                      <input name="scopes" type="checkbox" value={scope} defaultChecked={scope === "mcp:invoke"} />
                      <span>
                        <strong className="block font-mono text-slate-800 dark:text-slate-200">{scope}</strong>
                        <small className="text-slate-500">{label}</small>
                      </span>
                    </label>
                  ))}
                </div>
              </fieldset>
            </div>

            {create.isError ? (
              <p className="mt-4 text-xs text-rose-600">
                {create.error instanceof Error ? create.error.message : "Could not issue key"}
              </p>
            ) : null}
            <div className="mt-6 flex justify-end gap-2">
              <button type="button" onClick={() => setIssueOpen(false)} className="glass-button rounded-xl px-4 py-2 text-xs font-semibold">Cancel</button>
              <button type="submit" disabled={create.isPending || !(projects.data?.items.length)} className="glass-button-primary rounded-xl px-4 py-2 text-xs font-bold disabled:opacity-50">
                {create.isPending ? "Issuing…" : "Issue key"}
              </button>
            </div>
          </form>
        </div>
      ) : null}

      {issued ? (
        <div className="fixed inset-0 z-[130] flex items-center justify-center bg-black/75 p-4 backdrop-blur-sm">
          <div className="glass-card w-full max-w-xl rounded-2xl bg-white p-6 dark:bg-slate-950">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h2 className="text-lg font-bold text-slate-900 dark:text-white">
                  Save this key now
                </h2>
                <p className="mt-1 text-xs text-slate-500">
                  {issued.name} · generation {issued.active_generation_number}. The plaintext cannot be retrieved again.
                </p>
              </div>
              <Key size={19} className="text-indigo-600 dark:text-cyan-400" />
            </div>
            <div className="mt-5 flex items-center gap-2 rounded-xl border border-amber-500/30 bg-amber-500/10 p-3">
              <code className="min-w-0 flex-1 break-all text-xs text-amber-900 dark:text-amber-100">
                {issued.secret}
              </code>
              <button type="button" onClick={() => void navigator.clipboard.writeText(issued.secret)} className="glass-button shrink-0 rounded-lg p-2" aria-label="Copy key">
                <Copy size={14} />
              </button>
            </div>
            <p className="mt-4 text-xs leading-relaxed text-slate-500">
              Store it in your organization secret manager as <code>AAP_PLATFORM_KEY</code>.
              Do not put it in source control, a profile record, or <code>mcp.json</code>.
            </p>
            <button type="button" onClick={() => setIssued(null)} className="glass-button-primary mt-5 w-full rounded-xl px-4 py-2 text-xs font-bold">
              I saved the key
            </button>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function submitCredential(
  event: FormEvent<HTMLFormElement>,
  mutate: (payload: WorkloadCredentialCreate) => void,
) {
  event.preventDefault();
  const data = new FormData(event.currentTarget);
  const scopes = data.getAll("scopes").map(String);
  if (scopes.length === 0) return;
  const modelPatterns = String(data.get("model_patterns") ?? "")
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);
  const expiresLocal = String(data.get("expires_at") ?? "");
  mutate({
    project_id: String(data.get("project_id")),
    name: String(data.get("name")),
    environment: String(data.get("environment")) as WorkloadCredentialCreate["environment"],
    agent_id: String(data.get("agent_id") ?? "") || null,
    member_id: String(data.get("member_id") ?? "") || null,
    modules: ["router"],
    scopes,
    allowed_model_patterns: modelPatterns,
    expires_at: expiresLocal ? new Date(expiresLocal).toISOString() : null,
  });
}
