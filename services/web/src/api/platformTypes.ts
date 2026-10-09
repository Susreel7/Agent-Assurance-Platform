/**
 * Wire types for the account, access, credential, tool-registry and audit surface.
 *
 * Kept apart from `types.ts` because these five domains answer a different question from
 * the rest of the console. Everything in `types.ts` describes what agents are and what
 * they did; everything here describes who may do it, with which credential, against which
 * tool — and it is read by the admin screens rather than by the assurance ones.
 *
 * Hand-written rather than pulled from `schema.d.ts`. The generated file is 700kB of
 * deeply-nested `components["schemas"][...]` lookups; naming the shapes once here is what
 * lets a screen say `MemberSummary` instead. `npm run check:api` keeps the *paths* honest
 * and `tsc` keeps the usage honest, which is the pair that actually catches drift.
 */

/** Mirrors `app.domains.registry.schemas.LifecycleState`. */
export type LifecycleState = "dev" | "test" | "staging" | "production" | "retired";

export type RiskTier = "low" | "medium" | "high" | "critical";

export interface OffsetPage<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

/**
 * A keyset page. No `total`, by design — see `app/api/pagination.py`: counting a
 * partitioned append-only table to render "page 3 of 4,192" costs more than the page and
 * is stale before it paints.
 */
export interface KeysetPage<T> {
  items: T[];
  next_cursor: string | null;
  page_size: number;
}

/* ------------------------------------------------------------------ members and teams */

export type MemberStatus = "invited" | "active" | "suspended" | "disabled";
export type AvatarTone = "default" | "blue" | "purple" | "amber" | "dark";
export type TeamSource = "manual" | "directory";

