/**
 * The first screen of a ledger install.
 *
 * Four slots, in the order the MVP argues they matter: how much of the estate we can
 * actually see, what happened that was dangerous, who is running an agent we do not
 * collect from, and what credentials are sitting where an agent can read them.
 *
 * Almost none of it has data yet, and that is the point of the screen as it stands.
 * This is a layout with honest empties, not a dashboard with placeholder numbers — the
 * ingest that fills three of these slots is M3 and the discovery that fills the fourth
 * is M4. A slot renders an em dash and names the slice that will fill it, because a
 * zero is a measurement and we have not taken one. The previous overview was ordered
 * around approvals and framework coverage bars, which is a different product's morning.
 *
 * `HomeScreen.tsx` still exists and is what an assurance-mode install gets. Neither is
 * a fork of the other; they are two products' landing pages, selected by `product_mode`.
 */

import { Link } from "react-router-dom";
import AlertTriangle from "lucide-react/dist/esm/icons/triangle-alert";
import KeyRound from "lucide-react/dist/esm/icons/key-round";
import Radar from "lucide-react/dist/esm/icons/radar";
import ShieldCheck from "lucide-react/dist/esm/icons/shield-check";
import type { ElementType } from "react";
import { useAgents } from "@/api/queries";
import { DataBoundary } from "@/components/DataBoundary";
import { EnforcementGrade, GradedCount } from "@/components/EnforcementGrade";
import { HarnessStrip } from "@/components/HarnessMark";
import type { Grade } from "@/components/grades";
import { NexusCard, NexusPageHeader } from "@/components/NexusUI";
import { Skeleton } from "@/components/Skeleton";
import { useIdentity } from "@/features/auth/bootstrapContext";

/**
 * A slot that has nothing in it, and says which slice will change that.
 *
 * "Not implemented yet" is a purposeful empty rather than a zero, per the F0 error
 * contract. The distinction matters commercially: zero credential exposures is a
 * finding, and we have not looked.
 */
function Pending({ slice, children }: { slice: string; children: string }) {
  return (
    <div className="px-5 py-6">
      <p className="text-xs text-slate-600 dark:text-slate-400">{children}</p>
      <p className="mt-2 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
        Arrives with {slice}
      </p>
    </div>
  );
}

function Slot({
  icon: Icon,
  title,
  explain,
  more,
  children,
}: {
  icon: ElementType;
  title: string;
  explain: string;
  more?: { label: string; to: string };
  children: React.ReactNode;
}) {
  return (
    <NexusCard>
      <div className="flex items-start justify-between gap-3 border-b border-slate-200 px-5 py-4 dark:border-white/10">
        <div className="flex min-w-0 items-start gap-3">
          <span className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-500/10 text-slate-600 dark:text-slate-300">
            <Icon size={16} />
          </span>
          <div className="min-w-0">
            <h2 className="text-sm font-bold text-slate-900 dark:text-white">{title}</h2>
            <p className="mt-0.5 text-xs text-slate-500 dark:text-slate-400">{explain}</p>
          </div>
        </div>
        {more ? (
          <Link
            to={more.to}
            className="shrink-0 text-xs font-semibold text-indigo-600 hover:underline dark:text-cyan-400"
          >
            {more.label}
          </Link>
        ) : null}
      </div>
      {children}
    </NexusCard>
  );
}

const COVERAGE_ROWS: Array<{ grade: Grade; label: string }> = [
  { grade: "A", label: "Mediated — could not have happened without us" },
  { grade: "B", label: "Interposed — we could have vetoed it" },
  { grade: "C", label: "Attested — the vendor enforced it, we verified" },
  { grade: "D", label: "Observed — we learned afterwards" },
  { grade: "E", label: "Dark — outside anything we collect" },
];

