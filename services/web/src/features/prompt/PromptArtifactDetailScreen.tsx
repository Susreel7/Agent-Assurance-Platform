import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  useCreatePromptRevision,
  useDiffPromptRevisions,
  useModules,
  usePromotePromptLabel,
  usePromptArtifact,
  usePromptRevision,
  usePromptRevisions,
  useStableSuiteItems,
} from "@/api/suiteQueries";
import type { RevisionCreate } from "@/api/types";
import { canConfigureModule } from "@/lib/suiteModules";

function parseJsonObject(raw: string): RevisionCreate["content"] | null {
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) return null;
    return parsed as RevisionCreate["content"];
  } catch {
    return null;
  }
}
import { useSuiteProject } from "@/features/suite/useSuiteProject";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { MutationBanner } from "@/components/MutationBanner";
import { Panel } from "@/components/Panel";
import { Skeleton } from "@/components/Skeleton";
import { Tabs } from "@/components/Tabs";

export default function PromptArtifactDetailScreen() {
  const { artifactKey = "" } = useParams();
  const decodedKey = decodeURIComponent(artifactKey);
  const { projectId } = useSuiteProject();
  const { data: manifest } = useModules();
  const canConfigure = canConfigureModule(manifest, "prompt");

  const artifactQuery = usePromptArtifact(projectId, decodedKey);
  const revisionsQuery = usePromptRevisions(projectId, decodedKey);
  const revisions = useStableSuiteItems(revisionsQuery.data?.items);

  const [tab, setTab] = useState("revisions");
  const [contentJson, setContentJson] = useState('{"messages":[{"role":"user","content":"Hello"}]}');
  const [fromRev, setFromRev] = useState("");
  const [toRev, setToRev] = useState("");
  const [labelName, setLabelName] = useState("production");
  const [promoteRev, setPromoteRev] = useState("");
  const [selectedRev, setSelectedRev] = useState("");
  const [feedback, setFeedback] = useState<{ tone: "success" | "error"; message: string } | null>(
    null,
  );

  const createRevMut = useCreatePromptRevision(projectId, decodedKey);
  const diffMut = useDiffPromptRevisions(projectId, decodedKey);
  const promoteMut = usePromotePromptLabel(projectId, decodedKey);
  const revisionDetailQuery = usePromptRevision(
    projectId,
    decodedKey,
    selectedRev,
  );

  if (artifactQuery.isLoading) return <Skeleton height="16rem" />;

  if (artifactQuery.isError || !artifactQuery.data) {
    return (
      <ErrorState
        message={
          artifactQuery.error instanceof Error ? artifactQuery.error.message : "Artifact not found"
        }
        onRetry={() => void artifactQuery.refetch()}
      />
    );
  }

  const artifact = artifactQuery.data;

  return (
    <div className="space-y-4">
      <p className="text-sm">
        <Link to="/prompt" className="text-info-fg hover:underline">
          ← Artifacts
        </Link>
      </p>

      {feedback ? (
        <MutationBanner {...feedback} onDismiss={() => setFeedback(null)} />
      ) : null}

      <header>
        <h2 className="text-lg font-semibold text-ink-900">{artifact.display_name || artifact.artifact_key}</h2>
        <p className="text-sm text-ink-600">{artifact.kind} · {artifact.artifact_key}</p>
      </header>

      <Tabs
        ariaLabel="Artifact workflows"
        activeId={tab}
        onChange={setTab}
        tabs={[
          { id: "revisions", label: "Revisions" },
          { id: "create", label: "Create revision" },
          { id: "diff", label: "Diff" },
          { id: "promote", label: "Promote label" },
        ]}
      />

      {tab === "revisions" ? (
        <Panel title="Revision history">
          {revisions.length === 0 ? (
            <EmptyState title="No revisions" description="Add a revision to store prompt content." />
          ) : (
            <ul className="space-y-2 text-sm">
              {revisions.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    className="font-mono-data text-xs text-info-fg underline"
                    onClick={() => setSelectedRev(r.id)}
                  >
                    #{r.revision_number} · {r.id.slice(0, 8)}
                  </button>
                  {r.is_draft ? <span className="text-warn-fg">draft</span> : null}
                </li>
              ))}
            </ul>
          )}
          {selectedRev && revisionDetailQuery.data ? (
            <pre className="mt-4 max-h-64 overflow-auto rounded-md bg-bg-hover p-3 text-xs">
              {JSON.stringify(revisionDetailQuery.data.content, null, 2)}
            </pre>
          ) : null}
        </Panel>
      ) : null}

      {tab === "create" && canConfigure ? (
        <Panel title="New revision">
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              const content = parseJsonObject(contentJson);
              if (!content) {
                setFeedback({ tone: "error", message: "Content must be a JSON object." });
                return;
              }
              createRevMut.mutate(
                { content, is_draft: false },
                {
                  onSuccess: () =>
                    setFeedback({ tone: "success", message: "Revision created." }),
                  onError: (err) =>
                    setFeedback({
                      tone: "error",
                      message: err instanceof Error ? err.message : "Create failed",
                    }),
                },
              );
            }}
          >
            <textarea
              className="h-40 w-full rounded-md border border-line-200 p-2 font-mono-data text-xs"
              value={contentJson}
              onChange={(e) => setContentJson(e.target.value)}
            />
            <button
              type="submit"
              className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              disabled={createRevMut.isPending}
            >
              {createRevMut.isPending ? "Saving…" : "Save revision"}
            </button>
          </form>
        </Panel>
      ) : null}

      {tab === "diff" ? (
        <Panel title="Compare revisions">
          <form
            className="grid gap-3 md:grid-cols-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (!fromRev || !toRev) return;
              diffMut.mutate(
                { from_revision_id: fromRev, to_revision_id: toRev, mode: "structured" },
                {
                  onSuccess: () =>
                    setFeedback({ tone: "success", message: "Diff loaded below." }),
                  onError: (err) =>
                    setFeedback({
                      tone: "error",
                      message: err instanceof Error ? err.message : "Diff failed",
                    }),
                },
              );
            }}
          >
            <label className="text-sm">
              From revision ID
              <input
                className="mt-1 w-full rounded-md border border-line-200 px-2 py-1.5 font-mono-data text-xs"
                value={fromRev}
                onChange={(e) => setFromRev(e.target.value)}
              />
            </label>
            <label className="text-sm">
              To revision ID
              <input
                className="mt-1 w-full rounded-md border border-line-200 px-2 py-1.5 font-mono-data text-xs"
                value={toRev}
                onChange={(e) => setToRev(e.target.value)}
              />
            </label>
            <button type="submit" className="md:col-span-2 w-fit rounded-md border border-line-200 px-4 py-2 text-sm">
              Run diff
            </button>
          </form>
          {diffMut.data ? (
            <pre className="mt-4 max-h-64 overflow-auto rounded-md bg-bg-hover p-3 text-xs">
              {JSON.stringify(diffMut.data, null, 2)}
            </pre>
          ) : null}
        </Panel>
      ) : null}

      {tab === "promote" && canConfigure ? (
        <Panel title="Promote label">
          <form
            className="grid max-w-md gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              promoteMut.mutate(
                { label_name: labelName, revision_id: promoteRev },
                {
                  onSuccess: () =>
                    setFeedback({ tone: "success", message: `Label ${labelName} updated.` }),
                  onError: (err) =>
                    setFeedback({
                      tone: "error",
                      message: err instanceof Error ? err.message : "Promote failed",
                    }),
                },
              );
            }}
          >
            <label className="text-sm">
              Label
              <input
                className="mt-1 w-full rounded-md border border-line-200 px-2 py-1.5"
                value={labelName}
                onChange={(e) => setLabelName(e.target.value)}
              />
            </label>
            <label className="text-sm">
              Revision ID
              <input
                className="mt-1 w-full rounded-md border border-line-200 px-2 py-1.5 font-mono-data text-xs"
                value={promoteRev}
                onChange={(e) => setPromoteRev(e.target.value)}
                required
              />
            </label>
            <button
              type="submit"
              className="w-fit rounded-md bg-accent px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
              disabled={promoteMut.isPending}
            >
              Promote
            </button>
          </form>
        </Panel>
      ) : null}
    </div>
  );
}
