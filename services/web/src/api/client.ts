const API_BASE = import.meta.env.VITE_API_BASE ?? "";

// There used to be a second mode here, backed by ~2,600 lines of hand-written fixtures
// under src/mocks, and it is worth saying why it is gone.
//
// The fixtures mirrored 125 API routes by hand, so they were a second, independent
// account of the same contract — and they disagreed with it. Fifteen request paths and
// roughly a dozen response shapes were wrong in both places at once, which is the part
// that mattered: the console looked completely healthy in mock mode and returned 404s
// and blank tables against a real backend. A fake that agrees with your mistakes is
// worse than no fake at all, because it removes the feedback that would have caught them.
//
// The justification for keeping it was frontend work without a backend. `docker compose
// up` now starts Postgres, the API and Vite with hot reload in one command, so that cost
// is gone. The contract is checked instead: `npm run client` generates types from the
// spec and `npm run check:api` fails the build on a path the API does not serve.
export const isLive = true;

/**
 * The reason codes the API may return. Mirrors `Reason` in
 * `services/api/app/api/errors.py`; `design/02-identity-and-onboarding.md` is the
 * authority for what each one means.
 *
 * A union rather than an enum so an unrecognised code from a newer API still type-checks
 * as a string and still renders — a console that crashes on a reason it has not been
 * taught about is worse than one that shows the server's sentence.
 */
export type Reason =
  | "session_expired"
  | "not_authenticated"
  | "not_provisioned"
  | "provider_disabled"
  | "provider_unknown"
  | "provider_not_configured"
  | "invalid_credential"
  | "membership_suspended"
  | "mfa_required"
  | "module_forbidden"
  | "module_not_entitled"
  | "scope_outside_grant"
  | "approval_pending"
  | "policy_denied"
  | "bundle_stale"
  | "invalid_request"
  | "not_found"
  | "conflict"
  | "precondition_failed"
  | "rate_limited"
  | "licence_read_only"
  | "upstream_unavailable"
  | "identity_provider_unavailable"
  | "internal_error"
  | (string & {});

/** The action the console offers as a button under the message. */
export type NextActionKind =
  | "sign_in"
  | "retry"
  | "request_access"
  | "contact_owner"
  | "reauthenticate"
  | "open_request"
  | "configure_provider"
  | "none"
  | (string & {});

export type ErrorEnvelope = {
  reason: Reason;
  message: string;
  detail: Record<string, unknown>;
  next: { kind: NextActionKind } & Record<string, unknown>;
  request_id: string;
};

/**
 * A failed request, carrying everything the UI needs to explain it.
 *
 * `reason` is the field screens branch on and `message` is the sentence they show. The
 * old shape was a status code and a free-text `detail`, which is why every failure in
 * the console rendered as "Something went wrong · Try again" — there was nothing else to
 * render.
 *
 * `requestId` is on here because a screenshot of an error should be enough to find the
 * server-side log line that produced it.
 */
export class ApiError extends Error {
  readonly status: number;
  readonly reason: Reason;
  readonly detail: Record<string, unknown>;
  readonly next: NextActionKind;
  readonly requestId: string;

  constructor(status: number, envelope: ErrorEnvelope) {
    super(envelope.message);
    this.name = "ApiError";
    this.status = status;
    this.reason = envelope.reason;
    this.detail = envelope.detail ?? {};
    this.next = envelope.next?.kind ?? "none";
    this.requestId = envelope.request_id ?? "";
  }
}

async function parseBody(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!text) return null;
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return text;
  }
}

/**
 * Read the envelope, or synthesise one.
 *
 * A response that is not an envelope means something in front of the API answered — a
 * proxy 502, a load balancer HTML page, a network stack that produced no body at all.
 * Those are real failures the user still has to see, so they become an envelope here
 * rather than an exception with no reason on it.
 */
function envelopeFrom(status: number, body: unknown, requestId: string): ErrorEnvelope {
  if (body && typeof body === "object" && "reason" in body && "message" in body) {
    const found = body as ErrorEnvelope;
    return { ...found, request_id: found.request_id || requestId };
  }
  return {
    reason: status >= 500 ? "upstream_unavailable" : "invalid_request",
    message:
      status >= 500
        ? "The server did not answer. This is not something you did."
        : `The request was refused (${status}).`,
    detail: typeof body === "string" && body.length < 500 ? { body } : {},
    next: { kind: status >= 500 ? "retry" : "none" },
    request_id: requestId,
  };
}

async function request<T>(
  method: string,
  path: string,
  options?: { search?: Record<string, string | string[] | undefined>; body?: unknown },
): Promise<T> {
  const url = new URL(`${API_BASE}${path}`, window.location.origin);
  if (options?.search) {
    for (const [key, val] of Object.entries(options.search)) {
      if (val === undefined) continue;
      if (Array.isArray(val)) val.forEach((v) => url.searchParams.append(key, v));
      else url.searchParams.set(key, val);
    }
  }

  const headers: Record<string, string> = {};
  if (options?.body) headers["Content-Type"] = "application/json";

  // The credential is an HttpOnly cookie the server set, so there is nothing to attach
  // here and nothing for this file to read. That is the point: a token this code could
  // put in a header is a token this code could leak, and the previous version kept one
  // in `sessionStorage` where any script on the page could take it.
  const res = await fetch(url.toString(), {
    method,
    headers,
    credentials: "same-origin",
    body: options?.body ? JSON.stringify(options.body) : undefined,
  });
  const body = await parseBody(res);
  if (!res.ok) {
    throw new ApiError(res.status, envelopeFrom(res.status, body, res.headers.get("X-Request-Id") ?? ""));
  }
  return body as T;
}

export const api = {
  get<T>(path: string, search?: Record<string, string | string[] | undefined>): Promise<T> {
    return request<T>("GET", path, { search });
  },
  post<T>(path: string, body?: unknown, search?: Record<string, string | string[] | undefined>): Promise<T> {
    return request<T>("POST", path, { body, search });
  },
  put<T>(path: string, body?: unknown): Promise<T> {
    return request<T>("PUT", path, { body });
  },
  patch<T>(path: string, body?: unknown): Promise<T> {
    return request<T>("PATCH", path, { body });
  },
  del<T>(path: string): Promise<T> {
    return request<T>("DELETE", path);
  },
};
