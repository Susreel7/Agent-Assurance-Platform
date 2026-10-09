/** API boundary types — names mirror Python Pydantic models and Postgres enum labels.
 *
 * Types declared as `Wire<"SomeSchema">` are the API's own shape, resolved out of
 * `schema.d.ts`, which `npm run client` generates from `openapi.json`. Prefer that form
 * for anything the API returns.
 *
 * Hand-writing these is what the rest of this file used to do, and the result was silent
 * drift: `PolicyVersion` declared `version`, `digest` and `signature_status` while the
 * API returned `semver`, `rules_digest` and no signature status at all. The tables built
 * on it rendered blank columns and nothing failed, because a hand-written type agrees
 * with itself. The mock fixtures were written from the same wrong types, so mock mode
 * looked correct too.
 *
 * Shapes the API does not define — view models assembled in the browser — stay
 * hand-written below. The distinction is the point: `Wire` means "the server said so".
 */

import type { components } from "@/api/schema";

export type Wire<K extends keyof components["schemas"]> = components["schemas"][K];

export type Page<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
};

// ---- Shared enums (Postgres labels, snake_case) ----

export type LifecycleState = "dev" | "test" | "staging" | "production" | "retired";

export type OwnershipRole =
  | "accountable"
  | "approver_of_record"
  | "technical"
  | "change_authority"
  | "business";

export type ComponentKind =
  | "model"
  | "prompt"
  | "tool"
  | "mcp_server"
  | "library"
  | "dataset"
  | "sub_agent"
  | "vector_store"
  | "data_source"
  | "guardrail";

export type ChangeCategory =
  | "model"
  | "inference_params"
  | "prompt"
  | "tool"
  | "mcp_server"
  | "capability"
  | "dependency"
  | "data_source"
  | "data_class"
  | "residency"
  | "guardrail"
  | "oversight"
  | "resilience"
  | "delegation"
  | "deployment"
  | "metadata"
  | "skill"
  | "sub_agent"
  | "config"
  | "rule_obligation"
  | "rule_source"
  | "model_policy"
  | "memory_retrieval";

export type ChangeOperation = "added" | "removed" | "modified" | "renamed";

export type EnforcementLevel = "advisory" | "soft" | "hard";

export type ImpactDimension = "behaviour" | "security" | "cost" | "latency" | "compliance";

export type Severity = "critical" | "high" | "medium" | "low" | "info";

export type Materiality = "material" | "immaterial" | "needs_review";

export type ReleaseState =
  | "draft"
  | "proposed"
  | "approved"
  | "rolled_out"
  | "rolled_back"
  | "abandoned";

export type AccreditationImpact = "none" | "requires_revalidation" | "suspends";

export type CustomerStatus = "prospect" | "active" | "suspended" | "offboarding" | "churned";

export type Sector =
  | "financial_services"
  | "insurance"
  | "healthcare"
  | "life_sciences"
  | "public_sector"
  | "defence"
  | "telecom"
  | "energy"
  | "utilities"
  | "retail"
  | "manufacturing"
  | "transport"
  | "technology"
  | "education"
  | "other";

export type CriticalityTier = "tier_1" | "tier_2" | "tier_3";

export type ContactRole =
  | "security_reviewer"
  | "data_protection"
  | "business_owner"
  | "procurement"
  | "technical"
  | "executive_sponsor";

export type RequirementLevel = "mandatory" | "expected" | "informational";

export type FrameworkKind =
  | "standard"
  | "regulation"
  | "certification"
  | "questionnaire"
  | "internal_policy";

export type AnswerMode = "evidence" | "narrative" | "hybrid" | "not_applicable";

export type EngagementState = "draft" | "active" | "suspended" | "terminated";

export type VersionUptake = "pinned" | "auto_patch" | "auto_minor" | "auto_all";

export type AccreditationState =
  | "draft"
  | "submitted"
  | "approved"
  | "suspended"
  | "expired"
  | "withdrawn";

export type EvidenceKind =
  | "bom_completeness"
  | "model_inventory"
  | "tool_permission_inventory"
  | "data_class_inventory"
  | "residency_proof"
  | "redaction_record"
  | "approval_record"
  | "ownership_record"
  | "oversight_record"
  | "change_history"
  | "materiality_verdict"
  | "vulnerability_scan"
  | "adversarial_probe"
  | "service_level_attainment"
  | "chain_integrity"
  | "incident_record";

export type GraphNodeKind =
  | "agent"
  | "model"
  | "tool"
  | "mcp_server"
  | "data_source"
  | "dataset"
  | "sub_agent"
  | "external_service";

export type GraphEdgeKind = "declared" | "observed";

export type FindingSource = "probe" | "cve" | "drift";

