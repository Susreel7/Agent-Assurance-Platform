import Copy from "lucide-react/dist/esm/icons/copy";
import ExternalLink from "lucide-react/dist/esm/icons/external-link";
import Route from "lucide-react/dist/esm/icons/route";
import Server from "lucide-react/dist/esm/icons/server";
import ShieldCheck from "lucide-react/dist/esm/icons/shield-check";
import { Link } from "react-router-dom";
import { useModelCatalogue, useModelRoutingOverview } from "@/api/queries";
import {
  NexusBadge,
  NexusCard,
  NexusMetric,
  NexusPageHeader,
} from "@/components/NexusUI";
import { formatTableDate } from "@/lib/dates";
import { titleCaseSnake } from "@/lib/formatters";

const PYTHON_EXAMPLE = `import os
from openai import OpenAI

client = OpenAI(
    base_url=os.environ["AAP_GATEWAY_URL"].rstrip("/") + "/v1",
    api_key=os.environ["AAP_PLATFORM_KEY"],
    default_headers={
        "X-AAP-Agent-Id": os.environ["AAP_AGENT_ID"],
        "X-AAP-Environment": os.getenv("AAP_ENVIRONMENT", "production"),
        "X-AAP-Data-Class": os.getenv("AAP_DATA_CLASS", "internal"),
    },
)

response = client.chat.completions.create(
    model="your-approved-route-alias",
    messages=[{"role": "user", "content": "Hello"}],
)`;

