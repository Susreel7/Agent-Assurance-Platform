/**
 * Marks for the harness vocabulary stored on `agent_instances.harness`.
 *
 * These are original geometric marks, one per value the ledger already accepts.
 * The label next to the mark is the accessible name; the picture is decorative.
 */

const HARNESSES = [
  {
    id: "cursor",
    name: "Cursor",
    detail: "IDE agent sessions, hooks, and MCP calls attributed to Cursor.",
  },
  {
    id: "claude_code",
    name: "Claude Code",
    detail: "Claude Code CLI sessions and the tools they invoke.",
  },
  {
    id: "copilot",
    name: "GitHub Copilot",
    detail: "Copilot agent activity inside an editor or a pull request.",
  },
  {
    id: "codex",
    name: "OpenAI Codex",
    detail: "Codex CLI and cloud-agent runs.",
  },
  {
    id: "gemini_cli",
    name: "Gemini CLI",
    detail: "Gemini CLI sessions and their tool calls.",
  },
  {
    id: "langgraph",
    name: "LangGraph",
    detail: "Graph runs reported through the tracing SDK.",
  },
  {
    id: "sdk",
    name: "SDK",
    detail: "Python and TypeScript workloads using aap-trace directly.",
  },
  {
    id: "ci",
    name: "CI",
    detail: "Pipeline agents that run without an interactive editor.",
  },
] as const;

export type HarnessId = (typeof HARNESSES)[number]["id"];

export function HarnessStrip() {
  return (
    <ul className="grid gap-px overflow-hidden rounded-xl border border-slate-200 bg-slate-200 sm:grid-cols-2 lg:grid-cols-4 dark:border-white/10 dark:bg-white/10">
      {HARNESSES.map((harness) => (
        <li key={harness.id} className="flex items-start gap-3 bg-bg-panel px-4 py-3 dark:bg-transparent">
          <HarnessMark id={harness.id} />
          <div className="min-w-0">
            <p className="text-xs font-bold text-slate-900 dark:text-white">{harness.name}</p>
            <p className="mt-0.5 text-[11px] leading-snug text-slate-500 dark:text-slate-400">
              {harness.detail}
            </p>
          </div>
        </li>
      ))}
    </ul>
  );
}

export function HarnessMark({ id }: { id: HarnessId }) {
  return (
    <svg
      width="28"
      height="28"
      viewBox="0 0 28 28"
      aria-hidden
      className="shrink-0"
    >
      {mark(id)}
    </svg>
  );
}

function mark(id: HarnessId) {
  switch (id) {
    case "cursor":
      return (
        <>
          <rect width="28" height="28" rx="7" fill="#111111" />
          <path d="M8 7.5 20.5 13.2 14.2 15.1 12.4 21.2 8 7.5Z" fill="#f5f5f5" />
        </>
      );
    case "claude_code":
      return (
        <>
          <rect width="28" height="28" rx="7" fill="#d97757" />
          <path
            d="M14 5.5 15.7 11.2 21.5 12.2 16.8 15.6 18.2 21.5 14 18.2 9.8 21.5 11.2 15.6 6.5 12.2 12.3 11.2 14 5.5Z"
            fill="#fff7f2"
          />
        </>
      );
    case "copilot":
      return (
        <>
          <rect width="28" height="28" rx="7" fill="#1f2328" />
          <circle cx="11" cy="14" r="4.2" fill="none" stroke="#ffffff" strokeWidth="1.6" />
          <circle cx="17" cy="14" r="4.2" fill="none" stroke="#7ee787" strokeWidth="1.6" />
        </>
      );
    case "codex":
      return (
        <>
          <rect width="28" height="28" rx="7" fill="#10a37f" />
          <path
            d="M9 10.5 6.5 14 9 17.5M19 10.5 21.5 14 19 17.5M15.2 8.5 12.8 19.5"
            fill="none"
            stroke="#ffffff"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </>
      );
    case "gemini_cli":
      return (
        <>
          <rect width="28" height="28" rx="7" fill="#4b3fbf" />
          <path d="M14 6.2 15.4 12.6 21.8 14 15.4 15.4 14 21.8 12.6 15.4 6.2 14 12.6 12.6 14 6.2Z" fill="#ffffff" />
        </>
      );
    case "langgraph":
      return (
        <>
          <rect width="28" height="28" rx="7" fill="#16332f" />
          <path d="M9 18.5 14 9.5 19 18.5" fill="none" stroke="#9be7c4" strokeWidth="1.4" />
          <circle cx="9" cy="18.5" r="2" fill="#9be7c4" />
          <circle cx="14" cy="9.5" r="2" fill="#ffffff" />
          <circle cx="19" cy="18.5" r="2" fill="#9be7c4" />
        </>
      );
    case "sdk":
      return (
        <>
          <rect width="28" height="28" rx="7" fill="#312e81" />
          <path
            d="M11.5 9.5 7.5 14l4 4.5M16.5 9.5 20.5 14l-4 4.5"
            fill="none"
            stroke="#c7d2fe"
            strokeWidth="1.6"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </>
      );
    case "ci":
      return (
        <>
          <rect width="28" height="28" rx="7" fill="#334155" />
          <circle cx="8" cy="14" r="2" fill="#ffffff" />
          <circle cx="14" cy="14" r="2" fill="#ffffff" />
          <circle cx="20" cy="14" r="2" fill="#38bdf8" />
          <path d="M10 14h2M16 14h2" stroke="#ffffff" strokeWidth="1.4" />
        </>
      );
    default:
      return null;
  }
}
