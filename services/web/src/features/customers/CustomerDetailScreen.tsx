import { Link, useParams } from "react-router-dom";
import { useCustomer, useCustomerReadiness } from "@/api/queries";
import { DataTable, type ColumnDef } from "@/components/DataTable";
import { ErrorState } from "@/components/ErrorState";
import { Panel } from "@/components/Panel";
import { Principal } from "@/components/Principal";
import { Skeleton } from "@/components/Skeleton";
import { formatPercent, titleCaseSnake } from "@/lib/formatters";
import { ReadinessPanel } from "./ReadinessPanel";

export default function CustomerDetailScreen() {
  const { customerId = "" } = useParams();
  const customerQuery = useCustomer(customerId);
  const readinessQuery = useCustomerReadiness(customerId);

  if (customerQuery.isLoading) {
    return (
      <div className="space-y-4">
        <Skeleton height="2rem" width="50%" />
        <Skeleton height="8rem" />
        <Skeleton height="16rem" />
      </div>
    );
  }

  if (customerQuery.isError || !customerQuery.data) {
    return (
      <ErrorState
        message={
          customerQuery.error instanceof Error ? customerQuery.error.message : "Customer not found"
        }
        onRetry={() => void customerQuery.refetch()}
      />
    );
  }

  const customer = customerQuery.data;

  const frameworkColumns: ColumnDef<(typeof customer.frameworks)[number]>[] = [
    {
      id: "framework",
      header: "Framework",
      sortValue: (r) => r.framework.name,
      accessor: (r) => r.framework.name,
    },
    {
      id: "level",
      header: "Requirement level",
      sortValue: (r) => r.level,
      accessor: (r) => titleCaseSnake(r.level),
    },
    {
      id: "controls",
      header: "Controls",
      align: "right",
      sortValue: (r) => r.framework.control_count,
      accessor: (r) => <span className="tabular-nums">{r.framework.control_count}</span>,
    },
    {
      id: "since",
      header: "Required since",
      accessor: (r) => r.required_since ?? "—",
    },
  ];

  return (
    <div className="space-y-4">
      <header className="space-y-1">
        <p className="text-xs text-ink-400">{customer.slug}</p>
        <h1 className="text-lg font-semibold text-ink-900">{customer.display_name}</h1>
        <p className="text-table text-ink-600">
          {titleCaseSnake(customer.status)} · {customer.sector ? titleCaseSnake(customer.sector) : "Sector unknown"} ·{" "}
          {titleCaseSnake(customer.criticality)}
        </p>
      </header>

      <div className="grid gap-4 lg:grid-cols-3">
        <Panel title="Profile" className="lg:col-span-1">
          <dl className="space-y-2 text-table">
            <div>
              <dt className="text-ink-400">Home jurisdiction</dt>
              <dd>{customer.home_jurisdiction ?? "—"}</dd>
            </div>
            <div>
              <dt className="text-ink-400">Engagements</dt>
              <dd className="tabular-nums">
                <Link to="/engagements" className="text-info-fg hover:underline">
                  {customer.engagement_count}
                </Link>
              </dd>
            </div>
            <div>
              <dt className="text-ink-400">Agents in scope</dt>
              <dd className="tabular-nums">{customer.agent_count}</dd>
            </div>
            <div>
              <dt className="text-ink-400">Accreditation drift</dt>
              <dd className="tabular-nums">{customer.drift_count} agents</dd>
            </div>
          </dl>
        </Panel>

        <div className="lg:col-span-2">
          <ReadinessPanel
            headline={readinessQuery.data?.headline}
            coveragePct={readinessQuery.data?.coverage_pct}
            frameworks={readinessQuery.data?.readiness.frameworks}
            gaps={readinessQuery.data?.readiness.gaps}
            isLoading={readinessQuery.isLoading}
            isError={readinessQuery.isError}
            errorMessage={
              readinessQuery.error instanceof Error ? readinessQuery.error.message : null
            }
            onRetry={() => void readinessQuery.refetch()}
          />
        </div>
      </div>

      <Panel title="Required frameworks" noPadding>
        <DataTable
          columns={frameworkColumns}
          data={customer.frameworks}
          rowKey={(r) => r.id}
          emptyTitle="No frameworks"
          emptyDescription="This customer has no mapped assurance frameworks yet."
        />
      </Panel>

      {customer.contacts.length > 0 ? (
        <Panel title="Contacts" noPadding>
          <DataTable
            columns={[
              {
                id: "role",
                header: "Role",
                sortValue: (c) => c.role,
                accessor: (c) => titleCaseSnake(c.role),
              },
              {
                id: "name",
                header: "Name",
                accessor: (c) => c.display_name ?? "—",
              },
              {
                id: "principal",
                header: "Principal",
                accessor: (c) => <Principal principalId={c.principal_id} />,
              },
            ]}
            data={customer.contacts}
            rowKey={(c) => c.id}
            emptyTitle="No contacts"
          />
        </Panel>
      ) : null}

      {readinessQuery.data ? (
        <p className="text-xs text-ink-400">
          Readiness headline: {formatPercent(readinessQuery.data.coverage_pct)} of required controls
          answerable with evidence.
        </p>
      ) : null}
    </div>
  );
}
