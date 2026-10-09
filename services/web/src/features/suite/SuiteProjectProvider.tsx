/**
 * Project selection for the suite screens.
 *
 * A **filter, never a wall**. This used to refuse to render its children when the
 * account had no projects, which made "no projects yet" indistinguishable from "Observe
 * is broken" — and Observe has plenty to show without one. A project narrows what a
 * screen displays; it is not a precondition for the screen existing.
 *
 * Loading and failure are still handled here, because those are genuinely states the
 * children cannot render through: the difference is that *success with nothing selected*
 * is no longer one of them.
 */

import { useCallback, useMemo, useState, type ReactNode } from "react";
import { useProjects } from "@/api/suiteQueries";
import { ReasonState } from "@/components/DataBoundary";
import { Skeleton } from "@/components/Skeleton";
import {
  resolveActiveProjectId,
  SuiteProjectContext,
  useSuiteProject,
  type SuiteProjectContextValue,
} from "./useSuiteProject";

const STORAGE_KEY = "aap-suite-project-id";

export function SuiteProjectProvider({ children }: { children: ReactNode }) {
  const projectsQuery = useProjects();
  const projects = useMemo(
    () => projectsQuery.data?.items ?? [],
    [projectsQuery.data?.items],
  );

  const [preferredProjectId, setPreferredProjectId] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) ?? "";
    } catch {
      return "";
    }
  });

  const setProjectId = useCallback((id: string) => {
    setPreferredProjectId(id);
    try {
      if (id) localStorage.setItem(STORAGE_KEY, id);
      else localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* private browsing */
    }
  }, []);

  const activeProjectId = resolveActiveProjectId(projects, preferredProjectId);

  const project = useMemo(
    () => projects.find((p) => p.id === activeProjectId) ?? null,
    [projects, activeProjectId],
  );

  const value = useMemo((): SuiteProjectContextValue => {
    return {
      projectId: activeProjectId,
      project,
      setProjectId,
      projects,
    };
  }, [activeProjectId, project, projects, setProjectId]);

  if (projectsQuery.isLoading) {
    return (
      <div className="space-y-3">
        <Skeleton height="2rem" width="40%" />
        <Skeleton height="12rem" />
      </div>
    );
  }

  if (projectsQuery.isError) {
    return <ReasonState error={projectsQuery.error} onRetry={() => void projectsQuery.refetch()} />;
  }

  // No empty branch. An account with no projects still renders every suite screen; the
  // screens themselves show what they have, which for most of them is everything.
  return <SuiteProjectContext.Provider value={value}>{children}</SuiteProjectContext.Provider>;
}

export function ProjectSelect() {
  const { projectId, setProjectId, projects } = useSuiteProject();

  // Nothing to choose between is not worth a control. Rendering a disabled empty select
  // is how a filter starts to look like a blocked screen.
  if (!projects.length) return null;

  return (
    <label className="flex items-center gap-2 text-sm text-ink-600">
      <span className="font-medium text-ink-900">Project</span>
      <select
        className="rounded-md border border-line-200 bg-bg-panel px-2 py-1.5 text-sm text-ink-900"
        value={projectId}
        onChange={(e) => setProjectId(e.target.value)}
      >
        {projects.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name} ({p.slug})
          </option>
        ))}
      </select>
    </label>
  );
}