export default function LedgerHomeScreen() {
  const identity = useIdentity();
  // One cheap call for the denominator that already exists. The numerator — how many of
  // these are reporting actions — is the thing M3 adds, so the slot states the half it
  // has rather than dividing by a number it does not.
  const agents = useAgents({ limit: "1" });

  return (
    <div className="space-y-6">
      <NexusPageHeader
        crumbs={["Home"]}
        title={`${identity.account.name} · agent action ledger`}
        lede="What your AI agents did, under whose authority, and how much of it we can actually prove. Every number on this page carries the grade it was measured at."
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Slot
          icon={ShieldCheck}
          title="Coverage by grade"
          explain="Actions in the last window, split by what we could have done about them."
          more={{ label: "Ledger", to: "/observe/executions" }}
        >
          <div className="space-y-2.5 px-5 py-4">
            {COVERAGE_ROWS.map(({ grade, label }) => (
              <GradedCount key={grade} grade={grade} label={label} value={null} />
            ))}
          </div>
          <p className="border-t border-slate-200 px-5 py-3 text-[11px] text-slate-500 dark:border-white/10">
            Nothing is ingested yet, so every grade is unmeasured — including E. Showing
            zero would claim we had looked and found none. Ingest arrives with M3.
          </p>
        </Slot>

        <Slot
          icon={AlertTriangle}
          title="Recent high-risk actions"
          explain="Shell commands, outbound HTTP and file reads that touched something that matters."
          more={{ label: "All actions", to: "/observe/executions" }}
        >
          <Pending slice="M3 action ingest">
            The three capabilities that would have caught the reference incident —
            shell.exec, net.http and fs.read — are not collected yet. Model calls and MCP
            tool calls are already visible under Ledger.
          </Pending>
        </Slot>

        <Slot
          icon={Radar}
          title="Unregistered collectors"
          explain="Agents running in the estate that are not reporting to this ledger."
          more={{ label: "Agents", to: "/agents" }}
        >
          <DataBoundary
            query={agents}
            loading={<div className="px-5 py-6"><Skeleton height="3rem" /></div>}
            empty={(page) => page.total === 0}
            emptyTitle="No agents are registered"
            emptyDescription="Register an agent to give the ledger a denominator. Without one, coverage has no meaning."
          >
            {(page) => (
              <div className="px-5 py-6">
                <p className="font-mono text-2xl font-bold tabular-nums text-slate-900 dark:text-white">
                  {page.total.toLocaleString()}
                </p>
                <p className="mt-1 text-xs text-slate-600 dark:text-slate-400">
                  agents registered. How many of them are reporting — and how many are
                  running that nobody registered — is what discovery measures.
                </p>
                <p className="mt-2 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
                  Arrives with M4 hooks and discovery
                </p>
              </div>
            )}
          </DataBoundary>
        </Slot>

        <Slot
          icon={KeyRound}
          title="Credential exposures"
          explain="Long-lived tokens readable from a workspace an agent can search."
          more={{ label: "Platform Keys", to: "/platform-keys" }}
        >
          <Pending slice="M4 hooks and discovery">
            This is the PocketOS root cause: a token in a file the agent could read. The
            credentials we issue are already listed under Platform Keys and Connections;
            the ones we did not issue are what discovery finds.
          </Pending>
        </Slot>
      </div>

      <section className="space-y-3">
        <div>
          <h2 className="text-sm font-bold text-slate-900 dark:text-white">Harnesses this ledger can attribute</h2>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">
            An action records which client produced it. These are the values the schema accepts.
            A client that is not one of these is stored as custom or unknown, and unknown counts as ungraded.
          </p>
        </div>
        <HarnessStrip />
      </section>

      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 px-4 py-3 text-[11px] text-slate-500 dark:border-white/10 dark:text-slate-400">
        <span className="font-semibold text-slate-700 dark:text-slate-300">Grades:</span>
        {(["A", "B", "C", "D", "E"] as const).map((grade) => (
          <EnforcementGrade key={grade} grade={grade} showName />
        ))}
        <span>
          An ungraded row counts as E. A number without a grade is a claim we cannot
          support, so this page does not render one.
        </span>
      </div>
    </div>
  );
}
