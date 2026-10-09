import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
// Direct per-icon imports, not `from "lucide-react"`. The barrel re-exports the whole
// set, so three icons cost roughly a thousand modules of resolution work in dev and
// hundreds of milliseconds of cold start in production. This file is on the critical
// path for every route, so it is the worst possible place to pay it. Vite has no
// equivalent of Next's `optimizePackageImports`, which leaves direct imports as the
// only fix; `inv_no_lucide_barrel` in `scripts/check-runtime-contract.mjs` keeps them.
import Activity from "lucide-react/dist/esm/icons/activity";
import ArrowRight from "lucide-react/dist/esm/icons/arrow-right";
import Bell from "lucide-react/dist/esm/icons/bell";
import ChevronDown from "lucide-react/dist/esm/icons/chevron-down";
import Cpu from "lucide-react/dist/esm/icons/cpu";
import Home from "lucide-react/dist/esm/icons/home";
import Key from "lucide-react/dist/esm/icons/key";
import Layers from "lucide-react/dist/esm/icons/layers";
import Lock from "lucide-react/dist/esm/icons/lock";
import Menu from "lucide-react/dist/esm/icons/menu";
import Moon from "lucide-react/dist/esm/icons/moon";
import Network from "lucide-react/dist/esm/icons/network";
import Plug from "lucide-react/dist/esm/icons/plug";
import Rows3 from "lucide-react/dist/esm/icons/rows-3";
import Search from "lucide-react/dist/esm/icons/search";
import Shield from "lucide-react/dist/esm/icons/shield";
import Sliders from "lucide-react/dist/esm/icons/sliders";
import Sun from "lucide-react/dist/esm/icons/sun";
import User from "lucide-react/dist/esm/icons/user";
import Users from "lucide-react/dist/esm/icons/users";
import Waypoints from "lucide-react/dist/esm/icons/waypoints";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useDeployment } from "@/api/queries";
import { useTheme } from "@/lib/theme";
import { useIdentity } from "@/features/auth/bootstrapContext";
import { logout } from "@/features/auth/session";
import type { NavItem } from "@/features/auth/useBootstrap";

/**
 * Icon names to glyphs.
 *
 * The server decides which links exist and names an icon; the client owns the icon set.
 * That split is deliberate — shipping SVG in a JSON envelope would tie the API to a
 * component library's version. An unknown name falls back rather than crashing a render.
 */
const ICONS: Record<string, React.ElementType> = {
  home: Home,
  cpu: Cpu,
  activity: Activity,
  network: Network,
  rows: Rows3,
  waypoints: Waypoints,
  users: Users,
  user: User,
  search: Search,
  sliders: Sliders,
  layers: Layers,
  plug: Plug,
  key: Key,
  shield: Shield,
  lock: Lock,
};

/**
 * Whether a nav item owns the current URL.
 *
 * Derived from the pathname, never from local state. The reported bug where clicking one
 * tab highlighted three was a `useState` holding "the selected item" alongside a router
 * that had its own idea — two sources of truth for one fact, disagreeing. There is one
 * source now, and it is the address bar.
 */
function isActive(pathname: string, item: NavItem): boolean {
  const candidates = [item.path, ...item.matches];
  return candidates.some((path) => {
    if (path === "/" || item.end) return pathname === path;
    return pathname === path || pathname.startsWith(`${path}/`);
  });
}

