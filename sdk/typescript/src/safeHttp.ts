const SENSITIVE_HEADER_PREFIXES = ["authorization", "cookie", "set-cookie", "x-api-key"];

export interface SafeHttpUrlParts {
  scheme: string;
  host: string;
  route: string;
}

/** Strip credentials, query strings, and fragments from a URL. */
export function safeHttpUrl(rawUrl: string): SafeHttpUrlParts | null {
  try {
    const parsed = new URL(rawUrl);
    parsed.username = "";
    parsed.password = "";
    parsed.search = "";
    parsed.hash = "";
    const route = parsed.pathname || "/";
    return {
      scheme: parsed.protocol.replace(/:$/, ""),
      host: parsed.host,
      route,
    };
  } catch {
    return null;
  }
}

export function isSensitiveHeaderName(name: string): boolean {
  const lower = name.toLowerCase();
  return SENSITIVE_HEADER_PREFIXES.some(
    (prefix) => lower === prefix || lower.startsWith(`${prefix}-`),
  );
}

export function safeHttpAttributes(
  method: string,
  url: string,
  options?: {
    statusCode?: number;
    peerService?: string;
    latencyMs?: number;
  },
): Record<string, unknown> {
  const parts = safeHttpUrl(url);
  const attrs: Record<string, unknown> = {
    "gen_ai.operation.name": "http",
    "aap.observation.type": "http",
    "http.request.method": method.toUpperCase(),
  };
  if (parts) {
    attrs["url.scheme"] = parts.scheme;
    attrs["server.address"] = parts.host;
    attrs["http.route"] = parts.route;
  }
  if (options?.statusCode !== undefined) {
    attrs["http.response.status_code"] = options.statusCode;
  }
  if (options?.peerService) {
    attrs["peer.service"] = options.peerService;
  }
  if (options?.latencyMs !== undefined) {
    attrs["http.client.request.duration_ms"] = options.latencyMs;
  }
  return attrs;
}
