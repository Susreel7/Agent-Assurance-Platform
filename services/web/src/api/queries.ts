import { useQuery } from "@tanstack/react-query";
import { api } from "./client";

/**
 * Stable fallback for a not-yet-loaded page of results.
 *
 * `query.data?.items ?? []` looks harmless but allocates a fresh array on every render
 * while the query is pending, so any `useMemo` depending on it recomputes every time —
 * silently removing the memoisation the screens rely on to stay responsive on a large
 * estate. Sharing one frozen reference makes the dependency genuinely stable.
 */
export const EMPTY_ITEMS: readonly never[] = Object.freeze([]);
import type {
  AccreditationDetail,
  AgentDetail,
  AgentOperations,
  AgentVersion,
  BlastRadius,
  BomComponent,
  ChainVerification,
  CostReport,
  CustomerDetail,
  DashboardSummary,
  DeploymentInfo,
  FrameworkShare,
  McpInventory,
  RunRow,
  RunDetail,
  ObservedGraph,
  ToolInventory,
  EngagementDetail,
  EvidenceBatch,
  EvidenceEvent,
  Finding,
  Framework,
  FrameworkControl,
  GraphNeighbourhood,
  InclusionProof,
  Ownership,
  Page,
  ModelCatalogPage,
  ModelRoutingOverview,
  EngagementSloRollup,
  PolicyDecision,
  PolicySummary,
  PolicyVersion,
  ReadinessResponse,
  ReleaseAssessment,
  ReleaseDetail,
  ReleaseSummary,
  SloBreach,
  SloDefinition,
  SloMeasurement,
  TrustPortalView,
  AccreditationSummary,
  AgentSummary,
  AttestationRun,
  CompositionReconciliation,
  CompositionSummary,
  ProbeRun,
  ProbeRunDetail,
  ProbeSuite,
  RuleGapReport,
  CustomerSummary,
  EngagementSummary,
  GraphEdge,
  GraphNode,
} from "./types";

