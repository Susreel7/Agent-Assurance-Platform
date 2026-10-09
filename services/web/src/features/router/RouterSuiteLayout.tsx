import { Outlet } from "react-router-dom";
import { PageHeader } from "@/components/PageHeader";
import { ModuleGate } from "@/features/suite/ModuleGate";
import { ProjectSelect, SuiteProjectProvider } from "@/features/suite/SuiteProjectProvider";
import { SuiteSubNav } from "@/features/suite/SuiteSubNav";

const SUB_NAV = [
  { to: "/router", label: "Deployments", end: true },
  { to: "/router/routes", label: "Routes" },
  { to: "/router/simulate", label: "Simulation" },
  { to: "/router/compile", label: "Config compile" },
];

export default function RouterSuiteLayout() {
  return (
    <ModuleGate moduleId="router">
      <SuiteProjectProvider>
        <PageHeader
          title="Router"
          explain="Model deployments, routing rules, simulation, and signed gateway configuration for a runtime project."
          actions={<ProjectSelect />}
        />
        <SuiteSubNav items={SUB_NAV} ariaLabel="Router sections" />
        <Outlet />
      </SuiteProjectProvider>
    </ModuleGate>
  );
}
