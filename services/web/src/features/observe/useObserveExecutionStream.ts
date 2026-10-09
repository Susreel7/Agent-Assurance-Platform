import { useEffect, useRef, useState } from "react";
import type { ObserveLiveEvent, ObserveLifecycle } from "@/api/types";
const API_BASE = import.meta.env.VITE_API_BASE ?? "";

type ConnectionState = "idle" | "connecting" | "connected" | "reconnecting" | "error";

type SseMessage = {
  id: string | null;
  event: string;
  data: string;
};

function parseMessage(block: string): SseMessage | null {
  let id: string | null = null;
  let event = "message";
  const data: string[] = [];
  for (const line of block.split(/\r?\n/)) {
    if (!line || line.startsWith(":")) continue;
    const separator = line.indexOf(":");
    const field = separator >= 0 ? line.slice(0, separator) : line;
    const value = separator >= 0 ? line.slice(separator + 1).replace(/^ /, "") : "";
    if (field === "id") id = value;
    if (field === "event") event = value;
    if (field === "data") data.push(value);
  }
  return data.length > 0 ? { id, event, data: data.join("\n") } : null;
}

function wait(delayMs: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    const timeout = window.setTimeout(resolve, delayMs);
    signal.addEventListener(
      "abort",
      () => {
        window.clearTimeout(timeout);
        resolve();
      },
      { once: true },
    );
  });
}

function cursorKey(projectId: string, traceId: string): string {
  return `observe-live-cursor:${projectId}:${traceId}`;
}

export function useObserveExecutionStream(
  projectId: string,
  traceId: string,
  enabled: boolean,
): {
  events: ObserveLiveEvent[];
  connection: ConnectionState;
  error: string | null;
} {
  const [events, setEvents] = useState<ObserveLiveEvent[]>([]);
  const [connection, setConnection] = useState<ConnectionState>(
    enabled ? "connecting" : "idle",
  );
  const [error, setError] = useState<string | null>(null);
  const cursorRef = useRef<string | null>(null);

  useEffect(() => {
    if (!enabled || !projectId || !traceId) return;
    const controller = new AbortController();
    const storageKey = cursorKey(projectId, traceId);
    try {
      cursorRef.current = window.sessionStorage.getItem(storageKey);
    } catch {
      cursorRef.current = null;
    }

    const connect = async () => {
      let retryDelay = 500;
      while (!controller.signal.aborted) {
        const url = new URL(
          `${API_BASE}/v1/observe/projects/${projectId}/live-tail`,
          window.location.origin,
        );
        url.searchParams.set("trace_id", traceId);
        if (cursorRef.current) url.searchParams.set("cursor", cursorRef.current);
        const headers: Record<string, string> = { Accept: "text/event-stream" };

        try {
          // Same-origin, so the session cookie goes with it and there is no header to
          // build. `fetch` rather than `EventSource` precisely because `EventSource`
          // cannot set `Accept` or be aborted cleanly.
          const response = await fetch(url, {
            headers,
            credentials: "same-origin",
            signal: controller.signal,
          });
          if (!response.ok || !response.body) {
            throw new Error(`Live stream failed (${response.status})`);
          }
          setConnection("connected");
          setError(null);
          retryDelay = 500;
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";
          while (!controller.signal.aborted) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
            const blocks = buffer.split("\n\n");
            buffer = blocks.pop() ?? "";
            for (const block of blocks) {
              const message = parseMessage(block);
              if (!message) continue;
              try {
                const parsed = JSON.parse(message.data) as ObserveLiveEvent;
                const event = {
                  ...parsed,
                  type: message.event as ObserveLifecycle,
                  cursor: message.id ?? parsed.cursor,
                };
                if (event.trace_id !== traceId || !event.cursor) continue;
                cursorRef.current = event.cursor;
                try {
                  window.sessionStorage.setItem(storageKey, event.cursor);
                } catch {
                  // A disabled storage API must not stop execution updates.
                }
                setEvents((current) => {
                  if (current.some((candidate) => candidate.cursor === event.cursor)) {
                    return current;
                  }
                  return [...current.slice(-499), event];
                });
              } catch {
                // Ignore malformed frames; reconnecting from the last valid cursor is safe.
              }
            }
          }
          if (!controller.signal.aborted) setConnection("reconnecting");
        } catch (streamError) {
          if (controller.signal.aborted) break;
          setConnection("reconnecting");
          setError(streamError instanceof Error ? streamError.message : "Live stream failed");
        }
        await wait(retryDelay, controller.signal);
        retryDelay = Math.min(retryDelay * 2, 10_000);
      }
    };

    void connect();
    return () => controller.abort();
  }, [enabled, projectId, traceId]);

  return {
    events,
    connection: enabled ? connection : "idle",
    error,
  };
}
