import { useState } from "react";
import AlertTriangle from "lucide-react/dist/esm/icons/triangle-alert";
import Database from "lucide-react/dist/esm/icons/database";
import Key from "lucide-react/dist/esm/icons/key";
import Network from "lucide-react/dist/esm/icons/network";
import Shield from "lucide-react/dist/esm/icons/shield";
import Sliders from "lucide-react/dist/esm/icons/sliders";
import Zap from "lucide-react/dist/esm/icons/zap";
import { Link } from "react-router-dom";
import { useAuditDigest, useConnections, useMcpServers } from "@/api/platformQueries";
import {
  NexusBadge,
  NexusCard,
  NexusMetric,
  NexusPageHeader,
} from "@/components/NexusUI";

type OperatingMode = "standard" | "restricted" | "read_only" | "emergency_pause";

export default function ControlCenterScreen() {
  const [mode, setMode] = useState<OperatingMode>("standard");
  const servers = useMcpServers({ limit: 100 });
  const connections = useConnections({ limit: 100 });
  const audit = useAuditDigest(7);

  const serverRows = servers.data?.items ?? [];
  const connectionRows = connections.data?.items ?? [];
  const drifted = serverRows.filter((row) => row.drifted).length;
  const healthyConnections = connectionRows.filter(
    (row) => row.connection.status === "healthy",
  ).length;

  const modes: Array<{ key: OperatingMode; label: string }> = [
    { key: "standard", label: "Standard" },
    { key: "restricted", label: "Strict HITL" },
    { key: "read_only", label: "Read-Only" },
    { key: "emergency_pause", label: "Pause" },
  ];

  return (
    <div className="space-y-6">
      <NexusPageHeader
        crumbs={["Control", "Control center"]}
        title="Enterprise Control Center"
        lede="Unified command center for model routing, MCP guardrails, connection health and runtime enforcement across human and agent workloads."
        actions={
          <>
            <Link
              to="/router/simulate"
              className="glass-button flex items-center gap-1.5 rounded-xl px-3.5 py-2 text-xs font-semibold hover:no-underline"
            >
              <Zap size={14} className="text-amber-500" />
              Simulate policy
            </Link>
            <Link
              to="/admin/mcp"
              className="glass-button-primary flex items-center gap-1.5 rounded-xl px-4 py-2 text-xs font-bold shadow hover:no-underline"
            >
              <Network size={14} />
              MCP Registry
            </Link>
          </>
        }
      />

      <div className="flex flex-col items-start justify-between gap-4 rounded-2xl border border-slate-200 bg-slate-100/60 p-4 backdrop-blur-xl md:flex-row md:items-center dark:border-white/10 dark:bg-white/[0.03]">
        <div className="flex items-center gap-3">
          <span
            className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-white shadow-sm ${
              mode === "standard"
                ? "bg-emerald-500"
                : mode === "restricted"
                  ? "bg-amber-500"
                  : mode === "read_only"
                    ? "bg-blue-600"
                    : "animate-pulse bg-rose-600"
            }`}
          >
            <Shield size={20} />
          </span>
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-sm font-bold text-slate-900 dark:text-white">
                Platform operating mode:
              </h2>
              <span className="font-mono text-xs font-bold capitalize text-slate-900 dark:text-white">
                {mode.replace("_", " ")}
              </span>
              <NexusBadge tone={mode === "standard" ? "ok" : "warn"}>
                {mode === "standard" ? "Enforcing policy" : "Elevated caution"}
              </NexusBadge>
            </div>
            <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">
              Runtime posture across {serverRows.length} MCP servers and{" "}
              {connectionRows.length} provider connections.
            </p>
          </div>
        </div>
        <div className="flex shrink-0 items-center gap-1.5 rounded-xl bg-slate-200/60 p-1 dark:bg-white/10">
          {modes.map((item) => (
            <button
              key={item.key}
              type="button"
              onClick={() => setMode(item.key)}
              className={`rounded-lg px-2.5 py-1.5 text-xs font-semibold transition-all ${
                mode === item.key
                  ? item.key === "emergency_pause"
                    ? "bg-rose-600 text-white shadow-sm"
                    : "bg-white text-slate-900 shadow-sm dark:bg-white/20 dark:text-white"
                  : "text-slate-500 hover:text-slate-900 dark:hover:text-white"
              }`}
            >
              {item.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <NexusMetric
          label="MCP servers"
          value={servers.isPending ? "—" : String(serverRows.length)}
          meta={`${drifted} drifted · approved snapshots pinned`}
          tone={drifted > 0 ? "negative" : "positive"}
        />
        <NexusMetric
          label="Provider connections"
          value={connections.isPending ? "—" : String(connectionRows.length)}
          meta={`${healthyConnections} healthy`}
          tone={
            connectionRows.length > 0 && healthyConnections === connectionRows.length
              ? "positive"
              : "default"
          }
        />
        <NexusMetric
          label="Policy denials"
          value={audit.isPending ? "—" : (audit.data?.denied_count ?? 0).toLocaleString()}
          meta="Last 7 days · content-free audit"
        />
        <NexusMetric
          label="Critical decisions"
          value={audit.isPending ? "—" : (audit.data?.critical_count ?? 0).toLocaleString()}
          meta="Require security attention"
          tone={(audit.data?.critical_count ?? 0) > 0 ? "negative" : "positive"}
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <NexusCard className="lg:col-span-2">
          <div className="flex items-center justify-between border-b border-slate-200 p-5 dark:border-white/10">
            <div>
              <h2 className="text-base font-bold text-slate-900 dark:text-white">
                Governed resource matrix
              </h2>
              <p className="mt-1 text-xs text-slate-500">
                Separate registries, one effective enforcement decision.
              </p>
            </div>
            <NexusBadge tone="ok">Live contracts</NexusBadge>
          </div>
          <div className="grid gap-3 p-5 sm:grid-cols-2">
            {[
              {
                icon: Sliders,
                title: "Models & routing",
                text: "Catalogues, deployments, fallback and residency policy",
                to: "/model-routing",
              },
              {
                icon: Network,
                title: "MCP registry",
                text: "Immutable capability snapshots, access and quarantine",
                to: "/admin/mcp",
              },
              {
                icon: Database,
                title: "Provider connections",
                text: "Credential references, health and rotation",
                to: "/admin/connections",
              },
              {
                icon: Key,
                title: "Platform Keys",
                text: "Revocable workload identity for agents and SDKs",
                to: "/platform-keys",
              },
            ].map((item) => (
              <Link
                key={item.title}
                to={item.to}
                className="glass-card glass-card-hover flex items-start gap-3 rounded-xl p-4 hover:no-underline"
              >
                <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-500/10 text-indigo-600 dark:text-cyan-400">
                  <item.icon size={17} />
                </span>
                <span>
                  <span className="block text-sm font-bold text-slate-900 dark:text-white">
                    {item.title}
                  </span>
                  <span className="mt-1 block text-xs leading-relaxed text-slate-500 dark:text-slate-400">
                    {item.text}
                  </span>
                </span>
              </Link>
            ))}
          </div>
        </NexusCard>

        <NexusCard pad>
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-base font-bold text-slate-900 dark:text-white">
              Enforcement posture
            </h2>
            <NexusBadge tone={drifted > 0 ? "warn" : "ok"}>
              {drifted > 0 ? "Attention" : "Healthy"}
            </NexusBadge>
          </div>
          <div className="space-y-4">
            <div className="flex items-start gap-3 border-b border-slate-200 pb-4 dark:border-white/5">
              <AlertTriangle size={16} className="mt-0.5 text-amber-500" />
              <div>
                <div className="text-sm font-semibold text-slate-900 dark:text-white">
                  {drifted} capability snapshots drifted
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  Existing pinned grants do not widen automatically.
                </div>
              </div>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-slate-500">Gateway path</span>
              <span className="font-bold text-slate-900 dark:text-white">Online</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-slate-500">Audit retention</span>
              <span className="font-bold text-slate-900 dark:text-white">Partitioned</span>
            </div>
            <div className="flex justify-between text-sm">
              <span className="text-slate-500">Secret storage</span>
              <span className="font-bold text-slate-900 dark:text-white">References only</span>
            </div>
          </div>
        </NexusCard>
      </div>
    </div>
  );
}
