/**
 * The two forms on the credentials screen: register, and rotate.
 *
 * Split out of `ConnectionsScreen` because both are long, stateful, and only rendered when
 * an operator asks for them — keeping them here means the list screen reads as a list.
 *
 * Neither form has a field for a key, and that is the design. What is recorded is a
 * `credential_ref`: a Vault path, a KMS key id, or an environment variable name locally.
 * The gateway exchanges that reference for material through its own secret provider at call
 * time, so somebody may hold `connection:write` and rotate a credential they are not
 * permitted to read.
 */

import { useState } from "react";
import {
  useConnectionVersions,
  useCreateConnection,
  useRotateConnection,
} from "@/api/platformQueries";
import { MutationBanner } from "@/components/MutationBanner";
import { RelativeTime } from "@/components/RelativeTime";
import { Badge } from "@/components/StateBadge";
import { titleCaseSnake } from "@/lib/formatters";
import type { AuthKind, LifecycleState, ProviderKind } from "@/api/platformTypes";

const PROVIDERS: ProviderKind[] = [
  "openai",
  "anthropic",
  "azure_openai",
  "bedrock",
  "vertex",
  "mistral",
  "cohere",
  "vllm",
  "ollama",
  "mcp_http",
  "custom",
];

/** Providers reached at an address you choose rather than a published one. */
const NEEDS_ENDPOINT = new Set<ProviderKind>(["vllm", "ollama", "custom", "mcp_http"]);

const AUTH_KINDS: AuthKind[] = [
  "api_key",
  "oauth_client",
  "iam_role",
  "mtls",
  "workload_identity",
  "none",
];

const ENVIRONMENTS: LifecycleState[] = ["dev", "test", "staging", "production"];

const FIELD =
  "rounded-md border border-line-200 bg-bg-panel px-2.5 py-1.5 text-table text-ink-900";
const MONO_FIELD = `${FIELD} font-mono-data`;
const PRIMARY =
  "rounded-md bg-accent px-3 py-1.5 text-table font-medium text-white transition-colors hover:bg-accent-hover disabled:opacity-50";
const GHOST = "rounded-md px-3 py-1.5 text-table text-ink-600 transition-colors hover:bg-bg-hover";