export const qk = {
  deployment: ["deployment"] as const,
  // Every operational key carries the window. Without it, switching from 7 days to 90
  // reads the 7-day answer out of the cache and renders it under a "Last 90 days"
  // heading — the worst kind of wrong, because it looks fine.
  dashboard: (days: number) => ["dashboard", "summary", days] as const,
  runs: (params: Record<string, string | string[] | undefined>) => ["operations", "runs", params] as const,
  runDetail: (runId: string) => ["operations", "runs", runId] as const,
  observedGraph: (agentId: string, days: number) => ["operations", "agents", agentId, "graph", days] as const,
  cost: (days: number) => ["operations", "cost", days] as const,
  toolInventory: (days: number) => ["operations", "tools", days] as const,
  mcpServers: (days: number) => ["operations", "mcp", days] as const,
  runtimeFrameworks: (days: number) => ["operations", "frameworks", days] as const,
  agentOperations: (agentId: string, days: number) => ["operations", "agent", agentId, days] as const,
  agents: (params?: Record<string, string>) => ["agents", params ?? {}] as const,
  agent: (id: string) => ["agents", id] as const,
  agentVersions: (agentId: string, params?: Record<string, string>) =>
    ["agents", agentId, "versions", params ?? {}] as const,
  agentVersion: (agentId: string, versionId: string) => ["agents", agentId, "versions", versionId] as const,
  agentBom: (agentId: string, versionId?: string) => ["agents", agentId, "bom", versionId ?? "current"] as const,
  agentComposition: (agentId: string, versionId: string, days: number) =>
    ["agents", agentId, "composition", versionId, days] as const,
  agentReconciliation: (agentId: string, days: number) =>
    ["agents", agentId, "reconciliation", days] as const,
  agentOwnership: (agentId: string) => ["agents", agentId, "ownership"] as const,
  agentGraph: (agentId: string, depth: number) => ["agents", agentId, "graph", depth] as const,
  releases: (params?: Record<string, string>) => ["releases", params ?? {}] as const,
  release: (id: string) => ["releases", id] as const,
  releaseAssessment: (id: string) => ["releases", id, "assessment"] as const,
  evidenceEvents: (params?: Record<string, string>) => ["evidence", "events", params ?? {}] as const,
  evidenceBatches: (params?: Record<string, string>) => ["evidence", "batches", params ?? {}] as const,
  evidenceChain: ["evidence", "chain"] as const,
  inclusionProof: (eventId: string) => ["evidence", "events", eventId, "inclusion-proof"] as const,
  graphNodes: (params?: Record<string, string>) => ["graph", "nodes", params ?? {}] as const,
  graphEdges: (params?: Record<string, string>) => ["graph", "edges", params ?? {}] as const,
  blastRadius: (nodeId: string) => ["graph", "blast-radius", nodeId] as const,
  customers: (params?: Record<string, string>) => ["customers", params ?? {}] as const,
  customer: (id: string) => ["customers", id] as const,
  customerReadiness: (id: string) => ["customers", id, "readiness"] as const,
  engagements: (params?: Record<string, string>) => ["engagements", params ?? {}] as const,
  engagement: (id: string) => ["engagements", id] as const,
  accreditations: (params?: Record<string, string>) => ["accreditations", params ?? {}] as const,
  accreditation: (id: string) => ["accreditations", id] as const,
  attestations: (params?: Record<string, string>) => ["attestations", params ?? {}] as const,
  findings: (params?: Record<string, string>) => ["findings", params ?? {}] as const,
  policies: ["policy", "list"] as const,
  policyVersions: (policyId: string) => ["policy", policyId, "versions"] as const,
  policyDecisions: (params?: Record<string, string>) => ["policy", "decisions", params ?? {}] as const,
  modelRoutingOverview: ["model-routing", "overview"] as const,
  modelCatalogue: (params?: Record<string, string>) => ["model-routing", "catalogue", params ?? {}] as const,
  sloDefinitions: (params?: Record<string, string>) => ["sla", "definitions", params ?? {}] as const,
  engagementSloSummary: (engagementId: string) => ["sla", "engagement", engagementId] as const,
  sloMeasurements: (sloId: string, params?: Record<string, string>) =>
    ["sla", sloId, "measurements", params ?? {}] as const,
  sloBreaches: (sloId: string) => ["sla", sloId, "breaches"] as const,
  frameworks: ["frameworks"] as const,
  frameworkControls: (frameworkId: string) => ["frameworks", frameworkId, "controls"] as const,
  trustPortal: (customerSlug: string, engagementSlug: string) =>
    ["portal", customerSlug, engagementSlug] as const,
  probeSuites: ["assurance", "probe-suites"] as const,
  probeRuns: (params?: Record<string, string>) => ["assurance", "probe-runs", params ?? {}] as const,
  probeRunDetail: (runId: string) => ["assurance", "probe-runs", runId] as const,
  ruleGaps: (agentId: string, versionId: string, framework?: string) =>
    ["agents", agentId, "versions", versionId, "rule-gaps", framework ?? ""] as const,
};

export function useDeployment() {
  return useQuery({
    queryKey: qk.deployment,
    queryFn: () => api.get<DeploymentInfo>("/v1/deployment"),
    staleTime: Infinity,
  });
}

export function useDashboardSummary(days: number) {
  return useQuery({
    queryKey: qk.dashboard(days),
    queryFn: () => api.get<DashboardSummary>("/v1/home/summary", { days: String(days) }),
    // Runs land continuously, so the landing page is stale the moment it renders. Thirty
    // seconds is short enough that a number on screen is never surprising and long
    // enough that clicking between screens does not refetch the whole estate.
    staleTime: 30_000,
  });
}

// ---- Operations ----

export function useRuns(params: {
  days: number;
  agent_id?: string;
  environment?: string;
  outcome?: string[];
  escalated?: boolean;
  limit?: number;
  offset?: number;
}) {
  const search: Record<string, string | string[] | undefined> = {
    days: String(params.days),
    agent_id: params.agent_id,
    environment: params.environment,
    outcome: params.outcome?.length ? params.outcome : undefined,
    escalated: params.escalated ? "true" : undefined,
    limit: String(params.limit ?? 50),
    offset: String(params.offset ?? 0),
  };
  return useQuery({
    queryKey: qk.runs(search),
    queryFn: () => api.get<Page<RunRow>>("/v1/operations/runs", search),
    placeholderData: (previous) => previous,
  });
}

