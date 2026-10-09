/**
 * Discovery — a route and an empty state, deliberately nothing more.
 *
 * It exists now because the navigation has to be the shape of the product before the
 * product is finished, and because M4 needs somewhere to land. A nav entry pointing at
 * a route that does not exist redirects to Home, which reads as a broken link; a route
 * that says what it is for reads as a roadmap.
 *
 * What it must not do is show a count. "0 shadow agents" is a finding, and nothing has
 * looked yet.
 */

import { Link } from "react-router-dom";
import Radar from "lucide-react/dist/esm/icons/radar";
import { HarnessStrip } from "@/components/HarnessMark";
import { NexusCard, NexusPageHeader } from "@/components/NexusUI";

const FINDS = [
  {
    title: "Shadow agents",
    detail:
      "An AI client running against a workspace nobody registered — the estate's real denominator, and the reason a coverage percentage means anything.",
  },
  {
    title: "Unregistered collectors",
    detail:
      "A machine with an agent on it and no hook or OTLP export configured, so its actions never reach this ledger.",
  },
  {
    title: "Credential exposure",
    detail:
      "Long-lived tokens sitting in files an agent can read. This is the PocketOS root cause, and finding them does not require blocking anything.",
  },
];

export default function DiscoveryScreen() {
  return (
    <div className="space-y-6">
      <NexusPageHeader
        crumbs={["Agents", "Discovery"]}
        title="Discovery"
        lede="What is running that nobody told us about. Read-only: discovery observes and reports, it never blocks."
      />

      <section className="space-y-3">
        <h2 className="text-sm font-bold text-slate-900 dark:text-white">Clients discovery knows how to name</h2>
        <HarnessStrip />
      </section>

      <NexusCard>
        <div className="flex flex-col items-center gap-3 px-6 py-10 text-center">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-slate-500/10 text-slate-500">
            <Radar size={20} />
          </span>
          <p className="text-sm font-semibold text-slate-900 dark:text-white">
            Nothing has looked yet
          </p>
          <p className="max-w-lg text-xs text-slate-600 dark:text-slate-400">
            Discovery is M4. It deliberately shows no number here, because zero findings
            and zero searches render identically and mean opposite things. Until then the
            registered estate is under{" "}
            <Link to="/agents" className="font-medium text-indigo-600 hover:underline dark:text-cyan-400">
              Agents
            </Link>
            , and what those agents actually did is under{" "}
            <Link
              to="/observe/executions"
              className="font-medium text-indigo-600 hover:underline dark:text-cyan-400"
            >
              Ledger
            </Link>
            .
          </p>
        </div>
        <div className="grid gap-px border-t border-slate-200 bg-slate-200 sm:grid-cols-3 dark:border-white/10 dark:bg-white/10">
          {FINDS.map((find) => (
            <div key={find.title} className="bg-bg-panel px-5 py-4 dark:bg-transparent">
              <p className="text-xs font-bold text-slate-800 dark:text-slate-200">{find.title}</p>
              <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">{find.detail}</p>
            </div>
          ))}
        </div>
      </NexusCard>
    </div>
  );
}
