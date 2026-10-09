import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import { EMPTY_ITEMS } from "./queries";
import type {
  ArtifactCreate,
  ArtifactListResponse,
  ArtifactOut,
  DatasetCreate,
  DatasetOut,
  DeploymentCreate,
  DeploymentOut,
  DeploymentPage,
  DeploymentUpdate,
  DiffRequest,
  DiffResponse,
  EvaluatorCreate,
  EvaluatorRevisionOut,
  ExperimentCreate,
  ExperimentOut,
  ExperimentResultsResponse,
  ExecutionAnalytics,
  ExecutionDetail,
  ExecutionEvents,
  ExecutionLink,
  ExecutionObservations,
  ExecutionPage,
  ModulesManifest,
  OnlineRuleCreate,
  PagedDatasets,
  PagedEvaluators,
  PagedExperiments,
  PagedReleaseGates,
  PagedScores,
  PayloadContent,
  PayloadLegalHold,
  PayloadLegalHoldUpdate,
  PayloadReference,
  PagedOnlineRules,
  PagedAnnotationQueues,
  PagedAnnotationItems,
  PlaygroundRunRequest,
  PlaygroundRunResponse,
  PlaygroundRunStatusOut,
  ProjectPage,
  PromoteLabelRequest,
  ReleaseGateCreate,
  ReleaseGateEvaluateRequest,
  ReleaseGateEvaluateResponse,
  RevisionCreate,
  RevisionDetailOut,
  RevisionListResponse,
  RouteCreate,
  RouteOut,
  RoutePage,
  RouteSimulateRequest,
  RouteSimulateResult,
  RouteUpdate,
  ScoreCreate,
  ScoreOut,
  SessionDetail,
  SessionPage,
  SamplingPolicy,
  SamplingPolicyUpdate,
  SnapshotCompileRequest,
  SnapshotOut,
  TraceDetail,
  TraceGraph,
  TraceMetrics,
  TracePage,
  ObserveFreshness,
  ObservedUserPage,
  IdResponse,
  AnnotationQueueCreate,
} from "./types";