export function useCostReport(days: number) {
  return useQuery({
    queryKey: qk.cost(days),
    queryFn: () => api.get<CostReport>("/v1/operations/cost", { days: String(days) }),
  });
}

export function useToolInventory(days: number) {
  return useQuery({
    queryKey: qk.toolInventory(days),
    queryFn: () => api.get<ToolInventory>("/v1/operations/tools", { days: String(days) }),
  });
}

export function useMcpServers(days: number) {
  return useQuery({
    queryKey: qk.mcpServers(days),
    queryFn: () => api.get<McpInventory>("/v1/operations/mcp-servers", { days: String(days) }),
  });
}

export function useRuntimeFrameworks(days: number) {
  return useQuery({
    queryKey: qk.runtimeFrameworks(days),
    queryFn: () =>
      api.get<FrameworkShare[]>("/v1/operations/runtime-frameworks", { days: String(days) }),
  });
}

export function useAgentOperations(agentId: string, days: number) {
  return useQuery({
    queryKey: qk.agentOperations(agentId, days),
    queryFn: () =>
      api.get<AgentOperations>(`/v1/operations/agents/${agentId}`, { days: String(days) }),
    enabled: Boolean(agentId),
  });
}

export function useAgentComposition(agentId: string, versionId: string | undefined, days: number) {
  return useQuery({
    queryKey: qk.agentComposition(agentId, versionId ?? "none", days),
    queryFn: () =>
      api.get<CompositionSummary>(`/v1/agents/${agentId}/versions/${versionId}/composition`, {
        days: String(days),
      }),
    enabled: Boolean(agentId && versionId),
  });
}

export function useAgentReconciliation(agentId: string, days: number) {
  return useQuery({
    queryKey: qk.agentReconciliation(agentId, days),
    queryFn: () =>
      api.get<CompositionReconciliation>(`/v1/agents/${agentId}/composition/reconciliation`, {
        days: String(days),
      }),
    enabled: Boolean(agentId),
  });
}

export function useRunDetail(runId: string) {
  return useQuery({
    queryKey: qk.runDetail(runId),
    queryFn: () => api.get<RunDetail>(`/v1/operations/runs/${runId}`),
    enabled: Boolean(runId),
  });
}

export function useObservedGraph(agentId: string, days: number) {
  return useQuery({
    queryKey: qk.observedGraph(agentId, days),
    queryFn: () =>
      api.get<ObservedGraph>(`/v1/operations/agents/${agentId}/graph`, { days: String(days) }),
    enabled: Boolean(agentId),
  });
}

export function useAgents(params?: { limit?: string; offset?: string; lifecycle_state?: string[] }) {
  return useQuery({
    queryKey: qk.agents(params as Record<string, string>),
    queryFn: () =>
      api.get<Page<AgentSummary>>("/v1/agents", {
        limit: params?.limit ?? "50",
        offset: params?.offset ?? "0",
        lifecycle_state: params?.lifecycle_state,
      }),
  });
}

export function useAgent(agentId: string) {
  return useQuery({
    queryKey: qk.agent(agentId),
    queryFn: () => api.get<AgentDetail>(`/v1/agents/${agentId}`),
    enabled: Boolean(agentId),
  });
}

export function useAgentVersions(agentId: string, params?: { limit?: string; offset?: string }) {
  return useQuery({
    queryKey: qk.agentVersions(agentId, params),
    queryFn: () =>
      api.get<Page<AgentVersion>>(`/v1/agents/${agentId}/versions`, {
        limit: params?.limit ?? "50",
        offset: params?.offset ?? "0",
      }),
    enabled: Boolean(agentId),
  });
}

export function useAgentVersion(agentId: string, versionId: string) {
  return useQuery({
    queryKey: qk.agentVersion(agentId, versionId),
    queryFn: () => api.get<AgentVersion>(`/v1/agents/${agentId}/versions/${versionId}`),
    enabled: Boolean(agentId && versionId),
  });
}

export function useAgentBom(agentId: string, versionId?: string) {
  return useQuery({
    queryKey: qk.agentBom(agentId, versionId),
    queryFn: () =>
      api.get<BomComponent[]>(
        `/v1/bom/agents/${agentId}/bom`,
        versionId ? { version_id: versionId } : undefined,
      ),
    enabled: Boolean(agentId),
  });
}

