/**
 * Jump to an agent, or to a screen, without navigating to find it.
 *
 * Filtering happens in the browser over the agent list the console has already loaded,
 * rather than through a search endpoint. On an estate of a few hundred agents that is
 * instant and correct; past a few thousand it stops being either, which is recorded as
 * Q-018 rather than solved speculatively here.
 *
 * Matching is on display name and URN together, because people refer to agents both
 * ways — by the name in the console and by the identifier in their own configuration —
 * and being asked which one you meant is a bad first interaction with a search box.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useAgents } from "@/api/queries";
import { Icon, type IconName } from "./Icon";

type Hit = { id: string; label: string; hint: string; href: string; icon: IconName };

const DESTINATIONS: Hit[] = [
  { id: "d-overview", label: "Overview", hint: "Screen", href: "/", icon: "home" },
  { id: "d-agents", label: "Agents", hint: "Screen", href: "/agents", icon: "agents" },
  { id: "d-runs", label: "Runs", hint: "Screen", href: "/runs", icon: "activity" },
  { id: "d-cost", label: "Usage & cost", hint: "Screen", href: "/cost", icon: "cost" },
  { id: "d-tools", label: "Tools & MCP", hint: "Screen", href: "/tools", icon: "mcp" },
  { id: "d-changes", label: "Changes", hint: "Screen", href: "/releases", icon: "changes" },
  { id: "d-approvals", label: "Approvals", hint: "Screen", href: "/accreditations", icon: "approvals" },
  { id: "d-issues", label: "Issues", hint: "Screen", href: "/findings", icon: "issues" },
  { id: "d-clients", label: "Clients", hint: "Screen", href: "/customers", icon: "clients" },
  { id: "d-evidence", label: "Evidence", hint: "Screen", href: "/evidence", icon: "evidence" },
];

export function QuickSearch() {
  const [open, setOpen] = useState(false);
  const [term, setTerm] = useState("");
  const [cursor, setCursor] = useState(0);
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);

  // Only fetched once the box is opened. The overview is the first thing most people
  // load and it should not also pay for a list nobody has asked for yet.
  const { data } = useAgents(open ? { limit: "200" } : undefined);

  const hits = useMemo<Hit[]>(() => {
    const needle = term.trim().toLowerCase();
    const agents: Hit[] = (data?.items ?? []).map((agent) => ({
      id: agent.id,
      label: agent.display_name,
      hint: agent.urn,
      href: `/agents/${agent.id}`,
      icon: "agents",
    }));
    const all = [...agents, ...DESTINATIONS];
    if (!needle) return all.slice(0, 8);
    return all
      .filter((h) => `${h.label} ${h.hint}`.toLowerCase().includes(needle))
      .slice(0, 10);
  }, [data, term]);

  // The cursor resets where the term changes rather than in an effect watching it. An
  // effect would re-render a second time after every keystroke, and the reset is a
  // consequence of the edit, not of the term happening to differ.
  function retype(next: string) {
    setTerm(next);
    setCursor(0);
  }

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(true);
        window.setTimeout(() => inputRef.current?.focus(), 0);
      }
      if (event.key === "Escape") setOpen(false);
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!open) return;
    function onClick(event: MouseEvent) {
      if (!boxRef.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  function go(hit: Hit | undefined) {
    if (!hit) return;
    navigate(hit.href);
    setOpen(false);
    setTerm("");
  }

  return (
    <div ref={boxRef} className="relative w-full max-w-xl flex-1">
      <div className="relative">
        <Icon
          name="search"
          size={16}
          className="pointer-events-none absolute left-3.5 top-1/2 -translate-y-1/2 text-ink-400"
        />
        <input
          ref={inputRef}
          type="search"
          value={term}
          placeholder="Search agents, owners, policies, reports…"
          onFocus={() => setOpen(true)}
          onChange={(e) => retype(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "ArrowDown") {
              e.preventDefault();
              setCursor((c) => Math.min(c + 1, hits.length - 1));
            }
            if (e.key === "ArrowUp") {
              e.preventDefault();
              setCursor((c) => Math.max(c - 1, 0));
            }
            if (e.key === "Enter") go(hits[cursor]);
          }}
          className="w-full rounded-full border border-line-200 bg-bg-panel py-2 pl-10 pr-16 text-body text-ink-900 shadow-hairline placeholder:text-ink-400 focus:border-accent focus:outline-none focus:ring-2 focus:ring-accent/20"
          aria-label="Search agents and screens"
        />
        <kbd className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 rounded border border-line-300 bg-bg-panel px-1.5 py-0.5 font-mono text-[10px] text-ink-400">
          ⌘K
        </kbd>
      </div>

      {open ? (
        <div className="absolute left-0 right-0 top-full z-30 mt-1.5 animate-fade-rise overflow-hidden rounded-card bg-bg-panel shadow-pop">
          {hits.length === 0 ? (
            <p className="px-3 py-4 text-body text-ink-400">No match for “{term}”.</p>
          ) : (
            <ul className="max-h-80 overflow-y-auto py-1 scrollbar-thin">
              {hits.map((hit, index) => (
                <li key={hit.id}>
                  <button
                    type="button"
                    onMouseEnter={() => setCursor(index)}
                    onClick={() => go(hit)}
                    className={`flex w-full items-center gap-2.5 px-3 py-2 text-left ${
                      index === cursor ? "bg-bg-hover" : ""
                    }`}
                  >
                    <Icon name={hit.icon} size={15} className="shrink-0 text-ink-400" />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate text-body text-ink-900">{hit.label}</span>
                      <span className="block truncate font-mono text-micro text-ink-400">
                        {hit.hint}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </div>
  );
}
