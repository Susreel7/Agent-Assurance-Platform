import { useState, type FormEvent } from "react";
import Network from "lucide-react/dist/esm/icons/network";
import Plus from "lucide-react/dist/esm/icons/plus";
import Server from "lucide-react/dist/esm/icons/server";
import ShieldCheck from "lucide-react/dist/esm/icons/shield-check";
import X from "lucide-react/dist/esm/icons/x";
import { useNavigate } from "react-router-dom";
import {
  useMcpServers,
  useRegisterMcpServer,
} from "@/api/platformQueries";
import type {
  LifecycleState,
  McpServerRegister,
  McpTransport,
  TrustTier,
} from "@/api/platformTypes";
import { ErrorState } from "@/components/ErrorState";
import {
  NexusBadge,
  NexusCard,
  NexusMetric,
  NexusPageHeader,
} from "@/components/NexusUI";

function stateTone(state: string): "ok" | "warn" | "risk" | "info" | "default" {
  if (state === "approved") return "ok";
  if (state === "quarantined") return "risk";
  if (state === "in_review") return "info";
  if (state === "draft") return "warn";
  return "default";
}

export default function McpRegistryScreen() {
  const navigate = useNavigate();
  const [registerOpen, setRegisterOpen] = useState(false);
  const query = useMcpServers({ limit: 200 });
  const register = useRegisterMcpServer();
  const rows = query.data?.items ?? [];

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const transport = String(form.get("transport")) as McpTransport;
    const payload: McpServerRegister = {
      slug: String(form.get("slug") ?? ""),
      name: String(form.get("name") ?? ""),
      description: String(form.get("description") ?? "") || null,
      transport,
      endpoint_url:
        transport === "stdio" ? null : String(form.get("address") ?? "") || null,
      command:
        transport === "stdio" ? String(form.get("address") ?? "") || null : null,
      trust_tier: String(form.get("trust_tier")) as TrustTier,
      environments: [String(form.get("environment") ?? "dev") as LifecycleState],
      requires_approval_for_writes: form.has("requires_approval"),
    };
    register.mutate(payload, {
      onSuccess: (server) => {
        setRegisterOpen(false);
        navigate(`/admin/mcp/${encodeURIComponent(server.id)}`);
      },
    });
  };

  return (
    <div className="space-y-6">
      <NexusPageHeader
        crumbs={["Control", "MCP Registry"]}
        title="MCP Registry"
        lede="Only servers registered here can enter governed discovery, review, grant, and invocation. A registration never grants tool access."
        actions={
          <button
            type="button"
            onClick={() => setRegisterOpen(true)}
            className="glass-button-primary flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-bold"
          >
            <Plus size={14} />
            Register MCP server
          </button>
        }
      />

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <NexusMetric
          label="Registered"
          value={query.isPending ? "—" : String(rows.length)}
          meta="Live control-plane records"
        />
        <NexusMetric
          label="Approved"
          value={query.isPending ? "—" : String(rows.filter((row) => row.server.state === "approved").length)}
          meta="Eligible for granted access"
          tone={rows.some((row) => row.server.state === "approved") ? "positive" : "default"}
        />
        <NexusMetric
          label="Approved tools"
          value={query.isPending ? "—" : String(rows.reduce((sum, row) => sum + row.tool_count, 0))}
          meta={`${rows.reduce((sum, row) => sum + row.dangerous_tool_count, 0)} high-risk`}
        />
        <NexusMetric
          label="Denied calls (7d)"
          value={query.isPending ? "—" : String(rows.reduce((sum, row) => sum + row.denials_7d, 0))}
          meta="Fail-closed policy decisions"
          tone={rows.some((row) => row.denials_7d > 0) ? "negative" : "default"}
        />
      </div>

      {query.isError ? (
        <ErrorState
          message={query.error instanceof Error ? query.error.message : "Could not load MCP servers"}
          onRetry={() => void query.refetch()}
        />
      ) : rows.length > 0 ? (
        <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3">
          {rows.map((row) => (
            <button
              key={row.server.id}
              type="button"
              onClick={() => navigate(`/admin/mcp/${encodeURIComponent(row.server.id)}`)}
              className="glass-card group flex min-h-72 flex-col rounded-2xl p-5 text-left transition-colors hover:border-indigo-500/40 dark:hover:border-cyan-500/40"
            >
              <div className="mb-5 flex items-start justify-between gap-3">
                <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-indigo-500/10 text-indigo-600 dark:text-cyan-400">
                  <Server size={20} />
                </span>
                <NexusBadge tone={stateTone(row.server.state)}>{row.server.state}</NexusBadge>
              </div>
              <h2 className="text-lg font-bold text-slate-900 dark:text-white">
                {row.server.name}
              </h2>
              <p className="mt-1 font-mono text-[10px] text-slate-500">
                {row.server.slug} · {row.server.transport}
              </p>
              <p className="mt-3 line-clamp-3 text-xs leading-relaxed text-slate-600 dark:text-slate-400">
                {row.server.description ?? "No description supplied."}
              </p>
              <div className="mt-auto grid grid-cols-3 gap-2 border-t border-slate-200 pt-4 text-center dark:border-white/10">
                <span>
                  <strong className="block text-base text-slate-900 dark:text-white">{row.tool_count}</strong>
                  <small className="text-[9px] uppercase tracking-wide text-slate-500">approved tools</small>
                </span>
                <span>
                  <strong className="block text-base text-slate-900 dark:text-white">{row.grant_count}</strong>
                  <small className="text-[9px] uppercase tracking-wide text-slate-500">grants</small>
                </span>
                <span>
                  <strong className="block text-base text-slate-900 dark:text-white">{row.calls_7d}</strong>
                  <small className="text-[9px] uppercase tracking-wide text-slate-500">calls 7d</small>
                </span>
              </div>
            </button>
          ))}
        </div>
      ) : (
        <NexusCard pad className="py-12 text-center">
          <Network size={30} className="mx-auto text-slate-400" />
          <h2 className="mt-4 text-base font-bold text-slate-900 dark:text-white">
            No MCP servers registered
          </h2>
          <p className="mx-auto mt-2 max-w-xl text-xs leading-relaxed text-slate-500">
            Register a reachable server endpoint or an approved deployment command. It starts
            in draft, then discovery records its tools before a reviewer can approve and grant it.
          </p>
          <button
            type="button"
            onClick={() => setRegisterOpen(true)}
            className="glass-button-primary mx-auto mt-5 flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-bold"
          >
            <Plus size={14} /> Register your first server
          </button>
        </NexusCard>
      )}

      <NexusCard pad>
        <div className="flex items-start gap-3">
          <ShieldCheck size={18} className="mt-0.5 shrink-0 text-indigo-600 dark:text-cyan-400" />
          <div>
            <h2 className="text-sm font-bold text-slate-900 dark:text-white">
              Registration is not authorization
            </h2>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">
              The platform discovers and hashes the advertised capability set, reviewers classify
              write and irreversible behavior, grants are pinned to an approved snapshot, and each
              workload presents its own revocable Platform Key. Unknown servers, tools, snapshots,
              users, and environments fail closed.
            </p>
          </div>
        </div>
      </NexusCard>

      {registerOpen ? (
        <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <form
            onSubmit={submit}
            className="glass-card w-full max-w-2xl rounded-2xl border border-white/10 bg-white p-6 dark:bg-slate-950"
          >
            <div className="mb-5 flex items-start justify-between gap-4">
              <div>
                <h2 className="text-lg font-bold text-slate-900 dark:text-white">
                  Register MCP server
                </h2>
                <p className="mt-1 text-xs text-slate-500">
                  This records identity and address only. Discovery and approval remain separate.
                </p>
              </div>
              <button type="button" onClick={() => setRegisterOpen(false)} aria-label="Close">
                <X size={18} className="text-slate-500" />
              </button>
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <Field name="name" label="Display name" placeholder="Internal Bitbucket MCP" required />
              <Field name="slug" label="Stable slug" placeholder="bitbucket-internal" required />
              <label>
                <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-500">Transport</span>
                <select name="transport" defaultValue="streamable_http" className="glass-input h-10 w-full rounded-xl px-3 text-xs">
                  <option value="streamable_http">Streamable HTTP</option>
                  <option value="sse">SSE</option>
                  <option value="http">HTTP</option>
                  <option value="stdio">STDIO deployment command</option>
                </select>
              </label>
              <label>
                <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-500">Trust tier</span>
                <select name="trust_tier" defaultValue="unverified" className="glass-input h-10 w-full rounded-xl px-3 text-xs">
                  <option value="unverified">Unverified</option>
                  <option value="internal">Internal</option>
                  <option value="partner">Partner</option>
                  <option value="community">Community</option>
                  <option value="accredited">Accredited</option>
                </select>
              </label>
              <div className="sm:col-span-2">
                <Field name="address" label="Endpoint URL or approved command" placeholder="https://mcp.internal.example/mcp" required />
              </div>
              <div className="sm:col-span-2">
                <Field name="description" label="Description" placeholder="What this server can access and who owns it" />
              </div>
              <label>
                <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-500">Environment</span>
                <select name="environment" defaultValue="dev" className="glass-input h-10 w-full rounded-xl px-3 text-xs">
                  <option value="dev">Development</option>
                  <option value="test">Test</option>
                  <option value="staging">Staging</option>
                  <option value="production">Production</option>
                </select>
              </label>
              <label className="flex items-center gap-2 pt-6 text-xs text-slate-700 dark:text-slate-300">
                <input name="requires_approval" type="checkbox" defaultChecked />
                Require approval for write tools
              </label>
            </div>

            {register.isError ? (
              <p className="mt-4 text-xs text-rose-600 dark:text-rose-300">
                {register.error instanceof Error ? register.error.message : "Registration failed"}
              </p>
            ) : null}
            <div className="mt-6 flex justify-end gap-2">
              <button type="button" onClick={() => setRegisterOpen(false)} className="glass-button rounded-xl px-4 py-2 text-xs font-semibold">
                Cancel
              </button>
              <button type="submit" disabled={register.isPending} className="glass-button-primary rounded-xl px-4 py-2 text-xs font-bold disabled:opacity-50">
                {register.isPending ? "Registering…" : "Register server"}
              </button>
            </div>
          </form>
        </div>
      ) : null}
    </div>
  );
}

function Field({
  name,
  label,
  placeholder,
  required = false,
}: {
  name: string;
  label: string;
  placeholder: string;
  required?: boolean;
}) {
  return (
    <label>
      <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-500">
        {label}
      </span>
      <input
        name={name}
        required={required}
        placeholder={placeholder}
        className="glass-input h-10 w-full rounded-xl px-3 text-xs outline-none"
      />
    </label>
  );
}