export function useAgentOwnership(agentId: string) {
  return useQuery({
    queryKey: qk.agentOwnership(agentId),
    queryFn: () => api.get<Ownership[]>(`/v1/agents/${agentId}/ownership`),
    enabled: Boolean(agentId),
  });
}

export function useAgentGraphNeighbourhood(agentId: string, depth: number) {
  return useQuery({
    queryKey: qk.agentGraph(agentId, depth),
    queryFn: () =>
      api.get<GraphNeighbourhood>(`/v1/graph/nodes/${agentId}/neighbourhood`, {
        depth: String(depth),
      }),
    enabled: Boolean(agentId),
  });
}

export function useReleases(params?: { limit?: string; offset?: string; agent_id?: string }) {
  return useQuery({
    queryKey: qk.releases(params),
    queryFn: () =>
      api.get<Page<ReleaseSummary>>("/v1/releases", {
        limit: params?.limit ?? "50",
        offset: params?.offset ?? "0",
        agent_id: params?.agent_id,
      }),
  });
}

export function useRelease(releaseId: string) {
  return useQuery({
    queryKey: qk.release(releaseId),
    queryFn: () => api.get<ReleaseDetail>(`/v1/releases/${releaseId}`),
    enabled: Boolean(releaseId),
  });
}

/** The materiality verdict for a release, and which accreditations it touches.
 *
 * Replaces a hook that called `/v1/releases/{id}/impact` — a route that does not exist,
 * so the impact rail showed a spinner and then nothing, on every release, forever.
 *
 * It is a POST because assessing is a computation over the release's changes rather than
 * a stored field. It does not transition anything, so it is safe to issue on page load,
 * and it is expressed as a query rather than a mutation for that reason.
 */
export function useReleaseAssessment(releaseId: string) {
  return useQuery({
    queryKey: qk.releaseAssessment(releaseId),
    queryFn: () => api.post<ReleaseAssessment>(`/v1/materiality/releases/${releaseId}/assess`),
    enabled: Boolean(releaseId),
  });
}

export function useEvidenceEvents(params?: { limit?: string; offset?: string; kind?: string; agent_id?: string }) {
  return useQuery({
    queryKey: qk.evidenceEvents(params),
    queryFn: () =>
      api.get<Page<EvidenceEvent>>("/v1/evidence", {
        limit: params?.limit ?? "50",
        offset: params?.offset ?? "0",
        kind: params?.kind,
        agent_id: params?.agent_id,
      }),
  });
}

export function useEvidenceBatches(params?: { limit?: string; offset?: string }) {
  return useQuery({
    queryKey: qk.evidenceBatches(params),
    queryFn: () =>
      api.get<Page<EvidenceBatch>>("/v1/evidence/-/batches", {
        limit: params?.limit ?? "20",
        offset: params?.offset ?? "0",
      }),
  });
}

export function useEvidenceChain() {
  return useQuery({
    queryKey: qk.evidenceChain,
    queryFn: () => api.get<ChainVerification>("/v1/evidence/-/verify"),
  });
}

export function useInclusionProof(eventId: string, enabled: boolean) {
  return useQuery({
    queryKey: qk.inclusionProof(eventId),
    queryFn: () => api.get<InclusionProof>(`/v1/evidence/${eventId}/proof`),
    enabled: enabled && Boolean(eventId),
  });
}

export function useGraphNodes(params?: { limit?: string; offset?: string }) {
  return useQuery({
    queryKey: qk.graphNodes(params),
    queryFn: () =>
      api.get<Page<GraphNode>>("/v1/graph/nodes", {
        limit: params?.limit ?? "200",
        offset: params?.offset ?? "0",
      }),
  });
}

export function useGraphEdges(params?: { limit?: string; offset?: string; kind?: string }) {
  return useQuery({
    queryKey: qk.graphEdges(params),
    queryFn: () =>
      api.get<Page<GraphEdge>>("/v1/graph/edges", {
        limit: params?.limit ?? "200",
        offset: params?.offset ?? "0",
        kind: params?.kind,
      }),
  });
}

