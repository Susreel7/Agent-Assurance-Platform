import { Link, useParams } from "react-router-dom";
import { useAccreditation } from "@/api/queries";
import type { AccreditationControl, AccreditationTransition } from "@/api/types";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { Digest } from "@/components/Digest";
import { ErrorState } from "@/components/ErrorState";
import { Panel } from "@/components/Panel";
import { Principal } from "@/components/Principal";
import { AccreditationStateBadge } from "@/components/StateBadge";
import { Skeleton } from "@/components/Skeleton";
import { Urn } from "@/components/Urn";
import { formatTableDate } from "@/lib/dates";
import { titleCaseSnake } from "@/lib/formatters";

function signatureTone(status: "valid" | "invalid" | "unsigned"): string {
  if (status === "valid") return "text-ok-fg bg-ok-bg";
  if (status === "invalid") return "text-risk-fg bg-risk-bg";
  return "text-mute-fg bg-mute-bg";
}

export default function AccreditationDetailScreen() {
  const { accreditationId = "" } = useParams();
  const query = useAccreditation(accreditationId);

  if (query.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton height="2rem" width="50%" />
        <Skeleton height="12rem" />
      </div>
    );
  }

  if (query.isError || !query.data) {
    return (
      <ErrorState
        message={
          query.error instanceof Error ? query.error.message : "Accreditation not found"
        }
        onRetry={() => void query.refetch()}
      />
    );
  }

  const acc = query.data;
  const pack = acc.pack;

  const controlColumns: ColumnDef<AccreditationControl>[] = [
    {
      id: "ref",
      header: "Control",
      sortValue: (c) => c.control_ref,
      accessor: (c) => (
        <div>
          <span className="font-mono-data">{c.control_ref}</span>
          <div className="text-ink-600">{c.title}</div>
        </div>
      ),
    },
    {
      id: "mode",
      header: "Answer mode",
      accessor: (c) => titleCaseSnake(c.answer_mode),
    },
    {
      id: "satisfied",
      header: "Satisfied",
      sortValue: (c) => (c.satisfied ? 1 : 0),
      accessor: (c) =>
        c.satisfied ? (
          <span className="text-ok-fg">Yes</span>
        ) : (
          <span className="text-risk-fg">No</span>
        ),
    },
    {
      id: "evidence",
      header: "Evidence",
      accessor: (c) =>
        c.evidence_event_ids.length ? (
          <ul className="space-y-1">
            {c.evidence_event_ids.map((id) => (
              <li key={id}>
                <Link to="/evidence" className="font-mono-data text-info-fg hover:underline" title={id}>
                  {id.slice(0, 8)}…
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          "—"
        ),
    },
  ];

  const transitionColumns: ColumnDef<AccreditationTransition>[] = [
    {
      id: "from",
      header: "From",
      accessor: (t) => (t.from_state ? titleCaseSnake(t.from_state) : "—"),
    },
    {
      id: "to",
      header: "To",
      accessor: (t) => <AccreditationStateBadge state={t.to_state} />,
    },
    {
      id: "actor",
      header: "Actor",
      accessor: (t) => <Principal principalId={t.actor} />,
    },
    {
      id: "when",
      header: "When",
      sortValue: (t) => t.occurred_at,
      accessor: (t) => formatTableDate(t.occurred_at),
    },
    {
      id: "reason",
      header: "Reason",
      accessor: (t) => t.reason ?? "—",
    },
  ];

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="font-mono-data text-sm text-ink-600">{acc.reference}</p>
          <h1 className="text-lg font-semibold text-ink-900">{acc.framework_name}</h1>
          <p className="mt-1">
            <Link to={`/agents/${acc.agent_id}`}>
              <Urn value={acc.agent_urn} />
            </Link>
          </p>
          <p className="text-table text-ink-600">
            Customer {acc.customer_display_name} · version{" "}
            <span className="font-mono-data">{acc.version_semver}</span>
          </p>
        </div>
        <AccreditationStateBadge state={acc.state} />
      </header>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Accreditation pack" className="lg:col-span-1">
          {!pack ? (
            <p className="text-table text-ink-600">No pack rendered yet.</p>
          ) : (
            <dl className="space-y-2 text-table">
              <div>
                <dt className="text-ink-400">Pack URI</dt>
                <dd>
                  <a href={pack.pack_uri} className="text-info-fg hover:underline">
                    Download pack v{pack.version}
                  </a>
                </dd>
              </div>
              <div>
                <dt className="text-ink-400">Digest</dt>
                <dd>
                  <Digest value={pack.digest} />
                </dd>
              </div>
              <div>
                <dt className="text-ink-400">Rendered</dt>
                <dd>{formatTableDate(pack.rendered_at)}</dd>
              </div>
              <div>
                <dt className="text-ink-400">Signature</dt>
                <dd>
                  <span
                    className={`rounded-sm px-2 py-0.5 text-xs font-medium ${signatureTone(pack.signature_status)}`}
                  >
                    {titleCaseSnake(pack.signature_status)}
                  </span>
                </dd>
              </div>
            </dl>
          )}
        </Panel>

        <Panel title="State history" className="lg:col-span-2" noPadding>
          <DataTable
            columns={transitionColumns}
            data={acc.transitions}
            rowKey={(t) => `${t.occurred_at}-${t.to_state}-${t.actor}`}
            emptyTitle="No transitions recorded"
          />
        </Panel>
      </div>

      <Panel title="Controls" noPadding>
        <DataTable
          columns={controlColumns}
          data={acc.controls}
          rowKey={(c) => c.control_ref}
          emptyTitle="No controls"
        />
      </Panel>
    </div>
  );
}
