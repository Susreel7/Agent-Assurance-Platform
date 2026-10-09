import { useEffect, useRef, useState } from "react";
import { useSuiteProject } from "@/features/suite/useSuiteProject";
import { EmptyState } from "@/components/EmptyState";
import { NexusPageHeader } from "@/components/NexusUI";
import { Panel } from "@/components/Panel";

const API_BASE = import.meta.env.VITE_API_BASE ?? "";

export default function ObserveLiveTailPanel() {
  const { projectId } = useSuiteProject();
  const [lines, setLines] = useState<string[]>([]);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => abortRef.current?.abort();
  }, []);

  async function startTail() {
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setRunning(true);
    setError(null);
    setLines([]);

    const url = new URL(
      `${API_BASE}/v1/observe/projects/${projectId}/live-tail`,
      window.location.origin,
    );
    const headers: Record<string, string> = { Accept: "text/event-stream" };

    try {
      const res = await fetch(url.toString(), {
        headers,
        credentials: "same-origin",
        signal: controller.signal,
      });
      if (!res.ok || !res.body) {
        setError(res.statusText || "Stream failed");
        setRunning(false);
        return;
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split("\n");
        buffer = parts.pop() ?? "";
        for (const line of parts) {
          if (line.startsWith("data:")) {
            setLines((prev) => [...prev.slice(-199), line.slice(5).trim()]);
          }
        }
      }
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        setError(err instanceof Error ? err.message : "Stream error");
      }
    } finally {
      setRunning(false);
    }
  }

  function stopTail() {
    abortRef.current?.abort();
    setRunning(false);
  }

  return (
    <div className="space-y-6">
      <NexusPageHeader
        crumbs={["Activity", "Live activity"]}
        title="Live activity"
        lede="A tenant-scoped stream of execution, observation, and event lifecycle records as Observe accepts them."
      />
      <Panel title="Live event stream" explain="Server-sent events from the Observe query service.">
      <div className="mb-4 flex gap-2">
        {!running ? (
          <button
            type="button"
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white"
            onClick={() => void startTail()}
          >
            Connect
          </button>
        ) : (
          <button
            type="button"
            className="rounded-md border border-line-200 px-4 py-2 text-sm"
            onClick={stopTail}
          >
            Stop
          </button>
        )}
      </div>
      {error ? <p className="mb-3 text-sm text-risk-fg">{error}</p> : null}
      {lines.length === 0 && !running ? (
        <EmptyState title="Not connected" description="Connect to stream recent trace events." />
      ) : (
        <pre className="max-h-96 overflow-y-auto rounded-md bg-bg-hover p-3 text-xs text-ink-800">
          {lines.join("\n") || (running ? "Waiting for events…" : "")}
        </pre>
      )}
      </Panel>
    </div>
  );
}
