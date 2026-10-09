/**
 * What the signed-in person may do, for deciding what to render.
 *
 * This is presentation only. Every permission checked here is checked again by the API on
 * the request itself, and the API's answer is the one that counts — a console that hides a
 * button is a courtesy, not a control. The reason to do it at all is that showing someone
 * forty destinations that all return 403 is a worse experience than showing them the four
 * that work.
 *
 * The scope argument mirrors `EffectiveAccess.allows` on the server, including the rule
 * that an account-level grant subsumes narrower ones: a security admin granted at account
 * level should not need a per-project grant to answer a page-out.
 */

import { useIdentity } from "@/features/auth/bootstrapContext";
import type { Bootstrap } from "@/features/auth/useBootstrap";
import type { ScopeKind } from "@/api/platformTypes";

/**
 * The part of an access answer this file needs.
 *
 * Structural rather than `EffectiveAccess`, because the same judgement now arrives in
 * two envelopes — the bootstrap's `access`, and the full record the access screens
 * read — and both carry `scoped`. Naming only what is used keeps a caller from having
 * to fabricate a `member_id` to ask a question that does not depend on one.
 */
type Scoped = { scoped: Record<string, string[]> };

export function scopeKey(kind: ScopeKind, id?: string | null): string {
  return kind === "account" ? "account" : `${kind}:${id ?? ""}`;
}

export function allows(access: Scoped | undefined, permission: string, scope = "account"): boolean {
  const held = access?.scoped[permission];
  if (!held) return false;
  return held.includes("account") || held.includes(scope);
}

/**
 * `can("mcp:grant")` for the common case, `can("mcp:grant", scopeKey("project", id))`
 * when the question is about one resource.
 *
 * Read from the bootstrap, which `AuthGate` has already resolved, so there is no
 * `loading` to return: a caller cannot reach this hook before the answer exists. The
 * flag used to be here because this made its own request to `/v1/access/me`, which
 * meant every guarded control flashed in on first paint and, worse, made the shell
 * issue a second identity request — the thing `inv_bootstrap_is_single_request` forbids.
 */
export function usePermissions(): {
  can: (permission: string, scope?: string) => boolean;
  access: Bootstrap["access"];
} {
  const { access } = useIdentity();
  return {
    can: (permission: string, scope = "account") => allows(access, permission, scope),
    access,
  };
}
