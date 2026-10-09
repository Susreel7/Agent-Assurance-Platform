import { Link, useParams } from "react-router-dom";
import { useAgent, useAgentVersion } from "@/api/queries";
import { Panel } from "@/components/Panel";
import { ErrorState } from "@/components/ErrorState";
import { Skeleton } from "@/components/Skeleton";
import { Digest } from "@/components/Digest";
import { RelativeTime } from "@/components/RelativeTime";
import { Principal } from "@/components/Principal";
import { Urn } from "@/components/Urn";
import { AgentBomTab } from "./AgentBomTab";

export default function AgentVersionScreen() {
  const { agentId = "", versionId = "" } = useParams();
  const agentQuery = useAgent(agentId);
  const versionQuery = useAgentVersion(agentId, versionId);

  const version = versionQuery.data;
  const agent = agentQuery.data;

  if (versionQuery.isLoading || agentQuery.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton height="2rem" width="40%" />
        <Skeleton height="12rem" />
      </div>
    );
  }

  if (versionQuery.isError || !version) {
    return (
      <ErrorState
        message={versionQuery.error instanceof Error ? versionQuery.error.message : "Version not found"}
        onRetry={() => void versionQuery.refetch()}
      />
    );
  }

  return (
    <div className="space-y-4">
      <header>
        <p className="text-table">
          <Link to={`/agents/${agentId}`} className="text-info-fg hover:underline">
            {agent?.display_name ?? "Agent"}
          </Link>
          {agent ? (
            <>
              {" · "}
              <Urn value={agent.urn} />
            </>
          ) : null}
        </p>
        <h1 className="text-lg font-semibold font-mono-data tabular-nums">
          Version {version.semver}
          {version.is_baseline ? (
            <span className="ml-2 text-sm font-normal text-ink-400">baseline</span>
          ) : null}
        </h1>
        <p className="mt-2 text-table text-ink-600">
          Published <RelativeTime iso={version.published_at} mode="table" /> by{" "}
          <Principal principalId={version.published_by} />
        </p>
      </header>

      <Panel title="Descriptor">
        <dl className="grid gap-2 text-table sm:grid-cols-2 mb-4">
          <div>
            <dt className="text-ink-400">Digest</dt>
            <dd>
              <Digest value={version.descriptor_digest} max={48} />
            </dd>
          </div>
          <div>
            <dt className="text-ink-400">Runtime</dt>
            <dd>
              {version.runtime_framework ?? "—"} / {version.runtime_language ?? "—"}
            </dd>
          </div>
          <div>
            <dt className="text-ink-400">VCS</dt>
            <dd className="font-mono-data text-xs">
              {version.vcs_provider}/{version.vcs_repo}@{version.vcs_ref}
            </dd>
          </div>
        </dl>
        <details>
          <summary className="cursor-pointer text-sm text-ink-600 hover:text-ink-900">
            Descriptor document (JSON)
          </summary>
          <pre className="mt-2 max-h-80 overflow-auto rounded-sm border border-line-200 bg-bg-sunk p-3 font-mono-data text-xs">
            {JSON.stringify(version.descriptor_json, null, 2)}
          </pre>
        </details>
      </Panel>

      <Panel title="Bill of materials for this version">
        <AgentBomTab agentId={agentId} versionId={versionId} />
      </Panel>
    </div>
  );
}