export function ConnectionCreateForm({ onDone }: { onDone: () => void }) {
  const create = useCreateConnection();
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [providerKind, setProviderKind] = useState<ProviderKind>("openai");
  const [authKind, setAuthKind] = useState<AuthKind>("api_key");
  const [credentialRef, setCredentialRef] = useState("");
  const [endpointUrl, setEndpointUrl] = useState("");
  const [environments, setEnvironments] = useState<LifecycleState[]>(["dev"]);
  const [personal, setPersonal] = useState(false);

  const needsEndpoint = NEEDS_ENDPOINT.has(providerKind);
  // Enforced by a check constraint too. Surfacing it here means the operator meets the rule
  // while choosing rather than in a 400 after filling the whole form in.
  const productionBlocked = personal && environments.includes("production");

  return (
    <form
      className="grid gap-3 sm:grid-cols-2"
      onSubmit={(event) => {
        event.preventDefault();
        create.mutate(
          {
            slug,
            name,
            provider_kind: providerKind,
            auth_kind: authKind,
            credential_ref: authKind === "none" ? "none" : credentialRef,
            endpoint_url: needsEndpoint ? endpointUrl : null,
            environments,
            personal,
          },
          { onSuccess: onDone },
        );
      }}
    >
      <label className="flex flex-col gap-1">
        <span className="text-micro font-medium text-ink-600">Name</span>
        <input
          required
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Anthropic — platform team"
          className={FIELD}
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-micro font-medium text-ink-600">Slug</span>
        <input
          required
          pattern="[a-z0-9][a-z0-9-]*"
          value={slug}
          onChange={(event) => setSlug(event.target.value)}
          placeholder="anthropic-platform"
          className={MONO_FIELD}
        />
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-micro font-medium text-ink-600">Provider</span>
        <select
          value={providerKind}
          onChange={(event) => setProviderKind(event.target.value as ProviderKind)}
          className={FIELD}
        >
          {PROVIDERS.map((kind) => (
            <option key={kind} value={kind}>
              {titleCaseSnake(kind)}
            </option>
          ))}
        </select>
      </label>

      <label className="flex flex-col gap-1">
        <span className="text-micro font-medium text-ink-600">How it authenticates</span>
        <select
          value={authKind}
          onChange={(event) => setAuthKind(event.target.value as AuthKind)}
          className={FIELD}
        >
          {AUTH_KINDS.map((kind) => (
            <option key={kind} value={kind}>
              {titleCaseSnake(kind)}
            </option>
          ))}
        </select>
      </label>

      {authKind === "none" ? null : (
        <label className="flex flex-col gap-1 sm:col-span-2">
          <span className="text-micro font-medium text-ink-600">
            Credential reference — a pointer, never the key itself
          </span>
          <input
            required
            value={credentialRef}
            onChange={(event) => setCredentialRef(event.target.value)}
            placeholder="vault://secret/llm/anthropic#api_key · env:ANTHROPIC_API_KEY"
            className={MONO_FIELD}
          />
          <span className="text-micro text-ink-400">
            The gateway resolves this through your own secret provider at call time. Pasting a
            key here would store a key here, which this product deliberately cannot do.
          </span>
        </label>
      )}

      {needsEndpoint ? (
        <label className="flex flex-col gap-1 sm:col-span-2">
          <span className="text-micro font-medium text-ink-600">Endpoint</span>
          <input
            required
            type="url"
            value={endpointUrl}
            onChange={(event) => setEndpointUrl(event.target.value)}
            placeholder="https://vllm.internal.example.com/v1"
            className={MONO_FIELD}
          />
        </label>
      ) : null}

      <fieldset className="sm:col-span-2">
        <legend className="mb-1.5 text-micro font-medium text-ink-600">
          Usable in which environments
        </legend>
        <div className="flex flex-wrap gap-3">
          {ENVIRONMENTS.map((environment) => (
            <label key={environment} className="flex items-center gap-1.5 text-table text-ink-700">
              <input
                type="checkbox"
                checked={environments.includes(environment)}
                onChange={(event) =>
                  setEnvironments((current) =>
                    event.target.checked
                      ? [...current, environment]
                      : current.filter((entry) => entry !== environment),
                  )
                }
              />
              {titleCaseSnake(environment)}
            </label>
          ))}
        </div>
      </fieldset>

      <label className="sm:col-span-2 flex items-start gap-2 text-table text-ink-700">
        <input
          type="checkbox"
          checked={personal}
          onChange={(event) => setPersonal(event.target.checked)}
          className="mt-1"
        />
        <span>
          This is my own developer key
          <span className="block text-micro text-ink-400">
            A personal connection cannot be used in production, and only its owner&rsquo;s agents
            may resolve it.
          </span>
        </span>
      </label>

      {productionBlocked ? (
        <p className="sm:col-span-2 text-micro text-risk-fg">
          A personal key cannot carry production traffic. Uncheck one or the other.
        </p>
      ) : null}

      <div className="sm:col-span-2 flex items-center gap-2">
        <button
          type="submit"
          disabled={create.isPending || environments.length === 0 || productionBlocked}
          className={PRIMARY}
        >
          {create.isPending ? "Registering…" : "Register connection"}
        </button>
        <button type="button" onClick={onDone} className={GHOST}>
          Cancel
        </button>
      </div>

      {create.isError ? (
        <div className="sm:col-span-2">
          <MutationBanner
            tone="error"
            message={create.error instanceof Error ? create.error.message : "Could not register"}
            onDismiss={() => create.reset()}
          />
        </div>
      ) : null}
    </form>
  );
}