// Mirrors the `finding_state` Postgres enum exactly. It previously listed a
// `remediated` value the database has never had, and omitted `triaged`, `mitigated`
// and `fixed` — so three real states rendered as an unhandled default and one
// impossible state typechecked.
export type FindingState =
  | "open"
  | "triaged"
  | "accepted"
  | "mitigated"
  | "fixed"
  | "false_positive";

export type PolicyDecisionOutcome = "allow" | "deny" | "redact" | "reroute" | "require_approval";

export type SloKind =
  | "availability"
  | "latency_p95"
  | "latency_p99"
  | "error_rate"
  | "resolution_p1"
  | "resolution_p2"
  | "freshness"
  | "throughput";

export type SloWindow = "daily" | "weekly" | "monthly" | "quarterly" | "annual";

// Ordered least to most permissive. Safeguards and consent are distinct GDPR Chapter V
// bases, not two spellings of one stance.
export type CrossBorderTransfer =
  | "prohibited"
  | "permitted_with_safeguards"
  | "permitted_with_consent"
  | "permitted";

export type DeploymentMode = "saas" | "byoc" | "airgap";

// ---- Registry ----

export type PostureContributor = {
  factor: string;
  weight: number;
  detail: string;
};

export type PostureScore = {
  score: number;
  contributors: PostureContributor[];
};

export type AgentSummary = {
  id: string;
  urn: string;
  display_name: string;
  owning_team: string | null;
  lifecycle_state: LifecycleState;
  runtime_framework: string | null;
  environment: LifecycleState;
  posture_score: number;
  accreditation_state: AccreditationState | null;
  has_drift: boolean;
  last_release_id: string | null;
  last_release_tag: string | null;
  last_release_at: string | null;
  customer_ids: string[];
};

export type AgentDetail = AgentSummary & {
  description: string | null;
  current_version_id: string | null;
  current_semver: string | null;
  baseline_version_id: string | null;
  baseline_semver: string | null;
  accredited_version_id: string | null;
  accredited_semver: string | null;
  discovered_at: string | null;
  first_seen_source: string;
  created_at: string;
  updated_at: string;
  posture: PostureScore;
};

export type AgentVersion = {
  id: string;
  agent_id: string;
  semver: string;
  descriptor_digest: string;
  runtime_framework: string | null;
  runtime_language: string | null;
  environment: LifecycleState;
  autonomy: string | null;
  vcs_provider: string | null;
  vcs_repo: string | null;
  vcs_ref: string | null;
  published_at: string;
  published_by: string;
  is_baseline: boolean;
  is_current: boolean;
  descriptor_json: Record<string, unknown>;
};

// The hand-written version of this also declared `licence`, `human_approval`,
// `declared_meta` and `observed_meta`, none of which the API returns.
export type BomComponent = Wire<"BomComponentOut">;

export type Ownership = {
  id: string;
  agent_id: string;
  role: OwnershipRole;
  principal_id: string;
  source: string;
  valid_from: string;
  valid_to: string | null;
};

// ---- Releases ----

export type SemanticChange = {
  category: ChangeCategory;
  operation: ChangeOperation;
  path: string;
  subject: string;
  before_value: unknown;
  after_value: unknown;
  summary: string;
  detail: string | null;
  impacts: ImpactDimension[];
  severity: Severity;
  verdict: Materiality;
  rules_fired: string[];
  detected_by: string;
};

export type ReleaseDiff = {
  from_semver: string | null;
  to_semver: string;
  changes: SemanticChange[];
};

export type ReleaseSummary = {
  id: string;
  agent_id: string;
  agent_urn: string;
  release_tag: string;
  title: string | null;
  state: ReleaseState;
  from_semver: string | null;
  to_semver: string;
  change_count: number;
  material_count: number;
  review_count: number;
  impacts: ImpactDimension[];
  categories: ChangeCategory[];
  accreditation_impact: AccreditationImpact;
  affected_accreditations: number;
  vcs_provider: string | null;
  vcs_repo: string | null;
  vcs_ref: string | null;
  vcs_pr_ref: string | null;
  proposed_by: string | null;
  created_at: string;
};

export type ReviewSentence = {
  change_path: string;
  rule_ids: string[];
  template_id: string;
  text: string;
  severity: Severity;
  materiality: Materiality;
  enforcement: EnforcementLevel;
};

export type ReleaseReviewBrief = {
  release_id: string | null;
  from_semver: string | null;
  to_semver: string;
  descriptor_digest: string;
  headline: string;
  re_accreditation: ReviewSentence[];
  needs_review: ReviewSentence[];
  informational: ReviewSentence[];
  accreditation_impact: AccreditationImpact;
  blocking_rule_ids: string[];
  generated_at: string;
  generator_label: string;
};

