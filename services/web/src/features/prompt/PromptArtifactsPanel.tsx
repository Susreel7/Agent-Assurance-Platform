import { useState } from "react";
import { Link } from "react-router-dom";
import {
  useCreatePromptArtifact,
  useModules,
  usePromptArtifacts,
  useStableSuiteItems,
} from "@/api/suiteQueries";
import type { ArtifactCreate, ArtifactOut } from "@/api/types";
import { canConfigureModule } from "@/lib/suiteModules";
import { useSuiteProject } from "@/features/suite/useSuiteProject";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { MutationBanner } from "@/components/MutationBanner";
import { Panel } from "@/components/Panel";
import { Skeleton } from "@/components/Skeleton";
import { formatTableDate } from "@/lib/dates";

export default function PromptArtifactsPanel() {
  const { projectId } = useSuiteProject();
  const { data: manifest } = useModules();
  const canConfigure = canConfigureModule(manifest, "prompt");

  const query = usePromptArtifacts(projectId);
  const items = useStableSuiteItems(query.data?.items);
  const createMut = useCreatePromptArtifact(projectId);

  const [key, setKey] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [feedback, setFeedback] = useState<{ tone: "success" | "error"; message: string } | null>(
    null,
  );

  const columns: ColumnDef<ArtifactOut>[] = [
    {
      id: "key",
      header: "Key",
      accessor: (a) => (
        <Link to={`/prompt/artifacts/${encodeURIComponent(a.artifact_key)}`} className="hover:underline">
          {a.artifact_key}
        </Link>
      ),
    },
    { id: "kind", header: "Kind", accessor: (a) => a.kind },
    { id: "name", header: "Name", accessor: (a) => a.display_name || "—" },
    {
      id: "updated",
      header: "Updated",
      sortValue: (a) => a.updated_at,
      accessor: (a) => formatTableDate(a.updated_at),
    },
  ];

  if (query.isLoading) return <Skeleton height="14rem" />;

  if (query.isError) {
    return (
      <ErrorState
        message={query.error instanceof Error ? query.error.message : "Could not load artifacts"}
        onRetry={() => void query.refetch()}
      />
    );
  }

  const payload: ArtifactCreate = {
    artifact_key: key,
    kind: "prompt",
    display_name: displayName,
    description: "",
    tags: [],
  };

  return (
    <div className="space-y-4">
      {feedback ? (
        <MutationBanner {...feedback} onDismiss={() => setFeedback(null)} />
      ) : null}

      <Panel title="Artifacts">
        {items.length === 0 ? (
          <EmptyState title="No artifacts" description="Create a prompt artifact to begin versioning." />
        ) : (
          <DataTable data={items} columns={columns} rowKey={(a) => a.id} />
        )}
      </Panel>

      {canConfigure ? (
        <Panel title="Create artifact">
          <form
            className="grid max-w-lg gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              createMut.mutate(payload, {
                onSuccess: () => {
                  setFeedback({ tone: "success", message: "Artifact created." });
                  setKey("");
                  setDisplayName("");
                },
                onError: (err) =>
                  setFeedback({
                    tone: "error",
                    message: err instanceof Error ? err.message : "Create failed",
                  }),
              });
            }}
          >
            <label className="block text-sm">
              <span className="font-medium">Artifact key</span>
              <input
                className="mt-1 w-full rounded-md border border-line-200 px-2 py-1.5"
                value={key}
                onChange={(e) => setKey(e.target.value)}
                required
              />
            </label>
            <label className="block text-sm">
              <span className="font-medium">Display name</span>
              <input
                className="mt-1 w-full rounded-md border border-line-200 px-2 py-1.5"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
              />
            </label>
            <button
              type="submit"
              className="w-fit rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              disabled={createMut.isPending || !key.trim()}
            >
              {createMut.isPending ? "Creating…" : "Create"}
            </button>
          </form>
        </Panel>
      ) : null}
    </div>
  );
}
