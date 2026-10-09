import { Outlet } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { ModuleGate } from "@/features/suite/ModuleGate";
import { ProjectSelect, SuiteProjectProvider } from "@/features/suite/SuiteProjectProvider";
import { SuiteSubNav } from "@/features/suite/SuiteSubNav";

const SUB_NAV = [
  { to: "/prompt", label: "Artifacts", end: true },
  { to: "/prompt/playground", label: "Playground" },
];

export default function PromptSuiteLayout() {
  return (
    <ModuleGate moduleId="prompt">
      <SuiteProjectProvider>
        <PageHeader
          title="Prompt"
          explain="Versioned prompt artifacts, diffs, label promotion, and an interactive playground."
          actions={<ProjectSelect />}
        />
        <SuiteSubNav items={SUB_NAV} ariaLabel="Prompt sections" />
        <Outlet />
      </SuiteProjectProvider>
    </ModuleGate>
  );
}