export type ReleaseDetail = ReleaseSummary & {
  notes: string | null;
  changes: SemanticChange[];
  approved_by: string | null;
  approved_at: string | null;
  rolled_out_at: string | null;
  to_descriptor_digest: string | null;
  reviewed_descriptor_digest: string | null;
  review_brief: ReleaseReviewBrief | null;
};

export type ReleaseGateVerdict = {
  allowed: boolean;
  headline: string;
  material_count: number;
  review_count: number;
  accreditation_impact: AccreditationImpact;
  affected_accreditations: string[];
  blocking_changes: SemanticChange[];
  advisory: string[];
};

export type ReleaseAssessment = Wire<"AssessmentOut">;
export type AffectedAccreditation = Wire<"AffectedAccreditation">;

// ---- Evidence ----

export type EvidenceEvent = Wire<"EvidenceEventOut">;
export type EvidenceBatch = Wire<"EvidenceBatchOut">;
export type ChainVerification = Wire<"ChainVerification">;
export type InclusionProof = Wire<"InclusionProof">;

// ---- Graph ----

export type GraphNode = {
  id: string;
  kind: GraphNodeKind;
  label: string;
  agent_id: string | null;
  urn: string | null;
};

export type GraphEdge = {
  id: string;
  source_id: string;
  target_id: string;
  kind: GraphEdgeKind;
  label: string | null;
};

export type GraphNeighbourhood = Wire<"Neighbourhood">;
export type NeighbourhoodNode = Wire<"NeighbourhoodNode">;
export type BlastRadius = Wire<"BlastRadius">;
export type BlastRadiusNode = Wire<"BlastRadiusNode">;

// ---- Customers ----

export type ContactOut = {
  id: string;
  role: ContactRole;
  principal_id: string;
  display_name: string | null;
  valid_from: string;
};

export type Framework = {
  id: string;
  slug: string;
  name: string;
  kind: FrameworkKind;
  publisher: string | null;
  version: string | null;
  is_builtin: boolean;
  control_count: number;
};

export type FrameworkControl = {
  id: string;
  framework_id: string;
  control_ref: string;
  title: string;
  requirement: string | null;
  section: string | null;
  ordinal: number;
  answer_mode: AnswerMode;
};

export type FrameworkRequirementOut = {
  id: string;
  framework: Framework;
  level: RequirementLevel;
  scoped_controls: string[];
  required_since: string | null;
  notes: string | null;
};

export type CustomerSummary = {
  id: string;
  slug: string;
  legal_name: string;
  display_name: string;
  status: CustomerStatus;
  sector: Sector | null;
  criticality: CriticalityTier;
  home_jurisdiction: string | null;
  engagement_count: number;
  agent_count: number;
  framework_count: number;
  drift_count: number;
  created_at: string;
};

export type CustomerDetail = CustomerSummary & {
  operating_jurisdictions: string[];
  external_ref: string | null;
  notes: string | null;
  updated_at: string;
  contacts: ContactOut[];
  frameworks: FrameworkRequirementOut[];
};

export type ControlGap = {
  framework_slug: string;
  framework_name: string;
  control_ref: string;
  title: string;
  answer_mode: AnswerMode;
  reason: string;
};

export type ReadinessByFramework = {
  framework: Framework;
  level: RequirementLevel;
  controls_in_scope: number;
  answerable: number;
  partial: number;
  narrative_only: number;
  unmapped: number;
  coverage_pct: number;
};

export type CustomerReadiness = {
  customer_id: string;
  customer_display_name: string;
  frameworks: ReadinessByFramework[];
  gaps: ControlGap[];
};

export type ReadinessResponse = {
  readiness: CustomerReadiness;
  headline: string;
  total_controls: number;
  total_answerable: number;
  coverage_pct: number;
};

// ---- Engagements ----

export type ServiceLevel = {
  id: string;
  engagement_id: string;
  kind: SloKind;
  target: number;
  unit: string | null;
  measurement_window: SloWindow;
  penalty_basis: string;
  penalty_detail: string | null;
};

export type EngagementAgent = {
  id: string;
  engagement_id: string;
  agent_id: string;
  agent_urn: string;
  agent_display_name: string;
  accredited_version_id: string | null;
  accredited_semver: string | null;
  deployed_version_id: string | null;
  deployed_semver: string | null;
  has_drift: boolean;
  uptake: VersionUptake;
  in_scope_since: string;
};