export function useBlastRadius(nodeId: string, enabled: boolean) {
  return useQuery({
    queryKey: qk.blastRadius(nodeId),
    queryFn: () => api.get<BlastRadius>(`/v1/graph/nodes/${nodeId}/blast-radius`),
    enabled: enabled && Boolean(nodeId),
  });
}

export function useCustomers(params?: { limit?: string; offset?: string }) {
  return useQuery({
    queryKey: qk.customers(params),
    queryFn: () =>
      api.get<Page<CustomerSummary>>("/v1/customers", {
        limit: params?.limit ?? "50",
        offset: params?.offset ?? "0",
      }),
  });
}

export function useCustomer(customerId: string) {
  return useQuery({
    queryKey: qk.customer(customerId),
    queryFn: () => api.get<CustomerDetail>(`/v1/customers/${customerId}`),
    enabled: Boolean(customerId),
  });
}

export function useCustomerReadiness(customerId: string) {
  return useQuery({
    queryKey: qk.customerReadiness(customerId),
    queryFn: () => api.get<ReadinessResponse>(`/v1/customers/${customerId}/readiness`),
    enabled: Boolean(customerId),
  });
}

export function useEngagements(params?: { limit?: string; offset?: string }) {
  return useQuery({
    queryKey: qk.engagements(params),
    queryFn: () =>
      api.get<Page<EngagementSummary>>("/v1/engagements", {
        limit: params?.limit ?? "50",
        offset: params?.offset ?? "0",
      }),
  });
}

export function useEngagement(engagementId: string) {
  return useQuery({
    queryKey: qk.engagement(engagementId),
    queryFn: () => api.get<EngagementDetail>(`/v1/engagements/${engagementId}`),
    enabled: Boolean(engagementId),
  });
}

export function useAccreditations(params?: { limit?: string; offset?: string; state?: string[] }) {
  return useQuery({
    queryKey: qk.accreditations(params as Record<string, string>),
    queryFn: () =>
      api.get<Page<AccreditationSummary>>("/v1/accreditations", {
        limit: params?.limit ?? "50",
        offset: params?.offset ?? "0",
        state: params?.state,
      }),
  });
}

export function useAccreditation(accreditationId: string) {
  return useQuery({
    queryKey: qk.accreditation(accreditationId),
    queryFn: () => api.get<AccreditationDetail>(`/v1/accreditations/${accreditationId}`),
    enabled: Boolean(accreditationId),
  });
}

export function useAttestations(params?: { limit?: string; offset?: string }) {
  return useQuery({
    queryKey: qk.attestations(params),
    queryFn: () =>
      api.get<Page<AttestationRun>>("/v1/attestations/runs", {
        limit: params?.limit ?? "50",
        offset: params?.offset ?? "0",
      }),
  });
}

export function useFindings(params?: { limit?: string; offset?: string }) {
  return useQuery({
    queryKey: qk.findings(params),
    queryFn: () =>
      api.get<Page<Finding>>("/v1/assurance/findings", {
        limit: params?.limit ?? "50",
        offset: params?.offset ?? "0",
      }),
  });
}

export function usePolicies() {
  return useQuery({
    queryKey: qk.policies,
    queryFn: () => api.get<PolicySummary[]>("/v1/policies"),
  });
}

// Versions are per-policy on the API. This previously called `/v1/policy/versions` with
// no argument, which is not a route that exists — the screen rendered a permanent error.
export function usePolicyVersions(policyId: string | undefined) {
  return useQuery({
    queryKey: qk.policyVersions(policyId ?? ""),
    queryFn: () => api.get<PolicyVersion[]>(`/v1/policies/${policyId}/versions`),
    enabled: Boolean(policyId),
  });
}

export function usePolicyDecisions(params?: { limit?: string; offset?: string }) {
  return useQuery({
    queryKey: qk.policyDecisions(params),
    queryFn: () =>
      api.get<Page<PolicyDecision>>("/v1/policies/-/decisions", {
        limit: params?.limit ?? "50",
        offset: params?.offset ?? "0",
      }),
  });
}

export function useModelRoutingOverview() {
  return useQuery({
    queryKey: qk.modelRoutingOverview,
    queryFn: () => api.get<ModelRoutingOverview>("/v1/model-routing/overview"),
  });
}

