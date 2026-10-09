/**
 * Sign in. The server decides what this screen offers.
 *
 * Every button here comes from `GET /v1/auth/config`. Nothing is read from the build
 * environment, and there is no auto-redirect: the previous version redirected to Entra
 * inside an effect on first paint, so a misconfiguration produced a blank screen with no
 * text on it and no way back.
 *
 * With no providers configured the screen says so, and says which configuration is
 * missing, rather than rendering a button that cannot work.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import Shield from "lucide-react/dist/esm/icons/shield";
import { useLocation, useNavigate } from "react-router-dom";
import type { ApiError } from "@/api/client";
import { ReasonState } from "@/components/DataBoundary";
import { Skeleton } from "@/components/Skeleton";
import {
  authConfig,
  beginDevelopmentLogin,
  beginLogin,
  type AuthConfig,
  type AuthProvider,
} from "./session";

export default function LoginScreen() {
  const navigate = useNavigate();
  const location = useLocation();
  const returnTo = (location.state as { from?: string } | null)?.from ?? "/";
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const configQuery = useQuery<AuthConfig, ApiError>({
    queryKey: ["auth", "config"],
    queryFn: () => authConfig(),
    retry: 1,
    staleTime: 60_000,
  });

  async function start(provider: AuthProvider) {
    setError(null);
    setBusy(provider.id);
    try {
      if (provider.kind === "development") {
        await beginDevelopmentLogin(provider, developmentEmail());
        navigate(returnTo, { replace: true });
        return;
      }
      await beginLogin(provider, returnTo);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in could not be started.");
      setBusy(null);
    }
  }

  return (
    <LoginFrame subtitle={configQuery.data?.account_hint ?? "Sign in to the assurance console"}>
      {configQuery.isPending ? (
        <div className="space-y-3">
          <Skeleton height="2.75rem" />
          <Skeleton height="2.75rem" width="70%" />
        </div>
      ) : configQuery.isError ? (
        <ReasonState error={configQuery.error} onRetry={() => void configQuery.refetch()} />
      ) : (
        <>
          {error ? (
            <div className="mb-4 rounded-xl border border-rose-500/30 bg-rose-500/10 px-3 py-2 text-xs text-rose-300">
              {error}
            </div>
          ) : null}

          {configQuery.data.providers.map((provider) => (
            <button
              key={provider.id}
              type="button"
              disabled={busy !== null}
              className="glass-button-primary mb-3 flex w-full items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-bold disabled:opacity-60"
              onClick={() => void start(provider)}
            >
              {provider.kind === "oidc" ? <MicrosoftMark /> : null}
              {busy === provider.id ? "Opening…" : provider.label}
            </button>
          ))}

          {configQuery.data.providers.length === 0 ? (
            <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-3 text-xs leading-relaxed text-amber-200">
              {configQuery.data.unavailable_reason ??
                "No sign-in method is configured for this deployment."}
            </div>
          ) : null}
        </>
      )}
    </LoginFrame>
  );
}

/**
 * The address a development sign-in claims.
 *
 * `localhost` and never a company domain: a development convenience that looks like a
 * production identity in an audit trail is worse than no convenience at all.
 */
function developmentEmail(): string {
  try {
    const stored = localStorage.getItem("aap.dev.email");
    if (stored && stored.includes("@")) return stored;
  } catch {
    /* private browsing */
  }
  return "developer@localhost";
}

export function LoginFrame({
  subtitle,
  children,
}: {
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <div className="nexus-shell relative flex min-h-screen items-center justify-center overflow-hidden font-sans">
      <div className="nexus-motion-bg" aria-hidden>
        <span className="nexus-orb nexus-orb-a" />
        <span className="nexus-orb nexus-orb-b" />
        <span className="nexus-grid" />
      </div>

      <div className="relative z-10 w-full max-w-md px-6">
        <div className="glass-card rounded-3xl border border-white/10 p-8 shadow-2xl">
          <div className="mb-6 flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-slate-900 text-white shadow-md dark:bg-white dark:text-black">
              <Shield size={20} strokeWidth={2.5} />
            </div>
            <div>
              <div className="text-lg font-bold tracking-tight text-slate-900 dark:text-white">
                Agent Assurance
              </div>
              <div className="text-[11px] font-medium text-slate-500">{subtitle}</div>
            </div>
          </div>

          {children}

          <p className="mt-6 text-[10px] leading-relaxed text-slate-500">
            Gateway policy blocks MCP tool calls without an account grant or Platform Key.
            Model traffic is routed only through permitted providers.
          </p>
        </div>
      </div>
    </div>
  );
}

function MicrosoftMark() {
  return (
    <svg width="16" height="16" viewBox="0 0 21 21" aria-hidden>
      <rect x="1" y="1" width="9" height="9" fill="#f25022" />
      <rect x="11" y="1" width="9" height="9" fill="#7fba00" />
      <rect x="1" y="11" width="9" height="9" fill="#00a4ef" />
      <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
    </svg>
  );
}
