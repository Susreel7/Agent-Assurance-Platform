/**
 * The four states of a screen, in one place.
 *
 * A screen is loading, empty, failed, or showing data. There is no fifth state, and in
 * particular there is no "signed in but nothing has appeared yet" — that is what this
 * component exists to make unrepresentable.
 *
 * The error state is the reason it is worth having at all. Before this, every failure in
 * the console rendered as "Something went wrong · Try again" with a Try again button
 * that retried a request which was never going to succeed: a 403 from a permissions
 * check, a 404 from a dead URL and a 500 from a real bug were indistinguishable. Here
 * the reason code decides the heading and the action, so a person who lacks a permission
 * is offered a way to request it, and somebody whose session has expired is offered a
 * sign-in rather than a retry.
 *
 * Wrap a screen in this and it cannot lie about what happened to it.
 */

import type { ReactNode } from "react";
import { useNavigate } from "react-router-dom";
import type { UseQueryResult } from "@tanstack/react-query";
import { ApiError, type NextActionKind, type Reason } from "@/api/client";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { RelativeTime } from "@/components/RelativeTime";
import { TableSkeleton } from "@/components/Skeleton";

/** Headings per reason. Absent reasons fall back to the server's own sentence. */
const TITLES: Partial<Record<Reason, string>> = {
  session_expired: "Your session has ended",
  not_authenticated: "You are not signed in",
  not_provisioned: "You do not have access to this account yet",
  membership_suspended: "Your membership is suspended",
  mfa_required: "Multi-factor authentication required",
  module_forbidden: "You do not have permission to see this",
  module_not_entitled: "Not included in this licence",
  scope_outside_grant: "Outside the part of the organisation you can see",
  approval_pending: "Waiting for approval",
  policy_denied: "A policy refused this",
  bundle_stale: "Running on a cached policy",
  not_found: "Not found",
  conflict: "That conflicts with something else",
  precondition_failed: "Somebody else changed this",
  rate_limited: "Too many requests",
  licence_read_only: "This install is read-only",
  upstream_unavailable: "A service this page needs is unavailable",
  identity_provider_unavailable: "Your identity provider is unreachable",
  provider_not_configured: "Sign-in is not configured",
  internal_error: "This failed on our side",
};

const ACTION_LABELS: Partial<Record<NextActionKind, string>> = {
  sign_in: "Sign in again",
  retry: "Try again",
  request_access: "Request access",
  contact_owner: "Contact an account owner",
  reauthenticate: "Sign in again",
  open_request: "Open the request",
  configure_provider: "Open sign-in settings",
};

type DataBoundaryProps<T> = {
  query: Pick<
    UseQueryResult<T, unknown>,
    "data" | "isPending" | "isError" | "error" | "refetch" | "fetchStatus"
  >;
  /** True when the request succeeded and there is genuinely nothing to show. */
  empty?: (data: T) => boolean;
  emptyTitle?: string;
  emptyDescription?: string;
  emptyAction?: ReactNode;
  /** Shown when the query is disabled — a filter it depends on has not been chosen. */
  idleTitle?: string;
  idleDescription?: string;
  loading?: ReactNode;
  /**
   * When the numbers were measured, as an ISO timestamp the payload carried.
   *
   * Rendered under the data because an aggregate with no stated age is read as "now",
   * and a rollup that last ran forty minutes ago is a different answer from a live one.
   * Omit it rather than inventing one: the absence of a freshness line is honest, a
   * wrong freshness line is not.
   */
  freshnessAt?: (data: T) => string | null | undefined;
  children: (data: T) => ReactNode;
};

export function DataBoundary<T>({
  query,
  empty,
  emptyTitle = "Nothing here yet",
  emptyDescription,
  emptyAction,
  idleTitle = "Nothing selected",
  idleDescription,
  loading,
  freshnessAt,
  children,
}: DataBoundaryProps<T>) {
  // A disabled query is pending and will stay pending — it is waiting on a filter, not
  // on the network. Rendering a skeleton for it is how a screen with no project selected
  // ends up spinning forever, which is the failure this whole component exists to stop.
  if (query.isPending && query.fetchStatus === "idle") {
    return <EmptyState title={idleTitle} description={idleDescription} />;
  }

  if (query.isPending) {
    return <>{loading ?? <TableSkeleton rows={6} cols={4} />}</>;
  }

  if (query.isError) {
    return <ReasonState error={query.error} onRetry={() => void query.refetch()} />;
  }

  const data = query.data as T;
  if (empty?.(data)) {
    return (
      <EmptyState title={emptyTitle} description={emptyDescription} action={emptyAction} />
    );
  }

  const freshness = freshnessAt?.(data);
  return (
    <>
      {children(data)}
      {freshness ? (
        <p className="mt-3 text-[10px] text-ink-400">
          Measured <RelativeTime iso={freshness} />
        </p>
      ) : null}
    </>
  );
}

/**
 * An `ApiError` turned into something a person can act on.
 *
 * Exported separately because a few places need it outside a query — the shell's own
 * boundary, the project provider, and the login screen, none of which have a
 * `UseQueryResult` in hand at the point they have to explain themselves.
 *
 * All it does is read the envelope and hand `ErrorState` the two fields that decide what
 * the box says: the reason, which picks the heading, and `next`, which picks the button.
 * Everything below is a lookup table because the alternative — each screen deciding what
 * a 403 means — is what produced "Something went wrong · Try again" on every failure.
 */
export function ReasonState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const navigate = useNavigate();
  const api = error instanceof ApiError ? error : null;
  const reason = api?.reason ?? "internal_error";
  const message =
    api?.message ?? (error instanceof Error ? error.message : "The request did not complete.");
  const next = api?.next ?? (onRetry ? "retry" : "none");
  const label = ACTION_LABELS[next];

  function act() {
    switch (next) {
      case "sign_in":
      case "reauthenticate":
        navigate("/login", { replace: true });
        return;
      // All three are answered by the same screen — it is where a grant is requested,
      // where a pending request is found, and where sign-in is configured.
      case "request_access":
      case "configure_provider":
      case "open_request":
        navigate("/admin/access");
        return;
      default:
        onRetry?.();
    }
  }

  const offered = label && (next !== "retry" || onRetry);

  return (
    <ErrorState
      title={TITLES[reason] ?? "This did not load"}
      message={message}
      reason={reason}
      next={offered ? { label, onAction: act } : null}
      requestId={api?.requestId}
    />
  );
}