export type EngagementSummary = {
  id: string;
  customer_id: string;
  customer_display_name: string;
  /** Half of the portal link: `/portal/{customer_slug}/{slug}`. See D-035. */
  customer_slug: string;
  slug: string;
  name: string;
  state: EngagementState;
  agent_count: number;
  permitted_regions: string[];
  slo_attainment_pct: number;
  drift_count: number;
  starts_on: string | null;
  ends_on: string | null;
};

export type EngagementDetail = EngagementSummary & {
  description: string | null;
  prohibited_regions: string[];
  cross_border_transfer: CrossBorderTransfer;
  permitted_data_classes: string[];
  contract_ref: string | null;
  delivery_lead: string | null;
  customer_approver: string | null;
  created_at: string;
  updated_at: string;
  agents: EngagementAgent[];
  service_levels: ServiceLevel[];
};

// ---- Accreditation ----

export type AccreditationControl = {
  control_ref: string;
  title: string;
  answer_mode: AnswerMode;
  satisfied: boolean;
  narrative: string | null;
  evidence_event_ids: string[];
};

export type AccreditationPack = {
  id: string;
  accreditation_id: string;
  version: number;
  pack_uri: string;
  digest: string;
  rendered_at: string;
  signature_status: "valid" | "invalid" | "unsigned";
};

export type AccreditationTransition = {
  from_state: AccreditationState | null;
  to_state: AccreditationState;
  actor: string;
  occurred_at: string;
  reason: string | null;
};

export type AccreditationSummary = {
  id: string;
  reference: string;
  agent_id: string;
  agent_urn: string;
  customer_id: string;
  customer_display_name: string;
  engagement_id: string;
  state: AccreditationState;
  framework_slug: string;
  framework_name: string;
  version_semver: string;
  submitted_at: string | null;
  approved_at: string | null;
  expires_on: string | null;
};

export type AccreditationDetail = AccreditationSummary & {
  controls: AccreditationControl[];
  pack: AccreditationPack | null;
  transitions: AccreditationTransition[];
};

export type AttestationRun = Wire<"AttestationRunOut">;

// ---- Findings ----

export type Finding = Wire<"FindingOut">;

// ---- Policy ----

export type PolicySummary = Wire<"PolicySummary">;
export type PolicyVersion = Wire<"PolicyVersionOut">;
export type PolicyDecision = Wire<"PolicyDecisionOut">;

// ---- Service levels ----

export type SloDefinition = Wire<"SloOut">;
export type SloMeasurement = Wire<"MeasurementOut">;
export type SloBreach = Wire<"BreachOut">;
export type SloSummary = Wire<"EngagementSloSummary">;
// Named for what it is rather than mirroring the API's `EngagementSummaryOut`, which
// collides with the engagements domain's own summary type. This one is service levels.
export type EngagementSloRollup = Wire<"EngagementSummaryOut">;

// ---- Operations: runs, cost, tools ----

export type RunOutcome =
  | "running"
  | "succeeded"
  | "failed"
  | "refused"
  | "timed_out"
  | "cancelled";

export type ToolSurface = "mcp" | "native" | "retrieval" | "sub_agent" | "handoff";

export type RunRow = {
  id: string;
  agent_id: string;
  agent_display_name: string;
  agent_urn: string;
  environment: LifecycleState;
  started_at: string;
  ended_at: string | null;
  duration_ms: number | null;
  outcome: RunOutcome;
  step_count: number;
  tool_call_count: number;
  retry_count: number;
  model: string | null;
  tokens_in: number;
  tokens_out: number;
  /** Millionths of a USD. Never a float — see lib/formatters.formatUsdMicros. */
  cost_micros: number;
  escalated: boolean;
  guardrail_blocks: number;
  error_kind: string | null;
  trace_id: string | null;
};

export type StepKind =
  | "node"
  | "llm"
  | "tool"
  | "mcp_tool"
  | "retrieval"
  | "guardrail"
  | "handoff"
  | "sub_agent";

export type StepRow = {
  id: string;
  seq: number;
  parent_seq: number | null;
  kind: StepKind;
  name: string;
  surface: ToolSurface | null;
  server_name: string;
  started_at: string;
  ended_at: string | null;
  duration_ms: number | null;
  outcome: RunOutcome;
  attempt: number;
  model: string | null;
  tokens_in: number;
  tokens_out: number;
  cost_micros: number;
  error_kind: string | null;
};

/** `GET /v1/operations/runs/{run_id}` — per docs/contracts/tracing.md */
export type RunDetail = {
  run: RunRow;
  steps: StepRow[];
  self_ms_by_seq: Record<number, number>;
  critical_path: number[];
  steps_truncated: boolean;
};

export type GraphNodeStat = {
  name: string;
  kind: StepKind;
  runs: number;
  executions: number;
  failures: number;
  p50_duration_ms: number;
  p95_duration_ms: number;
  cost_micros: number;
  tools: string[];
};

