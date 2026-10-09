/**
 * Console sign-in. Replaces `oidc.ts`, which did all of this in the browser.
 *
 * What the browser still does: generate a PKCE verifier, a state and a nonce, and
 * navigate to the provider's authorize URL. None of those are credentials — the verifier
 * is single-use and worthless without the authorization code it is paired with — so
 * `sessionStorage` is the right place for them and the wrong place for a token.
 *
 * What the browser no longer does: talk to the token endpoint, decode an id token with
 * `atob` and believe it, or hold an access token. `atob` reads a signature it cannot
 * check. The exchange and the verification happen in `POST /v1/auth/session`, and what
 * comes back is a `Set-Cookie` this file cannot read.
 *
 * There is no `VITE_OIDC_*` here and there must not be. Build-time identity
 * configuration is how a deployment ended up rendering a sign-in button for a provider
 * that was never configured; `inv_no_build_time_auth` keeps it from returning.
 */

import { api } from "@/api/client";

const PKCE_KEY = "aap.login.pkce";

export type AuthProvider = {
  id: string;
  kind: "oidc" | "development";
  label: string;
  authorize_url: string | null;
  client_id: string | null;
  scopes: string;
  pkce: boolean;
  onboarding_mode: string;
};

export type AuthConfig = {
  account_hint: string | null;
  providers: AuthProvider[];
  unavailable_reason: string | null;
  development: boolean;
};

export type StartedSession = {
  session_id: string;
  member_id: string;
  account_id: string;
  email: string;
  display_name: string;
  issued_at: string;
  expires_at: string;
  absolute_expires_at: string;
};

type PendingLogin = {
  providerId: string;
  verifier: string;
  state: string;
  nonce: string;
  redirectUri: string;
  returnTo: string;
};

export function authConfig(emailDomain?: string): Promise<AuthConfig> {
  return api.get<AuthConfig>("/v1/auth/config", emailDomain ? { email_domain: emailDomain } : undefined);
}

function base64Url(bytes: Uint8Array): string {
  let binary = "";
  bytes.forEach((b) => {
    binary += String.fromCharCode(b);
  });
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function sha256(input: string): Promise<Uint8Array> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(input));
  return new Uint8Array(digest);
}

function randomString(bytes = 32): string {
  const arr = new Uint8Array(bytes);
  crypto.getRandomValues(arr);
  return base64Url(arr);
}

function redirectUri(): string {
  return `${window.location.origin}/login/callback`;
}

function remember(pending: PendingLogin): void {
  try {
    sessionStorage.setItem(PKCE_KEY, JSON.stringify(pending));
  } catch {
    // Private browsing. The sign-in will fail on the callback with a specific reason,
    // which is better than failing here with a storage error the user cannot act on.
  }
}

function takePending(): PendingLogin | null {
  try {
    const raw = sessionStorage.getItem(PKCE_KEY);
    sessionStorage.removeItem(PKCE_KEY);
    return raw ? (JSON.parse(raw) as PendingLogin) : null;
  } catch {
    return null;
  }
}

export function forgetPendingLogin(): void {
  try {
    sessionStorage.removeItem(PKCE_KEY);
  } catch {
    /* nothing to forget */
  }
}

/**
 * Send the browser to the provider. Returns only if it could not.
 *
 * The authorize URL, client id and scopes come from `/v1/auth/config`, so a deployment
 * changes its identity provider by changing a row — not by rebuilding the console.
 */
export async function beginLogin(provider: AuthProvider, returnTo = "/"): Promise<void> {
  if (!provider.authorize_url || !provider.client_id) {
    throw new Error(`${provider.label} is missing an authorize URL or client id.`);
  }

  const verifier = randomString(64);
  const pending: PendingLogin = {
    providerId: provider.id,
    verifier,
    state: randomString(24),
    nonce: randomString(24),
    redirectUri: redirectUri(),
    returnTo,
  };
  remember(pending);

  const authorize = new URL(provider.authorize_url);
  authorize.searchParams.set("client_id", provider.client_id);
  authorize.searchParams.set("response_type", "code");
  authorize.searchParams.set("redirect_uri", pending.redirectUri);
  authorize.searchParams.set("response_mode", "query");
  authorize.searchParams.set("scope", provider.scopes);
  authorize.searchParams.set("state", pending.state);
  authorize.searchParams.set("nonce", pending.nonce);
  authorize.searchParams.set("code_challenge", base64Url(await sha256(verifier)));
  authorize.searchParams.set("code_challenge_method", "S256");
  window.location.assign(authorize.toString());
}

/** The local stub. Only offered when the server says this is a development install. */
export function beginDevelopmentLogin(
  provider: AuthProvider,
  email: string,
): Promise<StartedSession> {
  return api.post<StartedSession>("/v1/auth/session", {
    provider_id: provider.id,
    email,
  });
}

export type CallbackResult = { session: StartedSession; returnTo: string };

/**
 * Finish a redirect sign-in.
 *
 * `state` is compared here, before anything is sent to the server: it is the browser's
 * own check that this response belongs to the request this tab started, and the server
 * has no way to make it.
 */
export async function completeLogin(params: URLSearchParams): Promise<CallbackResult> {
  const pending = takePending();
  const error = params.get("error");
  if (error) {
    throw new Error(params.get("error_description") ?? `The identity provider refused: ${error}`);
  }

  const code = params.get("code");
  const state = params.get("state");
  if (!pending) {
    throw new Error("This sign-in was started in another tab or has already been used.");
  }
  if (!code || !state || state !== pending.state) {
    throw new Error("This sign-in response does not match the sign-in this tab started.");
  }

  const session = await api.post<StartedSession>("/v1/auth/session", {
    provider_id: pending.providerId,
    code,
    code_verifier: pending.verifier,
    redirect_uri: pending.redirectUri,
    nonce: pending.nonce,
  });
  return { session, returnTo: pending.returnTo || "/" };
}

export async function logout(): Promise<void> {
  await api.post<void>("/v1/auth/logout");
}
