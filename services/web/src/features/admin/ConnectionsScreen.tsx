/**
 * Provider credentials — the customer's own API keys, governed without being held.
 *
 * Nothing on this screen can reveal a key, because nothing in this product stores one. The
 * columns that matter are the fingerprint prefix, which is how you confirm a rotation
 * actually changed the material, and the grant count, which is how you tell a credential
 * somebody registered from one an agent can actually reach.
 */

import { useState } from "react";
import { useConnections } from "@/api/platformQueries";
import { Can } from "@/components/Can";
import { ErrorState } from "@/components/ErrorState";
import { Icon } from "@/components/Icon";
import { Panel } from "@/components/Panel";
import { ConnectionStatusBadge } from "@/components/PlatformBadge";
import { RelativeTime } from "@/components/RelativeTime";
import { Skeleton } from "@/components/Skeleton";
import { Stat } from "@/components/Stat";
import { Badge, LifecycleStateBadge } from "@/components/StateBadge";
import { titleCaseSnake } from "@/lib/formatters";
import { ConnectionCreateForm, ConnectionRotatePanel } from "./ConnectionForms";

export default function ConnectionsScreen() {
  const [creating, setCreating] = useState(false);
  const [rotatingId, setRotatingId] = useState<string | null>(null);
  const [includeDisabled, setIncludeDisabled] = useState(false);

  const connections = useConnections({ limit: 100, include_disabled: includeDisabled });

  if (connections.isPending) {
    return (
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} height="104px" />
          ))}
        </div>
        <Skeleton height="340px" />
      </div>
    );
  }

  if (connections.isError || !connections.data) {
    return (
      <ErrorState
        title="Could not load connections"
        message={connections.error instanceof Error ? connections.error.message : "Unknown error"}
        onRetry={() => void connections.refetch()}
      />
    );
  }

  const rows = connections.data.items;
  const overdue = rows.filter((row) => row.rotation_overdue);
  const ungranted = rows.filter((row) => row.grant_count === 0);

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <Stat
          label="Connections"
          value={connections.data.total.toLocaleString()}
          explain="provider credentials under governance"
          icon="key"
        />
        <Stat
          label="Rotation overdue"
          value={String(overdue.length)}
          explain="past the date somebody set"
          icon="refresh"
          iconTint={overdue.length > 0 ? "warn" : "ok"}
          tone={overdue.length > 0 ? "warn" : "ok"}
        />
        <Stat
          label="Granted to nobody"
          value={String(ungranted.length)}
          explain="registered, but no agent can reach them"
          icon="plug"
          iconTint="info"
        />
      </div>

      {overdue.length > 0 ? (
        <div className="flex items-start gap-3 rounded-card bg-warn-bg px-4 py-3 text-body text-warn-fg shadow-card">
          <Icon name="alert" size={18} className="mt-0.5 shrink-0" />
          <p>
            <strong className="font-semibold">
              {overdue.length} credential{overdue.length === 1 ? "" : "s"}
            </strong>{" "}
            {overdue.length === 1 ? "is" : "are"} past the rotation date recorded for{" "}
            {overdue.length === 1 ? "it" : "them"}. Rotating here records the change; the key
            itself moves in your own secret store.
          </p>
        </div>
      ) : null}

      <Panel
        title="Provider connections"
        explain="Registered as references into your secret provider, so the platform governs the key without ever holding it."
        noPadding
        toolbar={
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setIncludeDisabled((value) => !value)}
              aria-pressed={includeDisabled}
              className={`rounded-md px-2.5 py-1 text-table transition-colors ${
                includeDisabled
                  ? "bg-accent text-white"
                  : "bg-bg-sunk text-ink-600 hover:bg-bg-hover hover:text-ink-900"
              }`}
            >
              Include disabled
            </button>
            <Can permission="connection:write">
              <button
                type="button"
                onClick={() => setCreating((open) => !open)}
                className="rounded-md bg-accent px-2.5 py-1 text-table font-medium text-white transition-colors hover:bg-accent-hover"
              >
                Register
              </button>
            </Can>
          </div>
        }
      >
        {creating ? (
          <div className="border-b border-line-200 px-4 py-4">
            <ConnectionCreateForm onDone={() => setCreating(false)} />
          </div>
        ) : null}

        {rotatingId ? (
          <ConnectionRotatePanel connectionId={rotatingId} onDone={() => setRotatingId(null)} />
        ) : null}

        <div className="overflow-x-auto scrollbar-thin">
          <table className="min-w-[960px]">
            <thead>
              <tr>
                <th className="px-3 py-2">Connection</th>
                <th className="px-3 py-2">Provider</th>
                <th className="px-3 py-2">Status</th>
                <th className="px-3 py-2">Environments</th>
                <th className="px-3 py-2">Owner</th>
                <th className="px-3 py-2 text-right">Granted to</th>
                <th className="px-3 py-2 text-right">Version</th>
                <th className="px-3 py-2">Last used</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.connection.id} className="hover:bg-bg-hover">
                  <td className="px-3 py-2">
                    <span className="flex items-center gap-2">
                      <Icon name="key" size={15} className="shrink-0 text-ink-400" />
                      <span className="min-w-0">
                        <span className="block truncate font-medium text-ink-900">
                          {row.connection.name}
                        </span>
                        <span className="block truncate font-mono-data text-micro text-ink-400">
                          {row.connection.slug}
                        </span>
                      </span>
                    </span>
                  </td>
                  <td className="px-3 py-2 text-ink-700">
                    {titleCaseSnake(row.connection.provider_kind)}
                    <span className="ml-1.5 text-micro text-ink-400">
                      {titleCaseSnake(row.connection.auth_kind)}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <ConnectionStatusBadge status={row.connection.status} />
                  </td>
                  <td className="px-3 py-2">
                    <span className="flex flex-wrap gap-1">
                      {row.connection.environments.map((environment) => (
                        <LifecycleStateBadge key={environment} state={environment} />
                      ))}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-ink-600">
                    {row.connection.personal_member_id ? (
                      <Badge label="Personal" tone="info" />
                    ) : (
                      (row.owner_team_name ?? "—")
                    )}
                  </td>
                  {/* Zero here is the interesting value: a credential nothing can use. */}
                  <td
                    className={`px-3 py-2 text-right font-mono tabular-nums ${
                      row.grant_count === 0 ? "text-ink-300" : "text-ink-700"
                    }`}
                  >
                    {row.grant_count}
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-ink-600">
                    {row.active_version === null ? "—" : `v${row.active_version}`}
                  </td>
                  <td className="px-3 py-2 text-ink-600">
                    {row.connection.last_used_at ? (
                      <RelativeTime iso={row.connection.last_used_at} />
                    ) : (
                      <span className="text-micro text-ink-300">never</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Can permission="connection:rotate">
                      <button
                        type="button"
                        onClick={() =>
                          setRotatingId((current) =>
                            current === row.connection.id ? null : row.connection.id,
                          )
                        }
                        className={`rounded-md px-2 py-1 text-micro font-medium transition-colors hover:bg-bg-hover ${
                          row.rotation_overdue ? "text-warn-fg" : "text-ink-600 hover:text-ink-900"
                        }`}
                      >
                        Rotate
                      </button>
                    </Can>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {rows.length === 0 ? (
          <p className="px-4 py-10 text-center text-body text-ink-400">
            No provider connection is registered. Until one is, the gateway has nothing to route
            to.
          </p>
        ) : null}
      </Panel>
    </div>
  );
}