export type GraphEdgeStat = {
  from_node: string;
  to_node: string;
  traversals: number;
  failures: number;
};

/** `GET /v1/operations/agents/{agent_id}/graph?days=30` */
export type ObservedGraph = {
  agent_id: string;
  window_days: number;
  nodes: GraphNodeStat[];
  edges: GraphEdgeStat[];
  entry_nodes: string[];
  terminal_nodes: string[];
};

/**
 * Parallel arrays, not a list of points: `days[i]` lines up with index `i` of every
 * series in `by_environment`, of `totals` and of `failures`. That is the shape the
 * chart wants, and it avoids sending the same date once per environment.
 */
export type ActivitySeries = {
  days: string[];
  by_environment: Record<string, number[]>;
  totals: number[];
  failures: number[];
};

export type CostDay = {
  day: string;
  cost_micros: number;
  tokens_in: number;
  tokens_out: number;
  runs: number;
};

export type CostSlice = {
  label: string;
  cost_micros: number;
  tokens: number;
  runs: number;
  share_pct: number;
};

export type CostReport = {
  window_days: number;
  total_cost_micros: number;
  total_tokens: number;
  total_runs: number;
  previous_cost_micros: number;
  by_day: CostDay[];
  by_model: CostSlice[];
  by_agent: CostSlice[];
  by_environment: CostSlice[];
};

export type ToolRow = {
  surface: ToolSurface;
  server_name: string;
  tool_name: string;
  agents: number;
  calls: number;
  errors: number;
  denied: number;
  error_rate_pct: number;
  mean_duration_ms: number;
  max_duration_ms: number;
  /** False when any agent calling this tool never declared it in its bill of materials. */
  declared: boolean;
  undeclared_agents: number;
};

export type ToolInventory = {
  window_days: number;
  items: ToolRow[];
  mcp_servers: number;
  undeclared: number;
};

export type McpServerRow = {
  server_name: string;
  tools: number;
  agents: number;
  calls: number;
  errors: number;
  denied: number;
  error_rate_pct: number;
  mean_duration_ms: number;
  last_seen_at: string | null;
  declared: boolean;
  undeclared_agents: number;
  tool_names: string[];
};

export type McpInventory = {
  window_days: number;
  servers: McpServerRow[];
  total_calls: number;
  undeclared_servers: number;
};

/** LangGraph, CrewAI, the Cursor SDK — not the compliance frameworks in `Framework`. */
export type FrameworkShare = {
  framework: string;
  agents: number;
  runs: number;
  share_pct: number;
};

export type RunOutcomeCount = { outcome: RunOutcome; runs: number };

export type ErrorKindCount = { error_kind: string; runs: number };

export type OperationsSnapshot = {
  window_days: number;
  generated_at: string;
  runs_total: number;
  runs_previous: number;
  runs_failed: number;
  runs_refused: number;
  running_now: number;
  agents_active: number;
  escalations: number;
  success_rate_pct: number;
  p50_duration_ms: number;
  p95_duration_ms: number;
  activity: ActivitySeries;
  outcomes: RunOutcomeCount[];
  frameworks: FrameworkShare[];
  cost: CostReport;
  tools: ToolInventory;
  recent_runs: RunRow[];
};

/** `GET /v1/operations/agents/{id}` — the estate's questions, asked of one agent. */
export type AgentOperations = {
  agent_id: string;
  window_days: number;
  generated_at: string;
  runs_total: number;
  runs_previous: number;
  runs_failed: number;
  runs_refused: number;
  running_now: number;
  escalations: number;
  success_rate_pct: number;
  p50_duration_ms: number;
  p95_duration_ms: number;
  cost_micros: number;
  previous_cost_micros: number;
  tokens: number;
  activity: ActivitySeries;
  outcomes: RunOutcomeCount[];
  error_kinds: ErrorKindCount[];
  by_model: CostSlice[];
  cost_by_day: CostDay[];
  tools: ToolRow[];
  mcp_servers: McpServerRow[];
  recent_runs: RunRow[];
};

// ---- Dashboard & portal ----

export type AttentionItem = {
  id: string;
  title: string;
  consequence: string;
  href: string;
  severity: string;
  occurred_at: string;
};

export type AgentHealth = "healthy" | "warning" | "at_risk" | "critical";

export type EstateTotals = {
  agents_total: number;
  agents_in_production: number;
  agents_accredited: number;
  agents_unaccredited: number;
  agents_drifted: number;
  open_findings: number;
  open_critical_findings: number;
  approvals_waiting: number;
  /** The share of service levels meeting target — not an availability figure. */
  slos_meeting_target_pct: number;
};

