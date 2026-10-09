import { Suspense, lazy, useState } from "react";
import { PageHeader } from "@/components/PageHeader";
import { Skeleton } from "@/components/Skeleton";
import { Tabs } from "@/components/Tabs";
import { ModuleGate } from "@/features/suite/ModuleGate";
import { ProjectSelect, SuiteProjectProvider } from "@/features/suite/SuiteProjectProvider";

const EvaluateDatasetsTab = lazy(() => import("./tabs/EvaluateDatasetsTab"));
const EvaluateExperimentsTab = lazy(() => import("./tabs/EvaluateExperimentsTab"));
const EvaluateEvaluatorsTab = lazy(() => import("./tabs/EvaluateEvaluatorsTab"));
const EvaluateScoresTab = lazy(() => import("./tabs/EvaluateScoresTab"));
const EvaluateOnlineRulesTab = lazy(() => import("./tabs/EvaluateOnlineRulesTab"));
const EvaluateAnnotationTab = lazy(() => import("./tabs/EvaluateAnnotationTab"));
const EvaluateReleaseGatesTab = lazy(() => import("./tabs/EvaluateReleaseGatesTab"));

const TABS = [
  { id: "datasets", label: "Datasets" },
  { id: "experiments", label: "Experiments" },
  { id: "evaluators", label: "Evaluators" },
  { id: "scores", label: "Scores" },
  { id: "online", label: "Online rules" },
  { id: "annotation", label: "Annotation" },
  { id: "gates", label: "Release gates" },
];

export default function EvaluateSuiteLayout() {
  const [tab, setTab] = useState("datasets");

  return (
    <ModuleGate moduleId="evaluate">
      <SuiteProjectProvider>
        <PageHeader
          title="Evaluate"
          explain="Datasets, offline experiments, evaluators, scores, online sampling, human annotation, and release gates."
          actions={<ProjectSelect />}
        />
        <Tabs ariaLabel="Evaluate sections" tabs={TABS} activeId={tab} onChange={setTab} />
        <div className="mt-6">
          <Suspense fallback={<Skeleton height="10rem" />}>
            {tab === "datasets" ? <EvaluateDatasetsTab /> : null}
            {tab === "experiments" ? <EvaluateExperimentsTab /> : null}
            {tab === "evaluators" ? <EvaluateEvaluatorsTab /> : null}
            {tab === "scores" ? <EvaluateScoresTab /> : null}
            {tab === "online" ? <EvaluateOnlineRulesTab /> : null}
            {tab === "annotation" ? <EvaluateAnnotationTab /> : null}
            {tab === "gates" ? <EvaluateReleaseGatesTab /> : null}
          </Suspense>
        </div>
      </SuiteProjectProvider>
    </ModuleGate>
  );
}