export const sqk = {
  modules: ["modules"] as const,
  projects: ["workload", "projects"] as const,
  routerDeployments: (projectId: string, params?: Record<string, string>) =>
    ["router", projectId, "deployments", params ?? {}] as const,
  routerRoutes: (projectId: string, params?: Record<string, string>) =>
    ["router", projectId, "routes", params ?? {}] as const,
  routerSnapshot: (projectId: string, snapshotId: string) =>
    ["router", projectId, "snapshots", snapshotId] as const,
  observeTraces: (projectId: string, params?: Record<string, string>) =>
    ["observe", projectId, "traces", params ?? {}] as const,
  observeTrace: (projectId: string, traceId: string, params?: Record<string, string>) =>
    ["observe", projectId, "traces", traceId, params ?? {}] as const,
  observeTraceGraph: (projectId: string, traceId: string) =>
    ["observe", projectId, "traces", traceId, "graph"] as const,
  observeExecutions: (projectId: string, params?: Record<string, string>) =>
    ["observe", projectId, "executions", params ?? {}] as const,
  observeExecution: (projectId: string, executionId: string) =>
    ["observe", projectId, "executions", executionId] as const,
  observeExecutionObservations: (projectId: string, executionId: string) =>
    ["observe", projectId, "executions", executionId, "observations"] as const,
  observeExecutionEvents: (projectId: string, executionId: string) =>
    ["observe", projectId, "executions", executionId, "events"] as const,
  observeExecutionLinks: (projectId: string, executionId: string) =>
    ["observe", projectId, "executions", executionId, "links"] as const,
  observePayloadRefs: (projectId: string, traceId: string) =>
    ["observe", projectId, "traces", traceId, "payload-refs"] as const,
  observePayload: (projectId: string, payloadId: string) =>
    ["observe", projectId, "payloads", payloadId] as const,
  observeSessions: (projectId: string, params?: Record<string, string>) =>
    ["observe", projectId, "sessions", params ?? {}] as const,
  observeSession: (projectId: string, sessionId: string) =>
    ["observe", projectId, "sessions", sessionId] as const,
  observeMetrics: (projectId: string) => ["observe", projectId, "metrics"] as const,
  observeAnalytics: (projectId: string) => ["observe", projectId, "analytics"] as const,
  observeSamplingPolicy: (projectId: string) =>
    ["observe", projectId, "sampling-policy"] as const,
  observeFreshness: (projectId: string) => ["observe", projectId, "freshness"] as const,
  observeUsers: (projectId: string, params?: Record<string, string>) =>
    ["observe", projectId, "users", params ?? {}] as const,
  promptArtifacts: (projectId: string, params?: Record<string, string>) =>
    ["prompt", projectId, "artifacts", params ?? {}] as const,
  promptArtifact: (projectId: string, artifactKey: string) =>
    ["prompt", projectId, "artifacts", artifactKey] as const,
  promptRevisions: (projectId: string, artifactKey: string) =>
    ["prompt", projectId, "artifacts", artifactKey, "revisions"] as const,
  promptRevision: (projectId: string, artifactKey: string, revisionId: string) =>
    ["prompt", projectId, "artifacts", artifactKey, "revisions", revisionId] as const,
  promptPlaygroundRun: (projectId: string, runId: string) =>
    ["prompt", projectId, "playground", runId] as const,
  evaluateDatasets: (projectId: string, params?: Record<string, string>) =>
    ["evaluate", projectId, "datasets", params ?? {}] as const,
  evaluateDataset: (projectId: string, datasetKey: string) =>
    ["evaluate", projectId, "datasets", datasetKey] as const,
  evaluateExperiments: (projectId: string, params?: Record<string, string>) =>
    ["evaluate", projectId, "experiments", params ?? {}] as const,
  evaluateExperiment: (projectId: string, experimentId: string) =>
    ["evaluate", projectId, "experiments", experimentId] as const,
  evaluateExperimentResults: (projectId: string, experimentId: string) =>
    ["evaluate", projectId, "experiments", experimentId, "results"] as const,
  evaluateEvaluators: (projectId: string, params?: Record<string, string>) =>
    ["evaluate", projectId, "evaluators", params ?? {}] as const,
  evaluateScores: (projectId: string, params?: Record<string, string>) =>
    ["evaluate", projectId, "scores", params ?? {}] as const,
  evaluateOnlineRules: (projectId: string, params?: Record<string, string>) =>
    ["evaluate", projectId, "online-rules", params ?? {}] as const,
  evaluateAnnotationQueues: (projectId: string, params?: Record<string, string>) =>
    ["evaluate", projectId, "annotation-queues", params ?? {}] as const,
  evaluateAnnotationItems: (projectId: string, params?: Record<string, string>) =>
    ["evaluate", projectId, "annotation-items", params ?? {}] as const,
  evaluateReleaseGates: (projectId: string, params?: Record<string, string>) =>
    ["evaluate", projectId, "release-gates", params ?? {}] as const,
};

export function useModules() {
  return useQuery({
    queryKey: sqk.modules,
    queryFn: () => api.get<ModulesManifest>("/v1/modules"),
    staleTime: 60_000,
  });
}

export function useProjects() {
  return useQuery({
    queryKey: sqk.projects,
    queryFn: () => api.get<ProjectPage>("/v1/workload-credentials/projects", { limit: "200" }),
  });
}

export function useObservedUsers(
  projectId: string,
  params: Record<string, string> = {},
) {
  return useQuery({
    queryKey: sqk.observeUsers(projectId, params),
    queryFn: () =>
      api.get<ObservedUserPage>(
        `/v1/observe/projects/${projectId}/observed-users`,
        { limit: params.limit ?? "200", offset: params.offset ?? "0", ...params },
      ),
    enabled: Boolean(projectId),
  });
}

// ---- Router ----