export type HealthMix = {
  healthy: number;
  warning: number;
  at_risk: number;
  critical: number;
};

/** A governance ratio that always travels with the two numbers it came from. */
export type ComplianceBar = {
  id: string;
  label: string;
  covered: number;
  applicable: number;
  pct: number;
  explain: string;
};

/** One agent, with what it is and what it has been doing in the same row. */
export type AgentOpsRow = {
  id: string;
  display_name: string;
  urn: string;
  lifecycle_state: LifecycleState;
  runtime_framework: string | null;
  semver: string | null;
  health: AgentHealth;
  accreditation_state: AccreditationState | null;
  drifted: boolean;
  open_findings: number;
  open_critical_findings: number;
  runs: number;
  success_rate_pct: number;
  cost_micros: number;
  p95_duration_ms: number;
  escalations: number;
  running_now: number;
  last_run_at: string | null;
  mcp_servers: number;
  tools: number;
};

/**
 * `GET /v1/home/summary?days=N`.
 *
 * One request for the whole landing page. It grew from a much smaller shape that
 * answered only "is anything wrong", which was right for a console with no runtime data
 * in it and stopped being right once there was — cost, failure rate and which framework
 * the estate runs on are the first things anyone asks, not follow-up questions.
 */
export type DashboardSummary = {
  window_days: number;
  generated_at: string;
  attention: AttentionItem[];
  estate: EstateTotals;
  health: HealthMix;
  compliance: ComplianceBar[];
  operations: OperationsSnapshot;
  agents: AgentOpsRow[];
  recent_releases: ReleaseSummary[];
};

export type TrustPortalView = {
  engagement_slug: string;
  engagement_name: string;
  customer_display_name: string;
  scoped_statement: string;
  agents: Array<{
    agent_urn: string;
    display_name: string;
    accreditation_state: AccreditationState;
    pack_download_uri: string | null;
  }>;
  slo_attainment_pct: number;
  findings_by_severity: Record<Severity, number>;
  residency_summary: string;
  chain_verification: ChainVerification;
};

export type DeploymentInfo = {
  mode: DeploymentMode;
  customer_operated: boolean;
  instance: string;
  environment: string;
  version: string;
  licensee: string;
  license_expires: string | null;
  data_leaves_estate: boolean;
};

export type CompositionElementStatus =
  | "aligned"
  | "declared_only"
  | "observed_only"
  | "conflict";

export type CompositionElement = {
  kind: string;
  key: string;
  declared: boolean;
  observed: boolean;
  status: CompositionElementStatus;
  observed_count: number;
  declared_meta: Record<string, unknown>;
};

export type CompositionSummary = {
  agent_id: string;
  agent_version_id: string;
  semver: string;
  elements: CompositionElement[];
  rule_sources: Array<Record<string, unknown>>;
  rule_obligations: Array<Record<string, unknown>>;
  model_policy: Record<string, unknown> | null;
};

export type CompositionReconciliation = {
  agent_id: string;
  agent_version_id: string;
  window_days: number;
  window_start: string;
  window_end: string;
  items: Array<Record<string, unknown>>;
  elements: CompositionElement[];
};

export type ModelClassificationState = "classified" | "unclassified" | "deprecated";

export type ModelCatalogEntry = {
  id: string;
  org_id: string | null;
  provider: string;
  model_id: string;
  display_name: string | null;
  hosting_mode: string;
  primary_region: string;
  jurisdiction: string;
  cross_border_ok: boolean;
  data_handling_terms: string;
  classification_state: ModelClassificationState;
  source: string;
  source_url: string | null;
  valid_from: string;
  valid_to: string | null;
  digest: string;
};

export type ModelCatalogPage = {
  items: ModelCatalogEntry[];
  total: number;
  unclassified_count: number;
};

export type ModelRoutingOverview = {
  unclassified_models: ModelCatalogEntry[];
  recent_denials: Array<{
    occurred_at: string;
    outcome: string;
    reason_code: string;
    agent_id: string | null;
    rule_id: string;
  }>;
  drift_findings: Array<{
    title: string;
    severity: string;
    agent_id: string | null;
    last_seen_at: string;
  }>;
  observation_note: string;
};

export type ProbeSuite = {
  id: string;
  slug: string;
  name: string;
  category: string;
  probe_count: number;
  cadence: string;
  is_builtin: boolean;
  content_digest: string | null;
  owasp_coverage: string[];
};

export type JudgeAdvisoryOut = {
  verdict: string;
  disagrees_with_oracle: boolean;
  recorded: boolean;
};

