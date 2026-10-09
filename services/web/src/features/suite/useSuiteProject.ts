import { createContext, useContext } from "react";
import type { ProjectOut } from "@/api/types";

export type SuiteProjectContextValue = {
  projectId: string;
  project: ProjectOut | null;
  setProjectId: (id: string) => void;
  projects: ProjectOut[];
};

export const SuiteProjectContext = createContext<SuiteProjectContextValue | null>(null);

export function useSuiteProject(): SuiteProjectContextValue {
  const ctx = useContext(SuiteProjectContext);
  if (!ctx) {
    throw new Error("useSuiteProject must be used within SuiteProjectProvider");
  }
  return ctx;
}

export function resolveActiveProjectId(projects: readonly ProjectOut[], preferred: string): string {
  if (projects.length === 0) return "";
  if (preferred && projects.some((p) => p.id === preferred)) return preferred;
  return projects[0]!.id;
}