export function useRouterDeployments(projectId: string, includeDisabled = false) {
  return useQuery({
    queryKey: sqk.routerDeployments(projectId, { includeDisabled: String(includeDisabled) }),
    queryFn: () =>
      api.get<DeploymentPage>(`/v1/model-routing/projects/${projectId}/deployments`, {
        include_disabled: String(includeDisabled),
        limit: "200",
      }),
    enabled: Boolean(projectId),
  });
}

export function useCreateDeployment(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: DeploymentCreate) =>
      api.post<DeploymentOut>(`/v1/model-routing/projects/${projectId}/deployments`, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["router", projectId, "deployments"] }),
  });
}

export function usePatchDeployment(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ deploymentId, payload }: { deploymentId: string; payload: DeploymentUpdate }) =>
      api.patch<DeploymentOut>(
        `/v1/model-routing/projects/${projectId}/deployments/${deploymentId}`,
        payload,
      ),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["router", projectId, "deployments"] }),
  });
}

export function useDisableDeployment(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (deploymentId: string) =>
      api.post<DeploymentOut>(
        `/v1/model-routing/projects/${projectId}/deployments/${deploymentId}/disable`,
      ),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["router", projectId, "deployments"] }),
  });
}

export function useRouterRoutes(projectId: string, includeDisabled = false) {
  return useQuery({
    queryKey: sqk.routerRoutes(projectId, { includeDisabled: String(includeDisabled) }),
    queryFn: () =>
      api.get<RoutePage>(`/v1/model-routing/projects/${projectId}/routes`, {
        include_disabled: String(includeDisabled),
        limit: "200",
      }),
    enabled: Boolean(projectId),
  });
}

export function useCreateRoute(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: RouteCreate) =>
      api.post<RouteOut>(`/v1/model-routing/projects/${projectId}/routes`, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["router", projectId, "routes"] }),
  });
}

export function usePatchRoute(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ routeId, payload }: { routeId: string; payload: RouteUpdate }) =>
      api.patch<RouteOut>(`/v1/model-routing/projects/${projectId}/routes/${routeId}`, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["router", projectId, "routes"] }),
  });
}

export function useSimulateRoute(projectId: string) {
  return useMutation({
    mutationFn: ({
      routeId,
      payload,
    }: {
      routeId: string;
      payload: RouteSimulateRequest;
    }) =>
      api.post<RouteSimulateResult>(
        `/v1/model-routing/projects/${projectId}/routes/${routeId}/simulate`,
        payload,
      ),
  });
}

export function useCompileRouterSnapshot(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: SnapshotCompileRequest) =>
      api.post<SnapshotOut>(`/v1/model-routing/projects/${projectId}/snapshots/compile`, payload),
    onSuccess: (data) => {
      void qc.invalidateQueries({ queryKey: sqk.routerSnapshot(projectId, data.id) });
    },
  });
}

// ---- Observe ----

export function useObserveTraces(projectId: string, params: Record<string, string>) {
  return useQuery({
    queryKey: sqk.observeTraces(projectId, params),
    queryFn: () =>
      api.get<TracePage>(`/v1/observe/projects/${projectId}/traces`, {
        limit: params.limit ?? "50",
        offset: params.offset ?? "0",
        ...params,
      }),
    enabled: Boolean(projectId),
  });
}

export function useObserveTraceDetail(
  projectId: string,
  traceId: string,
  offset = "0",
  limit = "500",
) {
  return useQuery({
    queryKey: sqk.observeTrace(projectId, traceId, { offset, limit }),
    queryFn: () =>
      api.get<TraceDetail>(`/v1/observe/projects/${projectId}/traces/${traceId}`, {
        offset,
        limit,
      }),
    enabled: Boolean(projectId) && Boolean(traceId),
  });
}

export function useObserveTraceGraph(projectId: string, traceId: string) {
  return useQuery({
    queryKey: sqk.observeTraceGraph(projectId, traceId),
    queryFn: () =>
      api.get<TraceGraph>(`/v1/observe/projects/${projectId}/traces/${traceId}/graph`),
    enabled: Boolean(projectId) && Boolean(traceId),
  });
}