export type ProbeCaseResult = {
  probe_id: string;
  expect: string;
  oracle_verdict: string;
  oracle_passed: boolean;
  execution_verified: boolean;
  gate_passed: boolean;
  judge_advisory: JudgeAdvisoryOut | null;
  recognition_execution_gap: boolean;
  response_digest: string;
  signals: Record<string, unknown>;
  ambiguous: boolean;
};

export type ProbeRunSummary = {
  suite_content_digest: string;
  valid_rollouts: number;
  attempt_budget: number;
  execution_verified_pass: number;
  execution_verified_fail: number;
  judge_advisory_pass: number;
  judge_advisory_fail: number;
  oracle_needs_review: number;
  judge_oracle_disagreements: number;
  gate_level: string;
  gate_blocks_release: boolean;
};

export type ProbeRun = {
  id: string;
  suite_id: string;
  agent_id: string;
  agent_version_id: string;
  started_at: string;
  finished_at: string | null;
  result: string | null;
  probes_run: number;
  probes_passed: number;
  probes_failed: number;
  triggered_by: string;
};

export type ProbeRunDetail = ProbeRun & {
  results: ProbeCaseResult[];
  summary: ProbeRunSummary | null;
  suite_slug: string | null;
};

export type RuleGap = {
  template_id: string;
  control_ref: string;
  framework_slug: string;
  required_statement: string;
  status: "covered" | "partial" | "missing" | "conflict";
  matching_obligation_ids: string[];
  suggested_obligation: {
    id: string;
    template_ref: string;
    category: string;
    polarity: string;
    statement: string;
    strength: string;
    remediation_hint: string | null;
  } | null;
};

export type RuleGapReport = {
  agent_id: string;
  agent_version_id: string;
  frameworks: string[];
  gaps: RuleGap[];
  covered_count: number;
  generated_at: string;
  content_digest: string;
};

// ---- Runtime suite (Router, Observe, Prompt, Evaluate) ----

export type SuiteModuleId = "router" | "observe" | "prompt" | "evaluate";

export type ModulesManifest = Wire<"ModulesManifestOut">;
export type SuiteModuleOut = Wire<"SuiteModuleOut">;
export type ProjectOut = Wire<"ProjectOut">;
export type ProjectPage = Wire<"ProjectPage">;

export type DeploymentOut = Wire<"DeploymentOut">;
export type DeploymentPage = Wire<"DeploymentPage">;
export type DeploymentCreate = Wire<"DeploymentCreate">;
export type DeploymentUpdate = Wire<"DeploymentUpdate">;

export type RouteOut = Wire<"RouteOut">;
export type RoutePage = Wire<"RoutePage">;
export type RouteCreate = Wire<"RouteCreate">;
export type RouteUpdate = Wire<"RouteUpdate">;
export type RouteSimulateRequest = Wire<"RouteSimulateRequest">;
export type RouteSimulateResult = Wire<"RouteSimulateResult">;
// Qualified because the MCP registry has a `SnapshotOut` of its own — a capability
// snapshot rather than a compiled gateway config — so the generator disambiguates both.
export type SnapshotOut = Wire<"app__domains__model_routing__schemas__SnapshotOut">;
export type SnapshotCompileRequest = Wire<"SnapshotCompileRequest">;

export type TraceSummary = Wire<"TraceSummary">;
export type TracePage = Wire<"TracePage">;
export type TraceDetail = Wire<"TraceDetail">;
export type TraceGraph = Wire<"TraceGraph">;
export type TraceMetrics = Wire<"TraceMetrics">;
export type ObserveFreshness = Wire<"ObserveFreshness">;
export type SessionPage = Wire<"SessionPage">;
export type SessionDetail = Wire<"SessionDetail">;
// Fully qualified because two domains own a `SessionSummary` and FastAPI disambiguates
// both when they collide. F0 added the auth one — "your sessions" on the profile page —
// and the name in this file silently stopped resolving to anything, which nothing
// noticed because `openapi.json` was a snapshot from before that change. This is the
// conditional guarantee PROJECT_STATE describes: `check:api` proves a path is in the
// snapshot, and nothing proved the snapshot was current.
export type SessionSummary = Wire<"app__domains__observe__schemas__SessionSummary">;
export type ExecutionSummary = Wire<"ExecutionSummary">;
export type ExecutionPage = Wire<"ExecutionPage">;
export type ExecutionDetail = Wire<"ExecutionDetail">;
export type ExecutionObservation = Wire<"ExecutionObservation">;
export type ExecutionObservations = Wire<"ExecutionObservations">;
export type ExecutionEvent = Wire<"ExecutionEvent">;
export type ExecutionEvents = Wire<"ExecutionEvents">;
export type ExecutionTimeline = Wire<"ExecutionTimeline">;
export type ExecutionLink = Wire<"ExecutionLink">;
export type PayloadReference = Wire<"PayloadReference">;
export type PayloadContent = Wire<"PayloadContent">;
export type PayloadLegalHold = Wire<"PayloadLegalHold">;
export type PayloadLegalHoldUpdate = Wire<"PayloadLegalHoldUpdate">;
export type ExecutionAnalytics = Wire<"ExecutionAnalytics">;
export type ObservedUser = Wire<"ObservedUser">;
export type ObservedUserPage = Wire<"ObservedUserPage">;
export type UserActivity = Wire<"UserActivity">;
export type SamplingPolicy = Wire<"SamplingPolicy">;
export type SamplingPolicyUpdate = Wire<"SamplingPolicyUpdate">;
export type ObserveLifecycle =
  | "execution.started"
  | "execution.completed"
  | "execution.failed"
  | "observation.started"
  | "observation.completed"
  | "observation.failed"
  | "event.recorded";