export interface Member {
  id: string;
  org_id: string;
  email: string;
  display_name: string;
  status: MemberStatus;
  job_title: string | null;
  timezone: string;
  avatar_tone: AvatarTone;
  primary_team_id: string | null;
  last_seen_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface MemberSummary {
  member: Member;
  team_names: string[];
  role_keys: string[];
  identity_count: number;
  /** False is a real state: a member with no bound identity cannot have proved MFA. */
  mfa_verified: boolean;
}

export interface MemberInvite {
  email: string;
  display_name: string;
  job_title?: string | null;
  timezone?: string;
  avatar_tone?: AvatarTone;
  primary_team_id?: string | null;
  team_ids?: string[];
  role_keys?: string[];
}

export interface MemberUpdate {
  display_name?: string;
  job_title?: string | null;
  timezone?: string;
  avatar_tone?: AvatarTone;
  primary_team_id?: string | null;
  status?: MemberStatus;
}

export interface Identity {
  id: string;
  member_id: string;
  issuer: string;
  subject: string;
  email_verified: boolean;
  mfa_verified: boolean;
  directory_groups: string[];
  last_login_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

export interface Team {
  id: string;
  org_id: string;
  slug: string;
  name: string;
  description: string | null;
  parent_team_id: string | null;
  source: TeamSource;
  directory_group_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface TeamSummary {
  team: Team;
  member_count: number;
  lead_names: string[];
}

export interface TeamCreate {
  slug: string;
  name: string;
  description?: string | null;
  parent_team_id?: string | null;
  source?: TeamSource;
  directory_group_id?: string | null;
}

/** The signed-in person's own page, assembled server-side to keep login to one request. */
export interface MemberProfile {
  account_name: string;
  member: Member;
  identities: Identity[];
  teams: Team[];
  role_keys: string[];
  permissions: string[];
}

/* -------------------------------------------------------------------------- access */

export type SubjectKind = "member" | "team" | "agent" | "agent_version" | "workload" | "project";

export type ScopeKind = "account" | "project" | "environment" | "agent" | "mcp_server" | "engagement";

export type RequestState = "pending" | "approved" | "denied" | "withdrawn" | "expired";

export interface Role {
  id: string;
  /** Null for the roles seeded by migration; those are shared and immutable. */
  org_id: string | null;
  key: string;
  name: string;
  description: string;
  builtin: boolean;
  permissions: string[];
  assignable_scopes: ScopeKind[];
  /** True when holding this role should exclude holding the thing it approves. */
  separation_of_duty: boolean;
}

export interface RoleCreate {
  key: string;
  name: string;
  description: string;
  permissions: string[];
  assignable_scopes: ScopeKind[];
  separation_of_duty?: boolean;
}

export interface AccessGrant {
  id: string;
  org_id: string;
  subject_kind: SubjectKind;
  subject_id: string;
  role_key: string;
  scope_kind: ScopeKind;
  scope_id: string | null;
  granted_by: string;
  reason: string | null;
  /** Set when the grant came from an approved request rather than a direct assignment. */
  request_id: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  revoked_by: string | null;
  created_at: string;
}

export interface AccessGrantSummary {
  grant: AccessGrant;
  subject_label: string;
  role_name: string;
  permissions: string[];
  scope_label: string;
}

export interface AccessGrantCreate {
  subject_kind: "member" | "team";
  subject_id: string;
  role_key: string;
  scope_kind: ScopeKind;
  /** Omitted for account scope, required for every other scope. */
  scope_id?: string | null;
  reason?: string | null;
  expires_at?: string | null;
}

export interface AccessRequest {
  id: string;
  org_id: string;
  requester_member_id: string;
  role_key: string;
  scope_kind: ScopeKind;
  scope_id: string | null;
  duration_minutes: number;
  reason: string;
  ticket_ref: string | null;
  risk: RiskTier;
  state: RequestState;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  granted_grant_id: string | null;
  created_at: string;
}

export interface AccessRequestCreate {
  role_key: string;
  scope_kind: ScopeKind;
  scope_id?: string | null;
  duration_minutes: number;
  reason: string;
  ticket_ref?: string | null;
}

export interface AccessRequestDecision {
  approve: boolean;
  note?: string | null;
  /** An approver may shorten a request but never lengthen it. */
  granted_minutes?: number | null;
}

export interface EffectiveAccess {
  member_id: string;
  role_keys: string[];
  permissions: string[];
  /** Permission to the scope keys it holds at, as `"kind:id"` or `"account"`. */
  scoped: Record<string, string[]>;
}

/* --------------------------------------------------------------------- connections */

export type ProviderKind =
  | "openai"
  | "anthropic"
  | "azure_openai"
  | "bedrock"
  | "vertex"
  | "mistral"
  | "cohere"
  | "vllm"
  | "ollama"
  | "mcp_http"
  | "custom";

export type AuthKind = "api_key" | "oauth_client" | "iam_role" | "mtls" | "workload_identity" | "none";

export type ConnectionStatus = "pending" | "healthy" | "degraded" | "rotating" | "disabled";

export interface Connection {
  id: string;
  org_id: string;
  slug: string;
  name: string;
  provider_kind: ProviderKind;
  auth_kind: AuthKind;
  status: ConnectionStatus;
  owner_team_id: string | null;
  /** Set for a developer's own key. Such a connection cannot reach production. */
  personal_member_id: string | null;
  endpoint_url: string | null;
  region: string | null;
  residency_zone: string | null;
  environments: LifecycleState[];
  active_secret_version_id: string | null;
  rotation_due_at: string | null;
  last_used_at: string | null;
  last_health_at: string | null;
  health_detail: string | null;
  created_at: string;
  updated_at: string;
  created_by: string;
}

export interface ConnectionSummary {
  connection: Connection;
  owner_team_name: string | null;
  grant_count: number;
  active_version: number | null;
  rotation_overdue: boolean;
}

export interface ConnectionCreate {
  slug: string;
  name: string;
  provider_kind: ProviderKind;
  auth_kind: AuthKind;
  /**
   * A pointer into the customer's own secret provider — a Vault path, a KMS key id, or an
   * env var name locally. Never the credential itself: nothing in this product stores one.
   */
  credential_ref: string;
  owner_team_id?: string | null;
  endpoint_url?: string | null;
  region?: string | null;
  residency_zone?: string | null;
  environments: LifecycleState[];
  rotation_due_at?: string | null;
  personal?: boolean;
}

export interface ConnectionRotate {
  credential_ref: string;
  /** SHA-256 of the new material, computed by the caller. Proof of change, not the key. */
  fingerprint_hex: string;
  rotation_due_at?: string | null;
  retire_previous?: boolean;
}

export interface SecretVersion {
  id: string;
  version_number: number;
  credential_ref: string;
  /** First 16 hex characters: enough to compare two versions, not enough to be a key. */
  fingerprint_prefix: string;
  created_at: string;
  activated_at: string | null;
  retired_at: string | null;
  created_by: string;
}

export interface ConnectionGrant {
  id: string;
  connection_id: string;
  subject_kind: string;
  subject_id: string;
  environments: LifecycleState[];
  granted_by: string;
  reason: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

export interface ConnectionGrantCreate {
  subject_kind: "agent" | "team" | "project";
  subject_id: string;
  environments: LifecycleState[];
  reason?: string | null;
  expires_at?: string | null;
}

/* -------------------------------------------------------------------- MCP registry */

export type McpTransport = "stdio" | "http" | "sse" | "streamable_http";

export type TrustTier = "internal" | "accredited" | "partner" | "community" | "unverified";

export type ServerState = "draft" | "in_review" | "approved" | "quarantined" | "retired";

export type CapabilityKind = "tool" | "resource" | "prompt";

export type HealthState = "unknown" | "healthy" | "degraded" | "unreachable" | "drift";

export interface McpServer {
  id: string;
  org_id: string;
  slug: string;
  name: string;
  description: string | null;
  transport: McpTransport;
  endpoint_url: string | null;
  command: string | null;
  owner_team_id: string | null;
  connection_id: string | null;
  trust_tier: TrustTier;
  state: ServerState;
  risk_tier: RiskTier;
  health: HealthState;
  environments: LifecycleState[];
  /** What live grants resolve against. Null means every call is denied. */
  approved_snapshot_id: string | null;
  /** What discovery last saw. Differing from the approved one is drift. */
  observed_snapshot_id: string | null;
  requires_approval_for_writes: boolean;
  quarantined_at: string | null;
  quarantine_reason: string | null;
  last_discovered_at: string | null;
  created_at: string;
  updated_at: string;
  created_by: string;
}

export interface McpServerSummary {
  server: McpServer;
  owner_team_name: string | null;
  tool_count: number;
  grant_count: number;
  dangerous_tool_count: number;
  drifted: boolean;
  calls_7d: number;
  denials_7d: number;
}

export interface McpSnapshot {
  id: string;
  server_id: string;
  capability_digest_hex: string;
  protocol_version: string | null;
  source: string;
  tool_count: number;
  resource_count: number;
  prompt_count: number;
  discovered_at: string;
  discovered_by: string;
  approved_at: string | null;
  approved_by: string | null;
  superseded_at: string | null;
}

export interface McpCapability {
  id: string;
  snapshot_id: string;
  server_id: string;
  kind: CapabilityKind;
  name: string;
  title: string | null;
  input_schema_digest_hex: string | null;
  /** What the server claimed about itself. Null means it did not say. */
  declared_read_only: boolean | null;
  declared_destructive: boolean | null;
  declared_idempotent: boolean | null;
  declared_open_world: boolean | null;
  /** What a reviewer concluded. Kept separate from the claim on purpose. */
  verified_risk: RiskTier;
  verified_write: boolean;
  verified_irreversible: boolean;
  review_note: string | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  /** The server's own annotation contradicts what review found. */
  annotation_mismatch: boolean;
}

export interface McpServerDetail {
  summary: McpServerSummary;
  approved_snapshot: McpSnapshot | null;
  observed_snapshot: McpSnapshot | null;
  capabilities: McpCapability[];
  added_capability_names: string[];
  removed_capability_names: string[];
  changed_capability_names: string[];
}

export interface McpGrant {
  id: string;
  server_id: string;
  /** Null grants the whole server; a name narrows it to one capability. */
  capability_name: string | null;
  subject_kind: string;
  subject_id: string;
  environments: LifecycleState[];
  permission: string;
  requires_approval: boolean;
  /** Set when the grant is bound to one snapshot, so new tools are not auto-granted. */
  pinned_snapshot_id: string | null;
  granted_by: string;
  reason: string | null;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
}

export interface McpGrantCreate {
  capability_name?: string | null;
  subject_kind: "member" | "team" | "agent" | "agent_version" | "workload";
  subject_id: string;
  environments: LifecycleState[];
  permission?: "invoke" | "read";
  requires_approval?: boolean;
  pin_approved_snapshot?: boolean;
  reason?: string | null;
  expires_at?: string | null;
}

export interface McpServerRegister {
  slug: string;
  name: string;
  description?: string | null;
  transport: McpTransport;
  endpoint_url?: string | null;
  command?: string | null;
  owner_team_id?: string | null;
  connection_id?: string | null;
  trust_tier?: TrustTier;
  environments: LifecycleState[];
  requires_approval_for_writes?: boolean;
}

export interface CapabilityReview {
  verified_risk: RiskTier;
  verified_write: boolean;
  verified_irreversible?: boolean;
  review_note?: string | null;
}

export interface McpUsageRollup {
  usage_date: string;
  server_id: string;
  capability_name: string;
  call_count: number;
  denied_count: number;
  approval_count: number;
  error_count: number;
  p95_latency_ms: number | null;
  cost_micros: number;
}

/* --------------------------------------------------------------------- audit trail */

export type AuditActorKind = "member" | "workload" | "agent" | "service" | "system";

export type AuditOutcome = "allowed" | "denied" | "created" | "updated" | "revoked" | "failed" | "expired";

export type AuditSeverity = "info" | "notice" | "warning" | "critical";

export type AuditCategory =
  | "identity"
  | "access"
  | "credential"
  | "mcp"
  | "routing"
  | "data"
  | "admin";

export interface AuditEvent {
  id: string;
  occurred_at: string;
  event_type: string;
  category: string;
  severity: AuditSeverity;
  outcome: AuditOutcome;
  actor_kind: AuditActorKind;
  actor_id: string | null;
  actor_label: string;
  target_kind: string | null;
  target_id: string | null;
  target_label: string | null;
  reason_code: string | null;
  policy_digest_hex: string | null;
  request_id: string | null;
  trace_id: string | null;
  source_ip: string | null;
  /** Classifications, digests and decisions only. Never a prompt or a tool argument. */
  detail: Record<string, string | number | boolean | null>;
}

export interface AuditCategoryCount {
  category: string;
  severity: AuditSeverity;
  event_count: number;
}

export interface AuditDigest {
  since: string;
  until: string;
  counts: AuditCategoryCount[];
  denied_count: number;
  critical_count: number;
}