export function useObserveExecutions(projectId: string, params: Record<string, string> = {}) {
  return useQuery({
    queryKey: sqk.observeExecutions(projectId, params),
    queryFn: () =>
      api.get<ExecutionPage>(`/v1/observe/projects/${projectId}/executions`, {
        limit: params.limit ?? "50",
        offset: params.offset ?? "0",
        ...params,
      }),
    enabled: Boolean(projectId),
  });
}

export function useObserveExecution(projectId: string, executionId: string) {
  return useQuery({
    queryKey: sqk.observeExecution(projectId, executionId),
    queryFn: () =>
      api.get<ExecutionDetail>(
        `/v1/observe/projects/${projectId}/executions/${executionId}`,
      ),
    enabled: Boolean(projectId) && Boolean(executionId),
  });
}

export function useObserveExecutionObservations(projectId: string, executionId: string) {
  return useQuery({
    queryKey: sqk.observeExecutionObservations(projectId, executionId),
    queryFn: () =>
      api.get<ExecutionObservations>(
        `/v1/observe/projects/${projectId}/executions/${executionId}/observations`,
        { limit: "5000", offset: "0" },
      ),
    enabled: Boolean(projectId) && Boolean(executionId),
  });
}

export function useObserveExecutionEvents(projectId: string, executionId: string) {
  return useQuery({
    queryKey: sqk.observeExecutionEvents(projectId, executionId),
    queryFn: () =>
      api.get<ExecutionEvents>(
        `/v1/observe/projects/${projectId}/executions/${executionId}/events`,
        { limit: "5000" },
      ),
    enabled: Boolean(projectId) && Boolean(executionId),
  });
}

export function useObserveExecutionLinks(projectId: string, executionId: string) {
  return useQuery({
    queryKey: sqk.observeExecutionLinks(projectId, executionId),
    queryFn: () =>
      api.get<ExecutionLink[]>(
        `/v1/observe/projects/${projectId}/executions/${executionId}/links`,
      ),
    enabled: Boolean(projectId) && Boolean(executionId),
  });
}

export function useObservePayloadRefs(projectId: string, traceId: string, enabled = true) {
  return useQuery({
    queryKey: sqk.observePayloadRefs(projectId, traceId),
    queryFn: () =>
      api.get<PayloadReference[]>(
        `/v1/observe/projects/${projectId}/traces/${traceId}/payload-refs`,
      ),
    enabled: enabled && Boolean(projectId) && Boolean(traceId),
  });
}

export function useObservePayloadContent(
  projectId: string,
  payloadId: string,
  enabled: boolean,
) {
  return useQuery({
    queryKey: sqk.observePayload(projectId, payloadId),
    queryFn: () =>
      api.get<PayloadContent>(
        `/v1/observe/projects/${projectId}/payloads/${payloadId}/content`,
      ),
    enabled: enabled && Boolean(projectId) && Boolean(payloadId),
    staleTime: 5 * 60_000,
  });
}

export function useUpdateObservePayloadLegalHold(
  projectId: string,
  traceId: string,
  payloadId: string,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: PayloadLegalHoldUpdate) =>
      api.put<PayloadLegalHold>(
        `/v1/observe/projects/${projectId}/payloads/${payloadId}/legal-hold`,
        payload,
      ),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: sqk.observePayloadRefs(projectId, traceId) }),
  });
}

export function useObserveSessions(
  projectId: string,
  params: Record<string, string> = {},
) {
  return useQuery({
    queryKey: sqk.observeSessions(projectId, params),
    queryFn: () =>
      api.get<SessionPage>(`/v1/observe/projects/${projectId}/sessions`, {
        limit: params.limit ?? "50",
        offset: params.offset ?? "0",
        ...params,
      }),
    enabled: Boolean(projectId),
  });
}