export type ObserveLiveEvent = {
  id: number;
  type: ObserveLifecycle;
  trace_id: string | null;
  span_id: string | null;
  cursor: string;
  created_at: string;
  payload: {
    schema_version?: number;
    lifecycle?: ObserveLifecycle;
    execution_id?: string | null;
    parent_span_id?: string | null;
    kind?: string;
    observation_type?: string;
    operation_name?: string;
    outcome?: string;
    status?: string;
    start_time?: string | null;
    end_time?: string | null;
    duration_ms?: number;
    is_terminal?: boolean;
    retry_attempt?: number;
    event_type?: string;
    event_time?: string | null;
    sequence?: number;
  };
};

export type ArtifactOut = Wire<"ArtifactOut">;
export type ArtifactListResponse = Wire<"ArtifactListResponse">;
export type ArtifactCreate = Wire<"ArtifactCreate">;
export type RevisionDetailOut = Wire<"RevisionDetailOut">;
export type RevisionListResponse = Wire<"RevisionListResponse">;
export type RevisionCreate = Wire<"RevisionCreate">;
export type DiffRequest = Wire<"DiffRequest">;
export type DiffResponse = Wire<"DiffResponse">;
export type PromoteLabelRequest = Wire<"PromoteLabelRequest">;
export type PlaygroundRunRequest = Wire<"PlaygroundRunRequest">;
export type PlaygroundRunResponse = Wire<"PlaygroundRunResponse">;
export type PlaygroundRunStatusOut = Wire<"PlaygroundRunStatusOut">;

export type DatasetOut = Wire<"DatasetOut">;
export type DatasetCreate = Wire<"DatasetCreate">;
export type ExperimentOut = Wire<"ExperimentOut">;
export type ExperimentCreate = Wire<"ExperimentCreate">;
export type ExperimentResultsResponse = Wire<"ExperimentResultsResponse">;
export type EvaluatorOut = Wire<"EvaluatorOut">;
export type EvaluatorCreate = Wire<"EvaluatorCreate">;
export type EvaluatorRevisionOut = Wire<"EvaluatorRevisionOut">;
export type ScoreDetailOut = Wire<"ScoreDetailOut">;
export type ScoreOut = Wire<"ScoreOut">;
export type ScoreCreate = Wire<"ScoreCreate">;
export type OnlineRuleOut = Wire<"OnlineRuleOut">;
export type OnlineRuleCreate = Wire<"OnlineRuleCreate">;
export type AnnotationQueueOut = Wire<"AnnotationQueueOut">;
export type AnnotationQueueCreate = Wire<"AnnotationQueueCreate">;
export type AnnotationItemOut = Wire<"AnnotationItemOut">;
export type ReleaseGateOut = Wire<"ReleaseGateOut">;
export type ReleaseGateCreate = Wire<"ReleaseGateCreate">;
export type ReleaseGateEvaluateRequest = Wire<"ReleaseGateEvaluateRequest">;
export type ReleaseGateEvaluateResponse = Wire<"ReleaseGateEvaluateResponse">;
export type IdResponse = Wire<"IdResponse">;

export type PagedDatasets = Wire<"PagedResponse_DatasetOut_">;
export type PagedExperiments = Wire<"PagedResponse_ExperimentOut_">;
export type PagedEvaluators = Wire<"PagedResponse_EvaluatorOut_">;
export type PagedScores = Wire<"PagedResponse_ScoreDetailOut_">;
export type PagedOnlineRules = Wire<"PagedResponse_OnlineRuleOut_">;
export type PagedAnnotationQueues = Wire<"PagedResponse_AnnotationQueueOut_">;
export type PagedAnnotationItems = Wire<"PagedResponse_AnnotationItemOut_">;
export type PagedReleaseGates = Wire<"PagedResponse_ReleaseGateOut_">;
