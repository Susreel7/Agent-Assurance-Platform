/**
 * The single source of identity, permissions and navigation.
 *
 * One query, one key, one request. `inv_bootstrap_is_single_request` asserts that
 * loading the shell issues exactly one identity-related call, and this is it: no
 * component fetches identity on its own, and none should be taught to.
 *
 * The rule exists because the alternative is visible. When four components each fetched
 * some part of "who am I", they finished in an arbitrary order, so the navigation
 * rendered before permissions arrived and links appeared and then vanished. A screen
 * cannot be half-loaded if there is only one thing to load.
 */

import { useQuery, useQueryClient, type UseQueryResult } from "@tanstack/react-query";
import { api, ApiError } from "@/api/client";
import type { ModulesManifest } from "@/api/types";

export type NavItem = {
  label: string;
  path: string;
  icon: string;
  end: boolean;
  matches: string[];
};

export type NavGroup = { label: string | null; items: NavItem[] };

/**
 * Which information architecture the shell renders.
 *
 * An install property, not a preference and not a permission: it decides which product
 * this console *is*. `ledger` leads with agent actions and leaves the accreditation
 * screens reachable by URL; `assurance` is the console the earlier customers bought.
 */
export type ProductMode = "ledger" | "assurance";

/**
 * The optional product surfaces, keyed by the flag that reveals them in navigation.
 *
 * A false flag hides a link and nothing else. `App.tsx` still routes every one of these
 * paths, because the screens still work and somebody has them bookmarked.
 */
export type CapabilityFlag =
  | "accreditation"
  | "customers"
  | "engagements"
  | "graph"
  | "sla"
  | "prompt"
  | "evaluate"
  | "router";

export type Bootstrap = {
  member: {
    id: string;
    email: string;
    display_name: string;
    status: string;
    job_title: string | null;
    avatar_tone: string;
    timezone: string;
  };
  account: {
    id: string;
    name: string;
    slug: string;
    deployment_mode: string;
    tenancy: string;
    environment: string;
  };
  access: {
    role_keys: string[];
    permissions: string[];
    scoped: Record<string, string[]>;
  };
  product_mode: ProductMode;
  navigation: NavGroup[];
  // The same manifest `/v1/modules` returns, generated from the spec rather than
  // restated here. A hand-written twin of a wire type agrees with itself and with
  // nothing else, which is D-049.
  modules: ModulesManifest;
  capabilities: Record<string, boolean>;
  capability_flags: Partial<Record<CapabilityFlag, boolean>>;
  session: {
    id: string;
    expires_at: string;
    absolute_expires_at: string;
    provider_label: string | null;
    mfa_verified: boolean;
  } | null;
  generated_at: string;
};

export const BOOTSTRAP_KEY = ["session", "bootstrap"] as const;

export function useBootstrap(): UseQueryResult<Bootstrap, ApiError> {
  return useQuery<Bootstrap, ApiError>({
    queryKey: BOOTSTRAP_KEY,
    queryFn: () => api.get<Bootstrap>("/v1/session/bootstrap"),
    // Permissions change rarely and a stale answer is corrected by the next refusal from
    // the endpoint that matters, so this is worth keeping warm across navigations.
    staleTime: 5 * 60_000,
    // Not signed in is an answer, not a failure to retry. Retrying a 401 turns one
    // redirect to the login screen into three.
    retry: (failureCount, error) =>
      failureCount < 1 && error.status >= 500,
  });
}

/**
 * Discard the cached identity. Called after sign-out and after anything that changes a
 * grant or a membership, because both change what the navigation should contain.
 */
export function useResetBootstrap(): () => void {
  const client = useQueryClient();
  return () => {
    client.removeQueries({ queryKey: BOOTSTRAP_KEY });
  };
}
