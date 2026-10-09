/**
 * Decides whether there is a signed-in person, by asking the server.
 *
 * The previous version read `sessionStorage` and believed it. That is not an
 * authentication check — it is a check that the browser has a leftover object — and it
 * is why a revoked or expired session rendered the whole shell before the first API call
 * came back 401.
 *
 * Now the answer comes from `/v1/session/bootstrap`. Exactly one request decides it, and
 * the same response is what the shell renders from, so there is no window in which the
 * console believes it is signed in and has nothing to show.
 */

import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { ApiError } from "@/api/client";
import { ReasonState } from "@/components/DataBoundary";
import { TableSkeleton } from "@/components/Skeleton";
import { BootstrapContext } from "./bootstrapContext";
import { useBootstrap } from "./useBootstrap";

/** Reasons whose answer is "sign in again", rather than "something is wrong". */
const SEND_TO_LOGIN = new Set(["session_expired", "not_authenticated", "mfa_required"]);

export function AuthGate({ children }: { children: ReactNode }) {
  const location = useLocation();
  const onLogin = location.pathname === "/login" || location.pathname.startsWith("/login/");
  const onPortal = location.pathname.startsWith("/portal/");

  const query = useBootstrap();
  // The trust portal has its own audience and its own credential; the login screen is
  // where you go when you have none. Neither may require a console session.
  const bypass = onLogin || onPortal;

  if (bypass) {
    return <>{children}</>;
  }

  if (query.isPending) {
    return (
      <div className="p-6">
        <TableSkeleton rows={8} cols={4} />
      </div>
    );
  }

  if (query.isError) {
    const reason = query.error instanceof ApiError ? query.error.reason : "internal_error";
    if (SEND_TO_LOGIN.has(reason)) {
      return <Navigate to="/login" replace state={{ from: location.pathname }} />;
    }
    // Everything else is a person who is signed in and cannot proceed — suspended,
    // not provisioned, or a backend that is down. Sending them to the login screen would
    // loop them against an identity provider that is perfectly happy to sign them in.
    return (
      <div className="mx-auto max-w-lg p-10">
        <ReasonState error={query.error} onRetry={() => void query.refetch()} />
      </div>
    );
  }

  return (
    <BootstrapContext.Provider value={query.data}>{children}</BootstrapContext.Provider>
  );
}