export function Shell() {
  const location = useLocation();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { data: deployment } = useDeployment();
  const { resolved, setChoice } = useTheme();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);

  // One source for identity and navigation, resolved by `AuthGate` before this renders.
  // There is no loading branch here on purpose: the shell does not exist until the
  // bootstrap request has answered, so it cannot paint a half-filled sidebar.
  const identity = useIdentity();
  // The command palette was a second hardcoded list of four destinations, which in a
  // ledger install offered a model-routing screen that is not in the sidebar and never
  // mentioned the ledger. Flattening the manifest keeps it honest for free: whatever
  // the server says this person may open is what the palette jumps to.
  const quickNavigation = identity.navigation.flatMap((group) =>
    group.items.map((item) => ({ ...item, group: group.label })),
  );
  const displayName = identity.member.display_name;
  const displayEmail = identity.member.email;
  const initials =
    displayName
      .split(/\s+/)
      .map((part) => part[0] ?? "")
      .join("")
      .slice(0, 2)
      .toUpperCase() || "OP";

  async function signOut() {
    try {
      // Revokes the row server side. Clearing a cookie alone is what the old sign-out
      // did, and it left the session usable to anybody holding a copy of the token.
      await logout();
    } finally {
      queryClient.clear();
      navigate("/login", { replace: true });
    }
  }

  const go = (path: string) => {
    navigate(path);
    setSidebarOpen(false);
    setSearchOpen(false);
  };

  return (
    <div className="nexus-shell relative flex h-screen overflow-hidden font-sans">
      <div className="nexus-motion-bg" aria-hidden>
        <span className="nexus-orb nexus-orb-a" />
        <span className="nexus-orb nexus-orb-b" />
        <span className="nexus-grid" />
      </div>

      <aside
        className={`nexus-sidebar fixed inset-y-0 left-0 z-50 flex w-[260px] flex-col border-r backdrop-blur-2xl transition-transform duration-300 md:relative md:translate-x-0 ${
          sidebarOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="border-b border-slate-200/60 p-5 dark:border-white/5">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-slate-900 text-white shadow-md dark:bg-white dark:text-black">
              <Shield size={18} strokeWidth={2.5} />
            </div>
            <div>
              <div className="text-sm font-bold tracking-tight text-slate-900 dark:text-white">
                Agent Assurance
              </div>
              <div className="text-[10px] font-medium text-slate-500">
                People &amp; Agent Governance
              </div>
            </div>
          </div>
          <div className="mt-3 flex items-center justify-between">
            <div className="inline-flex items-center gap-2 rounded-full border border-slate-300/60 bg-slate-100/70 px-2.5 py-0.5 text-[9px] font-bold uppercase tracking-widest text-slate-600 dark:border-white/10 dark:bg-white/5 dark:text-slate-400">
              <span className="h-1.5 w-1.5 rounded-full bg-slate-400" />
              {deployment?.mode?.toUpperCase() ?? "DEPLOYMENT"}
            </div>
            <span className="font-mono text-[10px] text-slate-400">v0.1.0</span>
          </div>
        </div>

        <nav className="scrollbar-thin flex-1 space-y-5 overflow-y-auto px-3 py-3">
          {identity.navigation.map((group, index) => (
            <div key={group.label ?? index}>
              {group.label ? (
                <div className="px-3 pb-1.5 text-[10px] font-bold uppercase tracking-wider text-slate-400 dark:text-slate-500">
                  {group.label}
                </div>
              ) : null}
              <div className="space-y-0.5">
                {group.items.map((item) => {
                  const active = isActive(location.pathname, item);
                  const NavIcon = ICONS[item.icon] ?? Activity;
                  return (
                    <button
                      key={`${group.label ?? "root"}-${item.label}`}
                      type="button"
                      onClick={() => go(item.path)}
                      className={`flex w-full items-center gap-3 rounded-xl px-3 py-2 text-left text-xs font-medium transition-all duration-200 ${
                        active
                          ? "border border-indigo-100 bg-indigo-50 font-bold text-indigo-900 shadow-sm dark:border-transparent dark:bg-white/10 dark:text-white dark:shadow-inner"
                          : "text-slate-600 hover:bg-slate-100/80 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-white/5 dark:hover:text-slate-200"
                      }`}
                    >
                      <NavIcon
                        size={15}
                        className={
                          active
                            ? "text-indigo-600 dark:text-cyan-400"
                            : "text-slate-400 dark:text-slate-500"
                        }
                      />
                      <span>{item.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        <div className="border-t border-slate-200/60 bg-slate-50/50 p-3 dark:border-white/10 dark:bg-black/20">
          <button
            type="button"
            onClick={() => go("/profile")}
            className={`flex w-full items-center gap-3 rounded-xl p-2 text-left transition-colors ${
              location.pathname === "/profile"
                ? "bg-indigo-50 text-indigo-900 dark:bg-white/10 dark:text-white"
                : "hover:bg-slate-200/50 dark:hover:bg-white/5"
            }`}
          >
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-gradient-to-tr from-indigo-500 to-cyan-400 text-xs font-bold text-white shadow">
              {initials}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-xs font-semibold text-slate-900 dark:text-white">
                {displayName}
              </span>
              <span className="block truncate text-[10px] text-slate-500">
                {displayEmail} · {deployment?.mode?.toUpperCase() ?? "LOCAL"}
              </span>
            </span>
            <ChevronDown size={14} className="text-slate-400" />
          </button>
          <button
            type="button"
            className="mt-1 w-full rounded-lg px-2 py-1 text-left text-[10px] font-semibold text-slate-500 hover:bg-slate-200/50 hover:text-slate-800 dark:hover:bg-white/5 dark:hover:text-slate-200"
            onClick={() => void signOut()}
          >
            Sign out
          </button>
        </div>
      </aside>

      <div className="relative z-10 flex h-screen min-w-0 flex-1 flex-col">
        <header className="glass-panel glass-stable z-40 flex h-[64px] shrink-0 items-center justify-between border-b px-4 md:px-8">
          <div className="flex items-center gap-3">
            <button
              type="button"
              className="p-2 text-slate-500 md:hidden dark:text-slate-400"
              onClick={() => setSidebarOpen(true)}
              aria-label="Open navigation"
            >
              <Menu size={20} />
            </button>
            <div className="flex items-center gap-2 rounded-xl border border-slate-200/80 bg-slate-100/80 px-2.5 py-1.5 text-xs font-semibold text-slate-800 dark:border-white/10 dark:bg-white/5 dark:text-slate-200">
              <span className="h-2 w-2 rounded-full bg-emerald-500" />
              <span>{deployment?.licensee ?? "Local Assurance Account"}</span>
              <span className="ml-1 font-mono text-[10px] text-slate-400">
                {deployment?.environment?.toUpperCase() ?? "DEV"}
              </span>
            </div>
          </div>

          <button
            type="button"
            onClick={() => setSearchOpen(true)}
            className="glass-input mx-4 hidden max-w-md flex-1 items-center gap-2.5 rounded-xl px-3.5 py-2 text-xs text-slate-400 transition-all hover:border-indigo-500/40 md:flex"
          >
            <Search size={14} />
            <span className="truncate">
              Search agents, tools, MCP gateways, or policy evidence...
            </span>
            <span className="ml-auto rounded border border-slate-300 bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] text-slate-500 dark:border-white/10 dark:bg-black/50">
              ⌘ K
            </span>
          </button>

          <div className="flex items-center gap-2.5">
            <button
              type="button"
              onClick={() => setChoice(resolved === "dark" ? "light" : "dark")}
              className="flex items-center gap-2 rounded-xl border border-slate-200 bg-slate-100/90 px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-sm transition-all hover:bg-slate-200/90 dark:border-white/10 dark:bg-white/5 dark:text-slate-200 dark:hover:bg-white/10"
            >
              {resolved === "dark" ? (
                <Sun size={14} className="text-amber-400" />
              ) : (
                <Moon size={14} className="text-indigo-600" />
              )}
              <span className="hidden sm:inline">
                {resolved === "dark" ? "Light Mode" : "Dark Mode"}
              </span>
            </button>
            <button
              type="button"
              className="relative flex h-9 w-9 items-center justify-center rounded-xl border border-slate-200/60 text-slate-500 transition-colors hover:bg-slate-100 dark:border-white/5 dark:text-slate-400 dark:hover:bg-white/10"
              aria-label="Notifications"
            >
              <Bell size={16} />
              <span className="absolute right-2 top-2 h-2 w-2 rounded-full bg-rose-500 ring-2 ring-white dark:ring-black" />
            </button>
          </div>
        </header>

        <main className="scrollbar-thin flex-1 overflow-y-auto scroll-smooth">
          <div className="mx-auto max-w-[1440px] p-6 pb-24 md:p-8">
            <Outlet />
          </div>
        </main>
      </div>

      <AnimatePresence>
        {sidebarOpen ? (
          <motion.button
            type="button"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm md:hidden"
            onClick={() => setSidebarOpen(false)}
            aria-label="Close navigation"
          />
        ) : null}
        {searchOpen ? (
          <div className="fixed inset-0 z-[100] flex items-start justify-center p-4 pt-[12vh]">
            <motion.button
              type="button"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="absolute inset-0 bg-black/70 backdrop-blur-md"
              onClick={() => setSearchOpen(false)}
              aria-label="Close search"
            />
            <motion.div
              initial={{ opacity: 0, scale: 0.96, y: -15 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.96, y: -15 }}
              className="relative w-full max-w-2xl overflow-hidden rounded-2xl border border-slate-300 bg-white text-slate-800 shadow-2xl dark:border-white/10 dark:bg-slate-900 dark:text-slate-200"
            >
              <div className="flex items-center border-b border-slate-200 px-4 py-3.5 dark:border-white/10">
                <Search size={18} className="mr-3 shrink-0 text-slate-400" />
                <input
                  autoFocus
                  placeholder="Jump to agent, MCP server, tool, policy rule, or evidence..."
                  className="flex-1 border-none bg-transparent text-base text-slate-900 outline-none placeholder:text-slate-400 dark:text-white"
                />
                <button
                  type="button"
                  onClick={() => setSearchOpen(false)}
                  className="rounded-md bg-slate-100 px-2 py-1 text-xs text-slate-500 dark:bg-white/10"
                >
                  ESC
                </button>
              </div>
              <div className="p-3">
                <div className="px-3 py-1.5 text-[11px] font-bold uppercase tracking-wider text-slate-400">
                  Fast navigation
                </div>
                <div className="max-h-[50vh] overflow-y-auto scrollbar-thin">
                  {quickNavigation.map((item) => {
                    const ItemIcon = ICONS[item.icon] ?? Activity;
                    return (
                      <button
                        type="button"
                        key={item.path}
                        onClick={() => go(item.path)}
                        className="flex w-full items-center justify-between rounded-xl px-3 py-2.5 text-left transition-colors hover:bg-slate-100 dark:hover:bg-white/5"
                      >
                        <div className="flex items-center gap-3">
                          <ItemIcon size={16} className="text-cyan-500" />
                          <span className="text-xs font-bold text-slate-900 dark:text-white">
                            {item.label}
                          </span>
                          {item.group ? (
                            <span className="text-[10px] text-slate-400">{item.group}</span>
                          ) : null}
                        </div>
                        <ArrowRight size={14} className="text-slate-400" />
                      </button>
                    );
                  })}
                </div>
              </div>
            </motion.div>
          </div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
