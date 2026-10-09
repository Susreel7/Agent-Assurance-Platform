import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { PayloadReference } from "@/api/types";
import {
  useObservePayloadContent,
  useUpdateObservePayloadLegalHold,
} from "@/api/suiteQueries";
import { CopyButton } from "@/components/CopyButton";
import { Icon } from "@/components/Icon";

type Props = {
  projectId: string;
  reference: PayloadReference;
};

function decodeBase64(value?: string | null): string | null {
  if (!value) return null;
  try {
    const bytes = Uint8Array.from(atob(value), (character) => character.charCodeAt(0));
    return new TextDecoder().decode(bytes);
  } catch {
    return null;
  }
}

function prettyContent(content: string, mediaType: string, raw: boolean): string {
  if (raw || !mediaType.toLowerCase().includes("json")) return content;
  try {
    return JSON.stringify(JSON.parse(content), null, 2);
  } catch {
    return content;
  }
}

function highlightedLine(line: string): ReactNode[] {
  const parts = line.split(
    /("(?:\\.|[^"\\])*"(?=\s*:)|"(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?|\btrue\b|\bfalse\b|\bnull\b)/g,
  );
  return parts.map((part, index) => {
    if (/^".*"(?=\s*:)?$/.test(part)) {
      const isKey = new RegExp(`${part.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*:`).test(line);
      return (
        <span key={index} className={isKey ? "text-info-fg" : "text-ok-fg"}>
          {part}
        </span>
      );
    }
    if (/^(true|false|null)$/.test(part)) {
      return <span key={index} className="text-warn-fg">{part}</span>;
    }
    if (/^-?\d/.test(part)) {
      return <span key={index} className="text-accent-ink">{part}</span>;
    }
    return <span key={index}>{part}</span>;
  });
}