/**
 * Rotation asks for a SHA-256 of the new key rather than the key.
 *
 * The digest proves the material actually changed: an operator who "rotates" by re-entering
 * the same value produces the same fingerprint, and the form says so before the write.
 */
export function ConnectionRotatePanel({
  connectionId,
  onDone,
}: {
  connectionId: string;
  onDone: () => void;
}) {
  const versions = useConnectionVersions(connectionId);
  const rotate = useRotateConnection(connectionId);
  const [credentialRef, setCredentialRef] = useState("");
  const [fingerprint, setFingerprint] = useState("");
  const [retirePrevious, setRetirePrevious] = useState(true);

  const active = (versions.data ?? []).find(
    (version) => version.activated_at && !version.retired_at,
  );
  const unchanged =
    active !== undefined &&
    fingerprint.length === 64 &&
    fingerprint.toLowerCase().startsWith(active.fingerprint_prefix);

  return (
    <div className="border-b border-line-200 px-4 py-4">
      <form
        className="grid gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          rotate.mutate(
            {
              credential_ref: credentialRef,
              fingerprint_hex: fingerprint.toLowerCase(),
              retire_previous: retirePrevious,
            },
            { onSuccess: onDone },
          );
        }}
      >
        <label className="flex flex-col gap-1">
          <span className="text-micro font-medium text-ink-600">New credential reference</span>
          <input
            required
            value={credentialRef}
            onChange={(event) => setCredentialRef(event.target.value)}
            className={MONO_FIELD}
          />
        </label>

        <label className="flex flex-col gap-1">
          <span className="text-micro font-medium text-ink-600">
            SHA-256 of the new material, in hex
          </span>
          <input
            required
            pattern="[0-9a-fA-F]{64}"
            value={fingerprint}
            onChange={(event) => setFingerprint(event.target.value)}
            placeholder="64 hex characters"
            className={MONO_FIELD}
          />
          <span className="text-micro text-ink-400">
            Proof the key changed, not the key. Compute it where the key lives.
          </span>
        </label>

        <label className="flex items-center gap-2 text-table text-ink-700">
          <input
            type="checkbox"
            checked={retirePrevious}
            onChange={(event) => setRetirePrevious(event.target.checked)}
          />
          Retire the previous version immediately
        </label>

        {unchanged ? (
          <p className="text-micro text-warn-fg">
            That fingerprint matches the version already active. Rotating to the same material
            changes nothing.
          </p>
        ) : null}

        <div className="flex items-center gap-2">
          <button type="submit" disabled={rotate.isPending} className={PRIMARY}>
            {rotate.isPending ? "Rotating…" : "Rotate"}
          </button>
          <button type="button" onClick={onDone} className={GHOST}>
            Cancel
          </button>
        </div>

        {rotate.isError ? (
          <MutationBanner
            tone="error"
            message={rotate.error instanceof Error ? rotate.error.message : "Could not rotate"}
            onDismiss={() => rotate.reset()}
          />
        ) : null}
      </form>

      {(versions.data ?? []).length > 0 ? (
        <div className="mt-4">
          <p className="mb-1.5 text-micro font-semibold uppercase tracking-wide text-ink-400">
            Version history
          </p>
          <ul className="flex flex-col gap-1">
            {(versions.data ?? []).map((version) => (
              <li
                key={version.id}
                className="flex flex-wrap items-center gap-2 text-table text-ink-600"
              >
                <span className="font-mono tabular-nums text-ink-900">
                  v{version.version_number}
                </span>
                <span className="font-mono-data text-micro text-ink-400">
                  {version.fingerprint_prefix}…
                </span>
                {version.retired_at ? (
                  <Badge label="Retired" tone="mute" />
                ) : version.activated_at ? (
                  <Badge label="Active" tone="ok" />
                ) : (
                  <Badge label="Staged" tone="info" />
                )}
                <span className="text-micro text-ink-400">
                  <RelativeTime iso={version.created_at} /> by {version.created_by}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