export function useModelCatalogue(params?: { limit?: string }) {
  return useQuery({
    queryKey: qk.modelCatalogue(params),
    queryFn: () =>
      api.get<ModelCatalogPage>("/v1/model-routing/catalogue/entries", {
        limit: params?.limit ?? "100",
      }),
  });
}

// Returns a bare array, not a page. The hook used to declare `Page<SloDefinition>` and
// read `.items` off it, so the table bound to `undefined` and rendered permanently empty.
export function useSloDefinitions(params?: { engagementId?: string }) {
  return useQuery({
    queryKey: qk.sloDefinitions(params as Record<string, string> | undefined),
    queryFn: () => api.get<SloDefinition[]>("/v1/slos", { engagement_id: params?.engagementId }),
  });
}

/** Attainment, open breaches and accrued credit for every SLO on one engagement.
 *
 * These live on a separate endpoint rather than on the SLO row because computing them
 * means scanning the measurement history, which is not something a list endpoint should
 * do per row.
 */
export function useEngagementSloSummary(engagementId: string | undefined) {
  return useQuery({
    queryKey: qk.engagementSloSummary(engagementId ?? ""),
    queryFn: () =>
      api.get<EngagementSloRollup>(`/v1/slos/-/engagements/${engagementId}/summary`),
    enabled: Boolean(engagementId),
  });
}

export function useSloMeasurements(sloId: string) {
  return useQuery({
    queryKey: qk.sloMeasurements(sloId),
    queryFn: () =>
      api.get<Page<SloMeasurement>>(`/v1/slos/${sloId}/measurements`, { limit: "90", offset: "0" }),
    enabled: Boolean(sloId),
  });
}

export function useSloBreaches(sloId: string) {
  return useQuery({
    queryKey: qk.sloBreaches(sloId),
    queryFn: () => api.get<SloBreach[]>(`/v1/slos/${sloId}/breaches`),
    enabled: Boolean(sloId),
  });
}

export function useFrameworks() {
  return useQuery({
    queryKey: qk.frameworks,
    queryFn: () => api.get<Framework[]>("/v1/frameworks"),
  });
}

export function useFrameworkControls(frameworkId: string) {
  return useQuery({
    queryKey: qk.frameworkControls(frameworkId),
    queryFn: () => api.get<FrameworkControl[]>(`/v1/frameworks/${frameworkId}/controls`),
    enabled: Boolean(frameworkId),
  });
}

export function useProbeSuites() {
  return useQuery({
    queryKey: qk.probeSuites,
    queryFn: () => api.get<ProbeSuite[]>("/v1/assurance/probe-suites"),
  });
}

export function useProbeRuns(params?: { agent_id?: string; limit?: string }) {
  return useQuery({
    queryKey: qk.probeRuns(params),
    queryFn: () =>
      api.get<Page<ProbeRun>>("/v1/assurance/probe-runs", {
        limit: params?.limit ?? "30",
        offset: "0",
        ...(params?.agent_id ? { agent_id: params.agent_id } : {}),
      }),
  });
}

export function useProbeRunDetail(runId: string) {
  return useQuery({
    queryKey: qk.probeRunDetail(runId),
    queryFn: () => api.get<ProbeRunDetail>(`/v1/assurance/probe-runs/${runId}`),
    enabled: Boolean(runId),
  });
}

export function useRuleGaps(agentId: string, versionId: string, framework?: string) {
  return useQuery({
    queryKey: qk.ruleGaps(agentId, versionId, framework),
    queryFn: () =>
      api.get<RuleGapReport>(`/v1/agents/${agentId}/versions/${versionId}/rule-gaps`, {
        ...(framework ? { framework } : {}),
      }),
    enabled: Boolean(agentId) && Boolean(versionId),
  });
}

export function useTrustPortal(customerSlug: string, engagementSlug: string) {
  return useQuery({
    queryKey: qk.trustPortal(customerSlug, engagementSlug),
    queryFn: () =>
      api.get<TrustPortalView>(`/v1/portal/${customerSlug}/${engagementSlug}`),
    enabled: Boolean(customerSlug) && Boolean(engagementSlug),
  });
}