export function useObserveSessionDetail(projectId: string, sessionId: string) {
  return useQuery({
    queryKey: sqk.observeSession(projectId, sessionId),
    queryFn: () =>
      api.get<SessionDetail>(`/v1/observe/projects/${projectId}/sessions/${sessionId}`),
    enabled: Boolean(projectId) && Boolean(sessionId),
  });
}

export function useObserveMetrics(projectId: string) {
  return useQuery({
    queryKey: sqk.observeMetrics(projectId),
    queryFn: () => api.get<TraceMetrics>(`/v1/observe/projects/${projectId}/metrics`),
    enabled: Boolean(projectId),
  });
}

export function useObserveAnalytics(projectId: string) {
  return useQuery({
    queryKey: sqk.observeAnalytics(projectId),
    queryFn: () =>
      api.get<ExecutionAnalytics>(
        `/v1/observe/projects/${projectId}/analytics/executions`,
      ),
    enabled: Boolean(projectId),
  });
}

export function useObserveSamplingPolicy(projectId: string) {
  return useQuery({
    queryKey: sqk.observeSamplingPolicy(projectId),
    queryFn: () =>
      api.get<SamplingPolicy>(`/v1/observe/projects/${projectId}/sampling-policy`),
    enabled: Boolean(projectId),
  });
}

export function useUpdateObserveSamplingPolicy(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: SamplingPolicyUpdate) =>
      api.put<SamplingPolicy>(
        `/v1/observe/projects/${projectId}/sampling-policy`,
        payload,
      ),
    onSuccess: (data) => {
      qc.setQueryData(sqk.observeSamplingPolicy(projectId), data);
      void qc.invalidateQueries({ queryKey: sqk.observeAnalytics(projectId) });
    },
  });
}

export function useObserveFreshness(projectId: string) {
  return useQuery({
    queryKey: sqk.observeFreshness(projectId),
    queryFn: () => api.get<ObserveFreshness>(`/v1/observe/projects/${projectId}/freshness`),
    enabled: Boolean(projectId),
  });
}

// ---- Prompt ----

export function usePromptArtifacts(projectId: string, params?: Record<string, string>) {
  return useQuery({
    queryKey: sqk.promptArtifacts(projectId, params),
    queryFn: () =>
      api.get<ArtifactListResponse>(`/v1/artifacts/projects/${projectId}/artifacts`, {
        limit: params?.limit ?? "50",
        ...params,
      }),
    enabled: Boolean(projectId),
  });
}

export function usePromptArtifact(projectId: string, artifactKey: string) {
  return useQuery({
    queryKey: sqk.promptArtifact(projectId, artifactKey),
    queryFn: () =>
      api.get<ArtifactOut>(`/v1/artifacts/projects/${projectId}/artifacts/${artifactKey}`),
    enabled: Boolean(projectId) && Boolean(artifactKey),
  });
}

export function usePromptRevisions(projectId: string, artifactKey: string) {
  return useQuery({
    queryKey: sqk.promptRevisions(projectId, artifactKey),
    queryFn: () =>
      api.get<RevisionListResponse>(
        `/v1/artifacts/projects/${projectId}/artifacts/${artifactKey}/revisions`,
        { limit: "50" },
      ),
    enabled: Boolean(projectId) && Boolean(artifactKey),
  });
}

export function usePromptRevision(projectId: string, artifactKey: string, revisionId: string) {
  return useQuery({
    queryKey: sqk.promptRevision(projectId, artifactKey, revisionId),
    queryFn: () =>
      api.get<RevisionDetailOut>(
        `/v1/artifacts/projects/${projectId}/artifacts/${artifactKey}/revisions/${revisionId}`,
      ),
    enabled: Boolean(projectId) && Boolean(artifactKey) && Boolean(revisionId),
  });
}

export function useCreatePromptArtifact(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ArtifactCreate) =>
      api.post<ArtifactOut>(`/v1/artifacts/projects/${projectId}/artifacts`, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["prompt", projectId, "artifacts"] }),
  });
}