export default function ModelRoutingScreen() {
  const overviewQuery = useModelRoutingOverview();
  const catalogueQuery = useModelCatalogue({ limit: "100" });
  const catalogue = catalogueQuery.data?.items ?? [];
  const overview = overviewQuery.data;
  const classified = catalogue.filter((entry) => entry.classification_state === "classified");
  const regions = new Set(classified.map((entry) => entry.primary_region));

  return (
    <div className="space-y-6">
      <NexusPageHeader
        crumbs={["Control", "Models & routing"]}
        title="Models & routing"
        lede="The gateway is the only supported model egress path. It authenticates the workload, scans outbound data, selects an approved deployment, resolves provider credentials server-side, and records the result."
        actions={
          <Link
            to="/router"
            className="glass-button-primary flex items-center gap-2 rounded-xl px-4 py-2 text-xs font-bold"
          >
            <Route size={14} />
            Configure deployments
          </Link>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <NexusMetric
          label="Classified models"
          value={catalogueQuery.isPending ? "—" : String(classified.length)}
          meta={`${catalogueQuery.data?.unclassified_count ?? 0} fail-closed`}
        />
        <NexusMetric
          label="Approved regions"
          value={catalogueQuery.isPending ? "—" : String(regions.size)}
          meta="Operator assertions"
        />
        <NexusMetric
          label="Recent denials"
          value={overviewQuery.isPending ? "—" : String(overview?.recent_denials.length ?? 0)}
          meta="Gateway policy"
          tone={(overview?.recent_denials.length ?? 0) > 0 ? "negative" : "default"}
        />
        <NexusMetric
          label="Drift findings"
          value={overviewQuery.isPending ? "—" : String(overview?.drift_findings.length ?? 0)}
          meta="Observed versus approved"
          tone={(overview?.drift_findings.length ?? 0) > 0 ? "negative" : "positive"}
        />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <NexusCard pad>
          <div className="flex items-start gap-3">
            <ShieldCheck size={18} className="mt-0.5 shrink-0 text-indigo-600 dark:text-cyan-400" />
            <div>
              <h2 className="text-sm font-bold text-slate-900 dark:text-white">
                Enforcement boundary
              </h2>
              <p className="mt-1 text-xs leading-relaxed text-slate-500">
                {overview?.observation_note ??
                  "Loading model routing enforcement status from the control plane…"}
              </p>
            </div>
          </div>
        </NexusCard>
        <NexusCard pad>
          <div className="flex items-start gap-3">
            <Server size={18} className="mt-0.5 shrink-0 text-indigo-600 dark:text-cyan-400" />
            <div>
              <h2 className="text-sm font-bold text-slate-900 dark:text-white">
                Provider credentials stay server-side
              </h2>
              <p className="mt-1 text-xs leading-relaxed text-slate-500">
                A Platform Key identifies your workload. It is not an OpenAI, Anthropic,
                Azure, Bedrock, Gemini, or Vertex credential. Provider secrets are resolved
                from vaulted Connections only after routing policy allows the request.
              </p>
              <div className="mt-3 flex gap-2">
                <Link to="/platform-keys" className="text-xs font-semibold text-indigo-600 hover:underline dark:text-cyan-400">
                  Platform Keys
                </Link>
                <Link to="/admin/connections" className="text-xs font-semibold text-indigo-600 hover:underline dark:text-cyan-400">
                  Connections
                </Link>
              </div>
            </div>
          </div>
        </NexusCard>
      </div>

      <NexusCard>
        <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 px-5 py-4 dark:border-white/10">
          <div>
            <h2 className="text-sm font-bold text-slate-900 dark:text-white">
              Connect a Python agent
            </h2>
            <p className="mt-1 text-xs text-slate-500">
              OpenAI-compatible client; the route alias, not a provider model ID, selects policy.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void navigator.clipboard.writeText(PYTHON_EXAMPLE)}
            className="glass-button flex items-center gap-2 rounded-xl px-3 py-2 text-xs font-semibold"
          >
            <Copy size={13} /> Copy
          </button>
        </div>
        <pre className="overflow-x-auto p-5 text-[11px] leading-relaxed text-slate-700 dark:text-slate-300">
          <code>{PYTHON_EXAMPLE}</code>
        </pre>
      </NexusCard>

      <div className="grid gap-6 lg:grid-cols-2">
        <NexusCard>
          <div className="border-b border-slate-200 px-5 py-4 dark:border-white/10">
            <h2 className="text-sm font-bold text-slate-900 dark:text-white">
              Recent gateway denials
            </h2>
          </div>
          <ul className="divide-y divide-slate-200 dark:divide-white/5">
            {(overview?.recent_denials ?? []).map((denial) => (
              <li
                key={`${denial.occurred_at}-${denial.reason_code}`}
                className="px-5 py-3"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="font-mono text-xs font-semibold text-slate-800 dark:text-slate-200">
                    {denial.reason_code}
                  </span>
                  <NexusBadge tone="risk">{titleCaseSnake(String(denial.outcome))}</NexusBadge>
                </div>
                <p className="mt-1 text-[10px] text-slate-500">
                  {denial.rule_id} · {formatTableDate(String(denial.occurred_at))}
                  {denial.agent_id ? ` · agent ${denial.agent_id}` : ""}
                </p>
              </li>
            ))}
            {(overview?.recent_denials.length ?? 0) === 0 ? (
              <li className="px-5 py-8 text-center text-xs text-slate-500">No recent denials.</li>
            ) : null}
          </ul>
        </NexusCard>
        <NexusCard pad>
          <h2 className="text-sm font-bold text-slate-900 dark:text-white">What region evidence means</h2>
          <p className="mt-2 text-xs leading-relaxed text-slate-500">
            The catalogue is an operator assertion backed by provider contracts and deployment
            configuration. It is not cryptographic proof of physical execution. Strong assurance
            also needs private regional endpoints, egress allowlists, DNS and firewall evidence,
            provider response metadata, contractual no-reroute terms, and drift alerts when observed
            telemetry disagrees.
          </p>
          <Link to="/router" className="mt-4 inline-flex items-center gap-1 text-xs font-semibold text-indigo-600 hover:underline dark:text-cyan-400">
            Inspect signed route configuration <ExternalLink size={12} />
          </Link>
        </NexusCard>
      </div>

      <NexusCard className="overflow-x-auto">
        <div className="border-b border-slate-200 px-5 py-4 dark:border-white/10">
          <h2 className="text-sm font-bold text-slate-900 dark:text-white">Live model catalogue</h2>
          <p className="mt-1 text-xs text-slate-500">
            {catalogueQuery.data?.unclassified_count ?? 0} unclassified; production routes fail closed.
          </p>
        </div>
        <table className="min-w-[900px] text-left">
          <thead>
            <tr className="border-b border-slate-200 bg-slate-50/70 dark:border-white/10 dark:bg-white/[0.02]">
              {["Model", "Hosting", "Jurisdiction", "Data handling", "Cross-border", "Classification"].map((heading) => (
                <th key={heading} className="px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-slate-500">{heading}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-200 dark:divide-white/5">
            {catalogue.map((entry) => (
              <tr key={entry.id}>
                <td className="px-4 py-3 font-mono text-xs font-semibold text-slate-800 dark:text-slate-200">{entry.provider}/{entry.model_id}</td>
                <td className="px-4 py-3 text-xs text-slate-500">{entry.primary_region} · {titleCaseSnake(entry.hosting_mode)}</td>
                <td className="px-4 py-3 text-xs text-slate-500">{entry.jurisdiction}</td>
                <td className="px-4 py-3 text-xs text-slate-500">{titleCaseSnake(entry.data_handling_terms)}</td>
                <td className="px-4 py-3"><NexusBadge tone={entry.cross_border_ok ? "warn" : "ok"}>{entry.cross_border_ok ? "permitted" : "restricted"}</NexusBadge></td>
                <td className="px-4 py-3"><NexusBadge tone={entry.classification_state === "classified" ? "ok" : "risk"}>{entry.classification_state}</NexusBadge></td>
              </tr>
            ))}
          </tbody>
        </table>
        {!catalogueQuery.isPending && catalogue.length === 0 ? (
          <p className="p-8 text-center text-sm text-slate-500">No models are catalogued.</p>
        ) : null}
      </NexusCard>
    </div>
  );
}
