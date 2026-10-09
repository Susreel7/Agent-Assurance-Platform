import { useState, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import Copy from "lucide-react/dist/esm/icons/copy";
import KeyRound from "lucide-react/dist/esm/icons/key-round";
import LockKeyhole from "lucide-react/dist/esm/icons/lock-keyhole";
import Plus from "lucide-react/dist/esm/icons/plus";
import Server from "lucide-react/dist/esm/icons/server";
import ShieldAlert from "lucide-react/dist/esm/icons/shield-alert";
import Wrench from "lucide-react/dist/esm/icons/wrench";
import X from "lucide-react/dist/esm/icons/x";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "@/api/client";
import {
  useApproveSnapshot,
  useCreateMcpGrant,
  useMcpGrants,
  useMcpServer,
  useMcpUsage,
  useMembers,
  useQuarantineServer,
  useReleaseServer,
  useReviewCapability,
  useRevokeMcpGrant,
  useTeams,
} from "@/api/platformQueries";
import type {
  CapabilityReview,
  LifecycleState,
  McpCapability,
  McpGrantCreate,
} from "@/api/platformTypes";
import type { Wire } from "@/api/types";
import { ErrorState } from "@/components/ErrorState";
import {
  NexusBadge,
  NexusCard,
  NexusMetric,
  NexusPageHeader,
} from "@/components/NexusUI";
import { formatTableDate } from "@/lib/dates";

type Tab = "overview" | "tools" | "access" | "client";
type WorkloadCredentialPage = Wire<"WorkloadCredentialPage">;

export default function McpServerDetailScreen() {
  const { serverId = "" } = useParams();
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("overview");
  const [grantOpen, setGrantOpen] = useState(false);
  const [grantSubjectKind, setGrantSubjectKind] = useState<McpGrantCreate["subject_kind"]>("workload");
  const [reviewing, setReviewing] = useState<McpCapability | null>(null);
  const query = useMcpServer(serverId);
  const grants = useMcpGrants(serverId);
  const usage = useMcpUsage(serverId, 14);
  const approve = useApproveSnapshot(serverId);
  const quarantine = useQuarantineServer(serverId);
  const release = useReleaseServer(serverId);
  const createGrant = useCreateMcpGrant(serverId);
  const revokeGrant = useRevokeMcpGrant();
  const reviewCapability = useReviewCapability();
  const members = useMembers({ limit: 200 });
  const teams = useTeams();
  const credentials = useQuery({
    queryKey: ["workload-credentials", "mcp-grant-picker"],
    queryFn: () =>
      api.get<WorkloadCredentialPage>("/v1/workload-credentials", {
        limit: "200",
        offset: "0",
      }),
  });

  if (query.isPending) {
    return <div className="glass-card min-h-[28rem] animate-pulse rounded-2xl" />;
  }
  if (query.isError || !query.data) {
    return (
      <ErrorState
        title="MCP server not found"
        message={query.error instanceof Error ? query.error.message : "The registry has no such server."}
        onRetry={() => void query.refetch()}
      />
    );
  }

  const { summary, capabilities, observed_snapshot, approved_snapshot } = query.data;
  const server = summary.server;
  const adapterBase = String(import.meta.env.VITE_MCP_ADAPTER_BASE ?? "").replace(/\/$/, "");
  const clientUrl = adapterBase
    ? `${adapterBase}/v1/mcp/${encodeURIComponent(server.slug)}`
    : "";
  const cursorConfig = JSON.stringify(
    {
      mcpServers: {
        [server.slug]: {
          url: clientUrl || "<MCP_ADAPTER_BASE>/v1/mcp/" + server.slug,
          headers: {
            Authorization: "Bearer ${env:AAP_PLATFORM_KEY}",
          },
        },
      },
    },
    null,
    2,
  );
  const calls = usage.data?.reduce((sum, row) => sum + row.call_count, 0) ?? 0;
  const denials = usage.data?.reduce((sum, row) => sum + row.denied_count, 0) ?? 0;
  const statusTone =
    server.state === "approved"
      ? "ok"
      : server.state === "quarantined"
        ? "risk"
        : server.state === "in_review"
          ? "info"
          : "warn";
  const submitGrant = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const subjectKind = String(form.get("subject_kind")) as McpGrantCreate["subject_kind"];
    const subjectId = String(form.get("subject_id") ?? "").trim();
    const workloadEnvironment =
      subjectKind === "workload"
        ? credentials.data?.items.find((credential) => credential.id === subjectId)?.environment
        : undefined;
    const payload: McpGrantCreate = {
      subject_kind: subjectKind,
      subject_id: subjectId,
      capability_name: String(form.get("capability_name") ?? "") || null,
      environments: [
        (workloadEnvironment ?? String(form.get("environment") ?? "dev")) as LifecycleState,
      ],
      permission: "invoke",
      requires_approval: form.has("requires_approval"),
      pin_approved_snapshot: true,
      reason: String(form.get("reason") ?? "").trim() || null,
    };
    createGrant.mutate(payload, {
      onSuccess: () => setGrantOpen(false),
    });
  };
  const submitReview = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!reviewing) return;
    const form = new FormData(event.currentTarget);
    const payload: CapabilityReview = {
      verified_risk: String(form.get("verified_risk")) as CapabilityReview["verified_risk"],
      verified_write: form.has("verified_write"),
      verified_irreversible: form.has("verified_irreversible"),
      review_note: String(form.get("review_note") ?? "").trim() || null,
    };
    reviewCapability.mutate(
      { capabilityId: reviewing.id, payload },
      { onSuccess: () => setReviewing(null) },
    );
  };

  return (
    <div className="space-y-6">
      <NexusPageHeader
        crumbs={["Control", "MCP Registry", server.slug]}
        title={server.name}
        lede={server.description ?? `${server.transport} MCP server`}
        actions={
          <div className="flex items-center gap-2">
            <NexusBadge tone={statusTone}>{server.state}</NexusBadge>
            {server.state === "quarantined" ? (
              <button
                type="button"
                onClick={() => release.mutate()}
                disabled={release.isPending}
                className="glass-button rounded-xl px-3 py-2 text-xs font-semibold"
              >
                Release quarantine
              </button>
            ) : (
              <button
                type="button"
                onClick={() => {
                  const reason = window.prompt("Reason for quarantine");
                  if (reason?.trim()) quarantine.mutate({ reason: reason.trim() });
                }}
                disabled={quarantine.isPending}
                className="rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-600 dark:text-rose-300"
              >
                Quarantine
              </button>
            )}
          </div>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <NexusMetric
          label="Transport"
          value={server.transport.toUpperCase()}
          meta={server.health}
        />
        <NexusMetric
          label={approved_snapshot ? "Approved tools" : "Observed tools"}
          value={String(capabilities.length)}
          meta={approved_snapshot ? `${summary.dangerous_tool_count} high-risk` : "Awaiting approval"}
        />
        <NexusMetric
          label="Calls (14d)"
          value={String(calls)}
          meta={`${denials} denied`}
          tone={denials > 0 ? "negative" : "default"}
        />
        <NexusMetric
          label="Active grants"
          value={grants.isPending ? "—" : String((grants.data ?? []).filter((grant) => !grant.revoked_at).length)}
          meta={approved_snapshot ? "Pinned to approved capabilities" : "No approved snapshot"}
        />
      </div>

      {summary.drifted ? (
        <NexusCard pad className="border-amber-500/30 bg-amber-500/5">
          <div className="flex items-start gap-3">
            <ShieldAlert size={18} className="mt-0.5 text-amber-600 dark:text-amber-400" />
            <div className="min-w-0 flex-1">
              <h2 className="text-sm font-bold text-slate-900 dark:text-white">
                Capability drift requires review
              </h2>
              <p className="mt-1 text-xs text-slate-500">
                Added: {query.data.added_capability_names.join(", ") || "none"} · Removed:{" "}
                {query.data.removed_capability_names.join(", ") || "none"} · Changed:{" "}
                {query.data.changed_capability_names.join(", ") || "none"}
              </p>
            </div>
            {observed_snapshot ? (
              <button
                type="button"
                onClick={() => approve.mutate(observed_snapshot.id)}
                disabled={approve.isPending}
                className="glass-button-primary rounded-xl px-3 py-2 text-xs font-bold"
              >
                Approve reviewed snapshot
              </button>
            ) : null}
          </div>
        </NexusCard>
      ) : null}

      <div className="flex overflow-x-auto border-b border-slate-200 dark:border-white/10">
        {([
          ["overview", "Server overview", Server],
          ["tools", `Tools & capabilities (${capabilities.length})`, Wrench],
          ["access", `Effective access (${grants.data?.length ?? 0})`, LockKeyhole],
          ["client", "Client authentication", KeyRound],
        ] as const).map(([id, label, Icon]) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`flex items-center gap-2 border-b-2 px-4 py-3 text-xs font-semibold ${
              tab === id
                ? "border-indigo-500 text-indigo-700 dark:border-cyan-400 dark:text-cyan-300"
                : "border-transparent text-slate-500 hover:text-slate-900 dark:hover:text-white"
            }`}
          >
            <Icon size={14} /> {label}
          </button>
        ))}
      </div>

      {tab === "overview" ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <NexusCard pad>
            <h2 className="text-sm font-bold text-slate-900 dark:text-white">Server address</h2>
            <dl className="mt-4 space-y-3 text-xs">
              {[
                ["Registry ID", server.id],
                ["Stable slug", server.slug],
                ["Transport", server.transport],
                ["Endpoint", server.endpoint_url ?? server.command ?? "Not configured"],
                ["Trust tier", server.trust_tier],
                ["Environments", server.environments.join(", ")],
                ["Connection", server.connection_id ?? "No vaulted connection"],
              ].map(([label, value]) => (
                <div key={label} className="grid grid-cols-[110px_minmax(0,1fr)] gap-3 border-b border-slate-200 pb-2 last:border-0 dark:border-white/5">
                  <dt className="text-slate-500">{label}</dt>
                  <dd className="break-all font-mono text-slate-800 dark:text-slate-200">{value}</dd>
                </div>
              ))}
            </dl>
          </NexusCard>
          <NexusCard pad>
            <h2 className="text-sm font-bold text-slate-900 dark:text-white">Discovery state</h2>
            <dl className="mt-4 space-y-3 text-xs">
              {[
                ["Last discovered", server.last_discovered_at ? formatTableDate(server.last_discovered_at) : "Never"],
                ["Observed snapshot", observed_snapshot?.capability_digest_hex ?? "None"],
                ["Approved snapshot", approved_snapshot?.capability_digest_hex ?? "None"],
                ["Write approval", server.requires_approval_for_writes ? "Required" : "Not required"],
              ].map(([label, value]) => (
                <div key={label} className="grid grid-cols-[120px_minmax(0,1fr)] gap-3 border-b border-slate-200 pb-2 last:border-0 dark:border-white/5">
                  <dt className="text-slate-500">{label}</dt>
                  <dd className="break-all font-mono text-slate-800 dark:text-slate-200">{value}</dd>
                </div>
              ))}
            </dl>
            {!observed_snapshot ? (
              <p className="mt-4 rounded-xl border border-amber-500/20 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-300">
                No discovery result exists. This server cannot be approved or invoked.
              </p>
            ) : null}
          </NexusCard>
        </div>
      ) : null}

      {tab === "tools" ? (
        <NexusCard className="overflow-x-auto">
          <table className="min-w-[880px] text-left">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50/70 dark:border-white/10 dark:bg-white/[0.02]">
                {["Capability", "Kind", "Declared", "Verified risk", "Verified behavior", "Review", "Action"].map((heading) => (
                  <th key={heading} className="px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-slate-500">{heading}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-white/5">
              {capabilities.map((capability) => (
                <tr key={capability.id}>
                  <td className="px-4 py-3">
                    <p className="font-mono text-xs font-semibold text-slate-800 dark:text-slate-200">{capability.name}</p>
                    <p className="text-[10px] text-slate-500">{capability.title}</p>
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">{capability.kind}</td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {capability.declared_read_only === true ? "read only" : capability.declared_destructive === true ? "destructive" : "unspecified"}
                  </td>
                  <td className="px-4 py-3"><NexusBadge tone={capability.verified_risk === "critical" || capability.verified_risk === "high" ? "risk" : "default"}>{capability.verified_risk}</NexusBadge></td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {capability.verified_write ? "write" : "read"}{capability.verified_irreversible ? " · irreversible" : ""}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {capability.reviewed_at ? formatTableDate(capability.reviewed_at) : "Not reviewed"}
                  </td>
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      onClick={() => setReviewing(capability)}
                      className="glass-button rounded-lg px-2.5 py-1.5 text-[10px] font-semibold"
                    >
                      {capability.reviewed_at ? "Review again" : "Classify"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {capabilities.length === 0 ? <p className="p-8 text-center text-sm text-slate-500">No capabilities have been discovered.</p> : null}
        </NexusCard>
      ) : null}

      {tab === "access" ? (
        <NexusCard className="overflow-x-auto">
          <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4 dark:border-white/10">
            <div>
              <h2 className="text-sm font-bold text-slate-900 dark:text-white">
                Effective tool grants
              </h2>
              <p className="mt-1 text-xs text-slate-500">
                Grant an agent or a specific Platform Key; access remains pinned to the approved snapshot.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setGrantOpen(true)}
              disabled={!approved_snapshot}
              className="glass-button-primary flex shrink-0 items-center gap-2 rounded-xl px-3 py-2 text-xs font-bold disabled:opacity-50"
            >
              <Plus size={13} /> Add grant
            </button>
          </div>
          <table className="min-w-[820px] text-left">
            <thead>
              <tr className="border-b border-slate-200 bg-slate-50/70 dark:border-white/10 dark:bg-white/[0.02]">
                {["Subject", "Capability", "Environment", "Approval", "Snapshot", "Expires", "Action"].map((heading) => (
                  <th key={heading} className="px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-slate-500">{heading}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-white/5">
              {(grants.data ?? []).filter((grant) => !grant.revoked_at).map((grant) => (
                <tr key={grant.id}>
                  <td className="px-4 py-3 font-mono text-xs text-slate-700 dark:text-slate-300">{grant.subject_kind}:{grant.subject_id}</td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-500">{grant.capability_name ?? "Entire server"}</td>
                  <td className="px-4 py-3 text-xs text-slate-500">{grant.environments.join(", ")}</td>
                  <td className="px-4 py-3 text-xs text-slate-500">{grant.requires_approval ? "Required" : "No"}</td>
                  <td className="px-4 py-3 font-mono text-xs text-slate-500">{grant.pinned_snapshot_id ?? "Unpinned"}</td>
                  <td className="px-4 py-3 text-xs text-slate-500">{grant.expires_at ? formatTableDate(grant.expires_at) : "Never"}</td>
                  <td className="px-4 py-3">
                    <button
                      type="button"
                      onClick={() => revokeGrant.mutate(grant.id)}
                      disabled={revokeGrant.isPending}
                      className="rounded-lg px-2 py-1 text-[10px] font-semibold text-rose-600 hover:bg-rose-500/10"
                    >
                      Revoke
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!grants.isPending && (grants.data ?? []).filter((grant) => !grant.revoked_at).length === 0 ? (
            <p className="p-8 text-center text-sm text-slate-500">No active grants. Every tool call is denied.</p>
          ) : null}
        </NexusCard>
      ) : null}

      {tab === "client" ? (
        <NexusCard pad>
          <h2 className="text-sm font-bold text-slate-900 dark:text-white">Client authentication</h2>
          <p className="mt-2 max-w-3xl text-xs leading-relaxed text-slate-500">
            Clients authenticate with an AAP Platform Key scoped to <code>mcp:invoke</code>.
            The key identifies the project, environment, workload, and optional agent. Provider
            or MCP upstream credentials remain in a vaulted Connection and are never sent to the client.
          </p>
          <div className="mt-4 flex gap-2">
            <Link to="/platform-keys" className="glass-button-primary rounded-xl px-3 py-2 text-xs font-bold">
              Issue Platform Key
            </Link>
            <Link to="/admin/connections" className="glass-button rounded-xl px-3 py-2 text-xs font-semibold">
              Configure vaulted connection
            </Link>
          </div>
          <div className="mt-5 overflow-hidden rounded-xl border border-slate-200 dark:border-white/10">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-200 px-3 py-2 dark:border-white/10">
              <div>
                <p className="text-[10px] font-bold uppercase tracking-wider text-slate-500">
                  Cursor remote MCP configuration
                </p>
                <p className="mt-0.5 break-all font-mono text-[10px] text-slate-500">
                  {clientUrl || "Adapter base URL is not configured for this deployment"}
                </p>
              </div>
              <button
                type="button"
                onClick={() => void navigator.clipboard.writeText(cursorConfig)}
                className="glass-button flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[10px] font-semibold"
              >
                <Copy size={12} /> Copy JSON
              </button>
            </div>
            <pre className="overflow-x-auto bg-slate-950 p-4 text-[10px] leading-relaxed text-slate-200">
              <code>{cursorConfig}</code>
            </pre>
          </div>
          <p className="mt-4 rounded-xl border border-amber-500/20 bg-amber-500/10 p-3 text-xs text-amber-700 dark:text-amber-300">
            Set <code>AAP_PLATFORM_KEY</code> in the environment that launches Cursor; never
            paste the key into <code>mcp.json</code>. Registration, snapshot approval, a matching
            subject grant, adapter deployment, and the <code>mcp:invoke</code> scope must all be
            present or the call fails closed.
          </p>
        </NexusCard>
      ) : null}

      {grantOpen ? (
        <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <form
            onSubmit={submitGrant}
            className="glass-card w-full max-w-xl rounded-2xl bg-white p-6 dark:bg-slate-950"
          >
            <ModalTitle title="Grant MCP access" onClose={() => setGrantOpen(false)} />
            <div className="grid gap-4 sm:grid-cols-2">
              <label>
                <FieldLabel>Subject type</FieldLabel>
                <select
                  name="subject_kind"
                  value={grantSubjectKind}
                  onChange={(event) => setGrantSubjectKind(event.target.value as McpGrantCreate["subject_kind"])}
                  className="glass-input h-10 w-full rounded-xl px-3 text-xs"
                >
                  <option value="workload">Platform Key</option>
                  <option value="agent">Agent</option>
                  <option value="member">Person</option>
                  <option value="team">Team</option>
                </select>
              </label>
              <label>
                <FieldLabel>Subject ID</FieldLabel>
                {grantSubjectKind === "member" ? (
                  <select name="subject_id" required className="glass-input h-10 w-full rounded-xl px-3 text-xs">
                    <option value="">Choose a verified person</option>
                    {(members.data?.items ?? []).map((row) => (
                      <option key={row.member.id} value={row.member.id}>{row.member.display_name} · {row.member.email}</option>
                    ))}
                  </select>
                ) : grantSubjectKind === "team" ? (
                  <select name="subject_id" required className="glass-input h-10 w-full rounded-xl px-3 text-xs">
                    <option value="">Choose a team</option>
                    {(teams.data?.items ?? []).map((row) => (
                      <option key={row.team.id} value={row.team.id}>{row.team.name}</option>
                    ))}
                  </select>
                ) : grantSubjectKind === "workload" ? (
                  <select name="subject_id" required className="glass-input h-10 w-full rounded-xl px-3 text-xs">
                    <option value="">Choose a Platform Key</option>
                    {(credentials.data?.items ?? [])
                      .filter((credential) => !credential.revoked_at)
                      .map((credential) => (
                        <option key={credential.id} value={credential.id}>
                          {credential.name} · {credential.environment}
                        </option>
                      ))}
                  </select>
                ) : (
                  <input name="subject_id" required placeholder="Agent UUID" className="glass-input h-10 w-full rounded-xl px-3 text-xs" />
                )}
              </label>
              <label>
                <FieldLabel>Capability</FieldLabel>
                <select name="capability_name" defaultValue="" className="glass-input h-10 w-full rounded-xl px-3 text-xs">
                  <option value="">Entire approved server</option>
                  {capabilities.map((capability) => (
                    <option key={capability.id} value={capability.name}>{capability.name}</option>
                  ))}
                </select>
              </label>
              <label>
                <FieldLabel>Environment</FieldLabel>
                <select name="environment" defaultValue={server.environments[0] ?? "dev"} className="glass-input h-10 w-full rounded-xl px-3 text-xs">
                  {server.environments.map((environment) => (
                    <option key={environment} value={environment}>{environment}</option>
                  ))}
                </select>
              </label>
              <label className="sm:col-span-2">
                <FieldLabel>Reason</FieldLabel>
                <input name="reason" required placeholder="Business purpose and ticket reference" className="glass-input h-10 w-full rounded-xl px-3 text-xs" />
              </label>
              <label className="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-300 sm:col-span-2">
                <input name="requires_approval" type="checkbox" />
                Require human approval for every verified write invocation
              </label>
            </div>
            {createGrant.isError ? (
              <p className="mt-4 text-xs text-rose-600 dark:text-rose-300">
                {createGrant.error instanceof Error ? createGrant.error.message : "Grant failed"}
              </p>
            ) : null}
            <ModalActions
              pending={createGrant.isPending}
              action="Create pinned grant"
              onCancel={() => setGrantOpen(false)}
            />
          </form>
        </div>
      ) : null}

      {reviewing ? (
        <div className="fixed inset-0 z-[120] flex items-center justify-center bg-black/70 p-4 backdrop-blur-sm">
          <form
            onSubmit={submitReview}
            className="glass-card w-full max-w-xl rounded-2xl bg-white p-6 dark:bg-slate-950"
          >
            <ModalTitle title={`Classify ${reviewing.name}`} onClose={() => setReviewing(null)} />
            <p className="mb-4 text-xs leading-relaxed text-slate-500">
              Do not trust server annotations alone. Record the behavior verified from source,
              sandbox execution, and owner evidence before approving the snapshot.
            </p>
            <div className="space-y-4">
              <label>
                <FieldLabel>Verified risk</FieldLabel>
                <select name="verified_risk" defaultValue={reviewing.verified_risk} className="glass-input h-10 w-full rounded-xl px-3 text-xs">
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                  <option value="critical">Critical</option>
                </select>
              </label>
              <label className="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-300">
                <input name="verified_write" type="checkbox" defaultChecked={reviewing.verified_write} />
                Tool can modify external state
              </label>
              <label className="flex items-center gap-2 text-xs text-slate-700 dark:text-slate-300">
                <input name="verified_irreversible" type="checkbox" defaultChecked={reviewing.verified_irreversible} />
                Modification can be irreversible
              </label>
              <label>
                <FieldLabel>Review evidence</FieldLabel>
                <textarea name="review_note" required defaultValue={reviewing.review_note ?? ""} rows={3} className="glass-input w-full rounded-xl px-3 py-2 text-xs" />
              </label>
            </div>
            {reviewCapability.isError ? (
              <p className="mt-4 text-xs text-rose-600 dark:text-rose-300">
                {reviewCapability.error instanceof Error ? reviewCapability.error.message : "Review failed"}
              </p>
            ) : null}
            <ModalActions
              pending={reviewCapability.isPending}
              action="Save classification"
              onCancel={() => setReviewing(null)}
            />
          </form>
        </div>
      ) : null}

      <button type="button" onClick={() => navigate("/admin/mcp")} className="text-xs font-semibold text-indigo-600 hover:underline dark:text-cyan-400">
        ← Back to MCP Registry
      </button>
    </div>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <span className="mb-1 block text-[10px] font-bold uppercase tracking-wider text-slate-500">
      {children}
    </span>
  );
}

function ModalTitle({ title, onClose }: { title: string; onClose: () => void }) {
  return (
    <div className="mb-5 flex items-start justify-between gap-4">
      <h2 className="text-lg font-bold text-slate-900 dark:text-white">{title}</h2>
      <button type="button" onClick={onClose} aria-label="Close">
        <X size={18} className="text-slate-500" />
      </button>
    </div>
  );
}

function ModalActions({
  pending,
  action,
  onCancel,
}: {
  pending: boolean;
  action: string;
  onCancel: () => void;
}) {
  return (
    <div className="mt-6 flex justify-end gap-2">
      <button type="button" onClick={onCancel} className="glass-button rounded-xl px-4 py-2 text-xs font-semibold">
        Cancel
      </button>
      <button type="submit" disabled={pending} className="glass-button-primary rounded-xl px-4 py-2 text-xs font-bold disabled:opacity-50">
        {pending ? "Saving…" : action}
      </button>
    </div>
  );
}