export function useCreatePromptRevision(projectId: string, artifactKey: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: RevisionCreate) =>
      api.post<RevisionDetailOut>(
        `/v1/artifacts/projects/${projectId}/artifacts/${artifactKey}/revisions`,
        payload,
      ),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: sqk.promptRevisions(projectId, artifactKey) });
      void qc.invalidateQueries({ queryKey: sqk.promptArtifact(projectId, artifactKey) });
    },
  });
}

export function useDiffPromptRevisions(projectId: string, artifactKey: string) {
  return useMutation({
    mutationFn: (payload: DiffRequest) =>
      api.post<DiffResponse>(
        `/v1/artifacts/projects/${projectId}/artifacts/${artifactKey}/revisions:diff`,
        payload,
      ),
  });
}

export function usePromotePromptLabel(projectId: string, artifactKey: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: PromoteLabelRequest) =>
      api.post(`/v1/artifacts/projects/${projectId}/artifacts/${artifactKey}/labels:promote`, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: sqk.promptArtifact(projectId, artifactKey) });
    },
  });
}

export function usePlaygroundRun(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: PlaygroundRunRequest) =>
      api.post<PlaygroundRunResponse>(`/v1/artifacts/projects/${projectId}/playground/runs`, {
        ...payload,
        stream: false,
      }),
    onSuccess: (data) => {
      void qc.setQueryData(sqk.promptPlaygroundRun(projectId, data.run_id), data);
    },
  });
}

export function usePlaygroundRunStatus(projectId: string, runId: string) {
  return useQuery({
    queryKey: sqk.promptPlaygroundRun(projectId, runId),
    queryFn: () =>
      api.get<PlaygroundRunStatusOut>(
        `/v1/artifacts/projects/${projectId}/playground/runs/${runId}`,
      ),
    enabled: Boolean(projectId) && Boolean(runId),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      if (status === "completed" || status === "failed" || status === "cancelled") return false;
      return 2000;
    },
  });
}

// ---- Evaluate ----

export function useEvaluateDatasets(projectId: string) {
  return useQuery({
    queryKey: sqk.evaluateDatasets(projectId),
    queryFn: () =>
      api.get<PagedDatasets>(`/v1/evaluate/projects/${projectId}/datasets`, { limit: "100" }),
    enabled: Boolean(projectId),
  });
}

export function useCreateDataset(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: DatasetCreate) =>
      api.post<DatasetOut>(`/v1/evaluate/projects/${projectId}/datasets`, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: sqk.evaluateDatasets(projectId) }),
  });
}

export function useEvaluateExperiments(projectId: string) {
  return useQuery({
    queryKey: sqk.evaluateExperiments(projectId),
    queryFn: () =>
      api.get<PagedExperiments>(`/v1/evaluate/projects/${projectId}/experiments`, { limit: "100" }),
    enabled: Boolean(projectId),
  });
}

export function useCreateExperiment(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ExperimentCreate) =>
      api.post<ExperimentOut>(`/v1/evaluate/projects/${projectId}/experiments`, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: sqk.evaluateExperiments(projectId) }),
  });
}

export function useStartExperiment(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (experimentId: string) =>
      api.post<ExperimentOut>(
        `/v1/evaluate/projects/${projectId}/experiments/${experimentId}/start`,
      ),
    onSuccess: (_, experimentId) => {
      void qc.invalidateQueries({ queryKey: sqk.evaluateExperiments(projectId) });
      void qc.invalidateQueries({ queryKey: sqk.evaluateExperiment(projectId, experimentId) });
    },
  });
}

export function useExperimentResults(projectId: string, experimentId: string) {
  return useQuery({
    queryKey: sqk.evaluateExperimentResults(projectId, experimentId),
    queryFn: () =>
      api.get<ExperimentResultsResponse>(
        `/v1/evaluate/projects/${projectId}/experiments/${experimentId}/results`,
      ),
    enabled: Boolean(projectId) && Boolean(experimentId),
  });
}