export function PayloadViewer({ projectId, reference }: Props) {
  const [requested, setRequested] = useState(false);
  const [mode, setMode] = useState<"preview" | "expanded" | "fullscreen">("preview");
  const [raw, setRaw] = useState(false);
  const [query, setQuery] = useState("");
  const [showHoldForm, setShowHoldForm] = useState(false);
  const [holdReason, setHoldReason] = useState("");
  const contentQuery = useObservePayloadContent(projectId, reference.payload_id, requested);
  const holdMutation = useUpdateObservePayloadLegalHold(
    projectId,
    reference.trace_id,
    reference.payload_id,
  );
  const isExpired = Boolean(reference.retention_deleted_at);
  const decoded = useMemo(
    () => decodeBase64(contentQuery.data?.content_base64),
    [contentQuery.data?.content_base64],
  );
  const content = useMemo(
    () => (decoded == null ? null : prettyContent(decoded, reference.media_type, raw)),
    [decoded, raw, reference.media_type],
  );
  const lines = useMemo(() => content?.split("\n") ?? [], [content]);
  const visibleLines = mode === "preview" ? lines.slice(0, 18) : lines;
  const normalizedQuery = query.trim().toLowerCase();
  const matchCount = normalizedQuery
    ? lines.reduce(
        (count, line) => count + (line.toLowerCase().split(normalizedQuery).length - 1),
        0,
      )
    : 0;

  useEffect(() => {
    if (mode !== "fullscreen") return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMode("expanded");
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [mode]);

  const download = () => {
    if (content == null) return;
    const url = URL.createObjectURL(new Blob([content], { type: reference.media_type }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `${reference.field_name.replace(/[^a-z0-9_.-]+/gi, "-")}.txt`;
    anchor.click();
    URL.revokeObjectURL(url);
  };

  const shellClass =
    mode === "fullscreen"
      ? "fixed inset-4 z-50 flex flex-col border border-line-300 bg-bg-panel shadow-pop"
      : "border border-line-200 bg-bg-sunk";

  return (
    <section
      className={shellClass}
      role={mode === "fullscreen" ? "dialog" : undefined}
      aria-modal={mode === "fullscreen" ? true : undefined}
      aria-label={`${reference.field_name} payload`}
    >
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-line-200 bg-bg-panel px-3 py-2">
        <div className="min-w-0">
          <p className="truncate font-mono-data text-xs font-medium text-ink-900">
            {reference.field_name}
          </p>
          <p className="mt-0.5 text-micro text-ink-400">
            {reference.media_type} · {reference.byte_size.toLocaleString()} bytes ·{" "}
            {reference.redaction_state ?? "policy protected"}
            {reference.legal_hold ? " · legal hold" : ""}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {!isExpired ? (
            <button
              type="button"
              onClick={() => {
                if (reference.legal_hold) {
                  holdMutation.mutate({ enabled: false });
                } else {
                  setShowHoldForm((value) => !value);
                }
              }}
              disabled={holdMutation.isPending}
              className="h-8 border border-line-200 bg-bg-panel px-2.5 text-xs text-ink-600 hover:bg-bg-hover disabled:opacity-50"
            >
              {reference.legal_hold ? "Release hold" : "Legal hold"}
            </button>
          ) : null}
        {!requested && !isExpired ? (
          <button
            type="button"
            onClick={() => setRequested(true)}
            className="h-8 border border-line-200 bg-bg-panel px-2.5 text-xs font-medium text-info-fg hover:bg-bg-hover"
          >
            Load protected content
          </button>
        ) : null}
        </div>
        {content != null ? (
          <div className="flex items-center gap-2">
            <CopyButton value={content} />
            <button type="button" onClick={download} className="text-xs text-info-fg hover:underline">
              Download
            </button>
            {reference.media_type.toLowerCase().includes("json") ? (
              <button
                type="button"
                onClick={() => setRaw((value) => !value)}
                className="text-xs text-info-fg hover:underline"
              >
                {raw ? "Pretty JSON" : "Raw"}
              </button>
            ) : null}
            <button
              type="button"
              onClick={() => setMode(mode === "fullscreen" ? "expanded" : "fullscreen")}
              className="text-ink-400 hover:text-ink-700"
              title={mode === "fullscreen" ? "Exit fullscreen" : "Open fullscreen"}
            >
              <Icon name={mode === "fullscreen" ? "close" : "external"} size={14} />
            </button>
          </div>
        ) : null}
      </header>

      {showHoldForm && !reference.legal_hold ? (
        <div className="flex gap-2 border-b border-line-200 bg-warn-bg px-3 py-2">
          <input
            value={holdReason}
            onChange={(event) => setHoldReason(event.target.value)}
            placeholder="Reason for preservation"
            aria-label="Legal hold reason"
            className="h-8 min-w-0 flex-1 border border-line-200 bg-bg-panel px-2 text-xs outline-none focus:border-info-fg"
          />
          <button
            type="button"
            disabled={!holdReason.trim() || holdMutation.isPending}
            onClick={() =>
              holdMutation.mutate(
                { enabled: true, reason: holdReason.trim() },
                { onSuccess: () => setShowHoldForm(false) },
              )
            }
            className="h-8 border border-warn-solid px-2.5 text-xs font-medium text-warn-fg disabled:opacity-50"
          >
            Preserve
          </button>
        </div>
      ) : null}
      {holdMutation.isError ? (
        <p className="border-b border-risk-solid bg-risk-bg px-3 py-2 text-xs text-risk-fg">
          Legal-hold policy could not be updated.
        </p>
      ) : null}

      {isExpired ? (
        <div className="px-3 py-3 text-xs text-ink-400">
          Content was deleted by the retention policy. Its digest and execution metadata remain
          available.
        </div>
      ) : !requested ? (
        <div className="px-3 py-3 text-xs leading-5 text-ink-400">
          Content is lazy-loaded and access is audited. Digest{" "}
          <span className="font-mono-data">{reference.digest.slice(0, 20)}…</span>
        </div>
      ) : contentQuery.isLoading ? (
        <div className="px-3 py-4 text-xs text-ink-400">Loading protected content…</div>
      ) : contentQuery.isError ? (
        <div className="flex items-center justify-between gap-3 px-3 py-3 text-xs text-risk-fg">
          <span>Content could not be loaded or access was denied.</span>
          <button type="button" onClick={() => void contentQuery.refetch()} className="underline">
            Retry
          </button>
        </div>
      ) : content == null ? (
        <div className="px-3 py-3 text-xs text-ink-400">
          Content is unavailable at this capture level. Metadata and digest remain available.
        </div>
      ) : (
        <div className={`flex min-h-0 flex-col ${mode === "fullscreen" ? "flex-1" : ""}`}>
          <div className="flex items-center gap-2 border-b border-line-200 bg-bg-panel px-3 py-2">
            <label className="relative min-w-40 flex-1">
              <Icon name="search" size={13} className="absolute left-2 top-1.5 text-ink-400" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search content"
                aria-label={`Search ${reference.field_name}`}
                className="h-7 w-full border border-line-200 bg-bg-panel pl-7 pr-2 text-xs outline-none focus:border-info-fg"
              />
            </label>
            <span className="text-micro text-ink-400">
              {normalizedQuery ? `${matchCount} matches · ` : ""}
              {content.length.toLocaleString()} chars · ~{Math.ceil(content.length / 4).toLocaleString()} tokens
            </span>
          </div>
          <div
            className={`overflow-auto bg-[#fbfcfd] font-mono text-[11px] leading-5 text-ink-700 ${
              mode === "preview" ? "max-h-72" : mode === "expanded" ? "max-h-[34rem]" : "min-h-0 flex-1"
            }`}
          >
            {visibleLines.map((line, index) => {
              const matches =
                normalizedQuery.length > 0 && line.toLowerCase().includes(normalizedQuery);
              return (
                <div
                  key={`${index}:${line.slice(0, 24)}`}
                  className={`grid grid-cols-[48px_minmax(0,1fr)] ${matches ? "bg-warn-bg" : ""}`}
                >
                  <span className="select-none border-r border-line-200 px-2 text-right text-ink-300">
                    {index + 1}
                  </span>
                  <code className="whitespace-pre-wrap break-words px-3">{highlightedLine(line)}</code>
                </div>
              );
            })}
          </div>
          {mode !== "fullscreen" ? (
            <footer className="flex justify-center border-t border-line-200 bg-bg-panel py-2">
              <button
                type="button"
                onClick={() => setMode(mode === "preview" ? "expanded" : "preview")}
                className="text-xs font-medium text-info-fg hover:underline"
              >
                {mode === "preview" && lines.length > visibleLines.length
                  ? `Expand ${lines.length - visibleLines.length} more lines`
                  : mode === "preview"
                    ? "Expand viewer"
                    : "Collapse preview"}
              </button>
            </footer>
          ) : null}
        </div>
      )}
    </section>
  );
}
