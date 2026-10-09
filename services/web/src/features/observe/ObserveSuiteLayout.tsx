/**
 * Chrome for the ledger screens: the project filter, and nothing else.
 *
 * `<Outlet />` renders outside the boundary on purpose. The boundary governs the
 * *filter*, which genuinely has four states — still loading, none to choose between,
 * failed to load, here they are — and the content below is never gated on any of them.
 * Putting the outlet inside it is how this layout became a wall the first time: an
 * account with no projects got "no runtime projects" instead of Observe, which reads as
 * a broken product rather than an empty one. See `inv_observe_without_project`.
 */

import { Outlet } from "react-router-dom";
import { DataBoundary } from "@/components/DataBoundary";
import { Skeleton } from "@/components/Skeleton";
import { useProjects } from "@/api/suiteQueries";
import { ModuleGate } from "@/features/suite/ModuleGate";
import { ProjectSelect, SuiteProjectProvider } from "@/features/suite/SuiteProjectProvider";

export default function ObserveSuiteLayout() {
  const projectsQuery = useProjects();

  return (
    <ModuleGate moduleId="observe">
      <SuiteProjectProvider>
        <div className="mb-4 flex min-h-[2rem] justify-end">
          {/* No `empty` branch: nothing to choose between is not worth a message here,
              and `ProjectSelect` already renders nothing rather than a dead control.
              The screens below say what they are missing; the filter does not. */}
          <DataBoundary query={projectsQuery} loading={<Skeleton height="2rem" width="14rem" />}>
            {() => <ProjectSelect />}
          </DataBoundary>
        </div>
        <Outlet />
      </SuiteProjectProvider>
    </ModuleGate>
  );
}