export function useEvaluateEvaluators(projectId: string) {
  return useQuery({
    queryKey: sqk.evaluateEvaluators(projectId),
    queryFn: () =>
      api.get<PagedEvaluators>(`/v1/evaluate/projects/${projectId}/evaluators`, { limit: "100" }),
    enabled: Boolean(projectId),
  });
}

export function useCreateEvaluator(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: EvaluatorCreate) =>
      api.post<EvaluatorRevisionOut>(`/v1/evaluate/projects/${projectId}/evaluators`, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: sqk.evaluateEvaluators(projectId) }),
  });
}

export function useEvaluateScores(projectId: string) {
  return useQuery({
    queryKey: sqk.evaluateScores(projectId),
    queryFn: () =>
      api.get<PagedScores>(`/v1/evaluate/projects/${projectId}/scores`, { limit: "100" }),
    enabled: Boolean(projectId),
  });
}

export function useCreateScore(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ScoreCreate) =>
      api.post<ScoreOut>(`/v1/evaluate/projects/${projectId}/scores`, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: sqk.evaluateScores(projectId) }),
  });
}

export function useEvaluateOnlineRules(projectId: string) {
  return useQuery({
    queryKey: sqk.evaluateOnlineRules(projectId),
    queryFn: () =>
      api.get<PagedOnlineRules>(`/v1/evaluate/projects/${projectId}/online-rules`, { limit: "100" }),
    enabled: Boolean(projectId),
  });
}

export function useCreateOnlineRule(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: OnlineRuleCreate) =>
      api.post<IdResponse>(`/v1/evaluate/projects/${projectId}/online-rules`, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: sqk.evaluateOnlineRules(projectId) }),
  });
}

export function useEvaluateAnnotationQueues(projectId: string) {
  return useQuery({
    queryKey: sqk.evaluateAnnotationQueues(projectId),
    queryFn: () =>
      api.get<PagedAnnotationQueues>(
        `/v1/evaluate/projects/${projectId}/annotation-queues`,
        { limit: "100" },
      ),
    enabled: Boolean(projectId),
  });
}

export function useEvaluateAnnotationItems(projectId: string) {
  return useQuery({
    queryKey: sqk.evaluateAnnotationItems(projectId),
    queryFn: () =>
      api.get<PagedAnnotationItems>(
        `/v1/evaluate/projects/${projectId}/annotation-queues/items`,
        { limit: "100" },
      ),
    enabled: Boolean(projectId),
  });
}

export function useCreateAnnotationQueue(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: AnnotationQueueCreate) =>
      api.post<IdResponse>(`/v1/evaluate/projects/${projectId}/annotation-queues`, payload),
    onSuccess: () =>
      void qc.invalidateQueries({ queryKey: sqk.evaluateAnnotationQueues(projectId) }),
  });
}

export function useEvaluateReleaseGates(projectId: string) {
  return useQuery({
    queryKey: sqk.evaluateReleaseGates(projectId),
    queryFn: () =>
      api.get<PagedReleaseGates>(`/v1/evaluate/projects/${projectId}/release-gates`, {
        limit: "100",
      }),
    enabled: Boolean(projectId),
  });
}

export function useCreateReleaseGate(projectId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ReleaseGateCreate) =>
      api.post<IdResponse>(`/v1/evaluate/projects/${projectId}/release-gates`, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: sqk.evaluateReleaseGates(projectId) }),
  });
}

export function useEvaluateReleaseGate(projectId: string) {
  return useMutation({
    mutationFn: ({
      gateId,
      payload,
    }: {
      gateId: string;
      payload: ReleaseGateEvaluateRequest;
    }) =>
      api.post<ReleaseGateEvaluateResponse>(
        `/v1/evaluate/projects/${projectId}/release-gates/${gateId}/evaluate`,
        payload,
      ),
  });
}

/** Stable empty list for suite tables while queries are pending. */
export function useStableSuiteItems<T>(items: T[] | undefined): readonly T[] {
  return items ?? EMPTY_ITEMS;
}
