/**
 * Query and mutation hooks for the admin surface: people, access, credentials, tools, audit.
 *
 * Two conventions here differ from `queries.ts` and are deliberate.
 *
 * Cache keys are coarse on purpose. Granting a role changes the grant list, the target
 * member's row, that member's effective access and — if the grant came from a request —
 * the request list. Invalidating the whole `["access"]` subtree costs three cheap refetches
 * and is correct; enumerating the four keys by hand is cheaper and was wrong twice.
 *
 * The audit list is paginated by cursor, not offset. `security_audit_events` is partitioned
 * and append-only, so `OFFSET 40000` reads forty thousand rows to discard them, and by the
 * time page 800 renders the rows have shifted underneath it. See `app/api/pagination.py`.
 */

import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./client";
import type {
  AccessGrantCreate,
  AccessGrant,
  AccessGrantSummary,
  AccessRequest,
  AccessRequestCreate,
  AccessRequestDecision,
  AuditDigest,
  AuditEvent,
  CapabilityReview,
  Connection,
  ConnectionCreate,
  ConnectionGrant,
  ConnectionGrantCreate,
  ConnectionRotate,
  ConnectionSummary,
  EffectiveAccess,
  Identity,
  KeysetPage,
  McpCapability,
  McpGrant,
  McpGrantCreate,
  McpServer,
  McpServerDetail,
  McpServerRegister,
  McpServerSummary,
  McpSnapshot,
  McpUsageRollup,
  Member,
  MemberInvite,
  MemberProfile,
  MemberSummary,
  MemberUpdate,
  OffsetPage,
  Role,
  RoleCreate,
  SecretVersion,
  Team,
  TeamCreate,
  TeamSummary,
} from "./platformTypes";

export const pqk = {
  me: ["platform", "me"] as const,
  members: (params: Record<string, string>) => ["platform", "members", params] as const,
  identities: (memberId: string) => ["platform", "members", memberId, "identities"] as const,
  teams: ["platform", "teams"] as const,
  roles: ["platform", "access", "roles"] as const,
  grants: (params: Record<string, string>) => ["platform", "access", "grants", params] as const,
  effective: (memberId: string) => ["platform", "access", "effective", memberId] as const,
  requests: (params: Record<string, string>) => ["platform", "access", "requests", params] as const,
  myRequests: ["platform", "access", "requests", "mine"] as const,
  connections: (params: Record<string, string>) => ["platform", "connections", params] as const,
  connection: (id: string) => ["platform", "connections", id] as const,
  connectionVersions: (id: string) => ["platform", "connections", id, "versions"] as const,
  connectionGrants: (id: string) => ["platform", "connections", id, "grants"] as const,
  mcpServers: (params: Record<string, string>) => ["platform", "mcp", "servers", params] as const,
  mcpServer: (id: string) => ["platform", "mcp", "servers", id] as const,
  mcpGrants: (id: string) => ["platform", "mcp", "servers", id, "grants"] as const,
  mcpUsage: (id: string, days: number) => ["platform", "mcp", "servers", id, "usage", days] as const,
  auditEvents: (params: Record<string, string>) => ["platform", "audit", "events", params] as const,
  auditDigest: (days: number) => ["platform", "audit", "digest", days] as const,
  auditForTarget: (targetId: string) => ["platform", "audit", "target", targetId] as const,
};

/** Drop `undefined` and empty strings so a cleared filter does not become `?state=`. */
function clean(params: Record<string, string | number | boolean | undefined>): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === "") continue;
    out[key] = String(value);
  }
  return out;
}

/* ------------------------------------------------------------------------- identity */

/**
 * The signed-in person, their identities, teams and permissions.
 *
 * Every guarded control in the console reads this, so it is fetched once and held. The
 * staleness that matters — a role revoked mid-session — is caught by the API rejecting the
 * next write, not by polling here.
 */
export function useMyProfile() {
  return useQuery({
    queryKey: pqk.me,
    queryFn: () => api.get<MemberProfile>("/v1/members/me"),
    staleTime: 5 * 60_000,
  });
}

/*
 * There is no `useMyAccess` and no `useStartSession` here any more.
 *
 * Permissions come from the bootstrap (`usePermissions`), and the sign-in stamp is
 * written by the server when it issues the session. Both were requests the shell fired
 * on mount, which is how "exactly one identity request" quietly became three.
 */

export function useMembers(params: {
  q?: string;
  member_status?: string;
  team_id?: string;
  limit?: number;
  offset?: number;
}) {
  const search = clean({ limit: params.limit ?? 50, offset: params.offset ?? 0, ...params });
  return useQuery({
    queryKey: pqk.members(search),
    queryFn: () => api.get<OffsetPage<MemberSummary>>("/v1/members", search),
  });
}

export function useInviteMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: MemberInvite) => api.post<MemberSummary>("/v1/members", payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["platform", "members"] }),
  });
}

export function useUpdateMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ memberId, payload }: { memberId: string; payload: MemberUpdate }) =>
      api.patch<Member>(`/v1/members/${memberId}`, payload),
    // The invalidation is broad on purpose. Suspending a member changes their row, their
    // effective access and the shell's own `me` when they suspended themselves.
    onSuccess: (_data, variables) => {
      void qc.invalidateQueries({ queryKey: ["platform", "members"] });
      // A member editing their own row is the common case, and the shell reads `me`.
      void qc.invalidateQueries({ queryKey: pqk.me });
      void qc.invalidateQueries({ queryKey: pqk.effective(variables.memberId) });
    },
  });
}

export function useMemberIdentities(memberId: string) {
  return useQuery({
    queryKey: pqk.identities(memberId),
    queryFn: () => api.get<Identity[]>(`/v1/members/${memberId}/identities`),
    enabled: Boolean(memberId),
  });
}

export function useRevokeIdentity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (identityId: string) => api.del<void>(`/v1/members/identities/${identityId}`),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["platform", "members"] });
      void qc.invalidateQueries({ queryKey: pqk.me });
    },
  });
}

export function useTeams() {
  return useQuery({
    queryKey: pqk.teams,
    queryFn: () => api.get<OffsetPage<TeamSummary>>("/v1/members/teams/all", { limit: "200" }),
  });
}

export function useCreateTeam() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: TeamCreate) => api.post<Team>("/v1/members/teams", payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: pqk.teams }),
  });
}

export function useAddTeamMembers(teamId: string) {
  const qc = useQueryClient();
  return useMutation({
    // Up to 500 ids in one call, applied as a single upsert: onboarding a department is
    // one request rather than hundreds of writes that can each fail separately.
    mutationFn: (payload: { member_ids: string[]; is_lead?: boolean }) =>
      api.post<{ changed: number }>(`/v1/members/teams/${teamId}/members`, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: pqk.teams });
      void qc.invalidateQueries({ queryKey: ["platform", "members"] });
    },
  });
}

export function useRemoveTeamMembers(teamId: string) {
  const qc = useQueryClient();
  return useMutation({
    // POST, not DELETE: it carries a body of up to 500 ids, and a DELETE with a body is
    // legal but poorly supported by proxies and client libraries.
    mutationFn: (payload: { member_ids: string[] }) =>
      api.post<{ changed: number }>(`/v1/members/teams/${teamId}/members/remove`, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: pqk.teams });
      void qc.invalidateQueries({ queryKey: ["platform", "members"] });
    },
  });
}

/* --------------------------------------------------------------------------- access */

export function useRoles() {
  return useQuery({
    queryKey: pqk.roles,
    // Built-in roles are seeded by migration and tenant roles change by the month.
    queryFn: () => api.get<Role[]>("/v1/access/roles"),
    staleTime: 10 * 60_000,
  });
}

export function useCreateRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: RoleCreate) => api.post<Role>("/v1/access/roles", payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: pqk.roles }),
  });
}

export function useGrants(params: {
  subject_kind?: string;
  subject_id?: string;
  include_revoked?: boolean;
  limit?: number;
  offset?: number;
}) {
  const search = clean({ limit: params.limit ?? 50, offset: params.offset ?? 0, ...params });
  return useQuery({
    queryKey: pqk.grants(search),
    queryFn: () => api.get<OffsetPage<AccessGrantSummary>>("/v1/access/grants", search),
  });
}

export function useCreateGrant() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: AccessGrantCreate) => api.post<AccessGrant>("/v1/access/grants", payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["platform", "access"] }),
  });
}

export function useRevokeGrant() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (grantId: string) => api.del<AccessGrant>(`/v1/access/grants/${grantId}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["platform", "access"] }),
  });
}

export function useEffectiveAccess(memberId: string) {
  return useQuery({
    queryKey: pqk.effective(memberId),
    queryFn: () => api.get<EffectiveAccess>(`/v1/access/effective/${memberId}`),
    enabled: Boolean(memberId),
  });
}

export function useAccessRequests(params: { state?: string; limit?: number; offset?: number }) {
  const search = clean({ limit: params.limit ?? 50, offset: params.offset ?? 0, ...params });
  return useQuery({
    queryKey: pqk.requests(search),
    queryFn: () => api.get<OffsetPage<AccessRequest>>("/v1/access/requests", search),
  });
}

export function useMyAccessRequests() {
  return useQuery({
    queryKey: pqk.myRequests,
    queryFn: () => api.get<OffsetPage<AccessRequest>>("/v1/access/requests/mine", { limit: "50" }),
  });
}

export function useCreateAccessRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: AccessRequestCreate) =>
      api.post<AccessRequest>("/v1/access/requests", payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["platform", "access"] }),
  });
}

export function useDecideAccessRequest() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ requestId, payload }: { requestId: string; payload: AccessRequestDecision }) =>
      api.post<AccessRequest>(`/v1/access/requests/${requestId}/decision`, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["platform", "access"] }),
  });
}

/* ---------------------------------------------------------------------- connections */

export function useConnections(params: {
  provider_kind?: string;
  include_disabled?: boolean;
  limit?: number;
  offset?: number;
}) {
  const search = clean({ limit: params.limit ?? 50, offset: params.offset ?? 0, ...params });
  return useQuery({
    queryKey: pqk.connections(search),
    queryFn: () => api.get<OffsetPage<ConnectionSummary>>("/v1/connections", search),
  });
}

export function useConnection(connectionId: string) {
  return useQuery({
    queryKey: pqk.connection(connectionId),
    queryFn: () => api.get<Connection>(`/v1/connections/${connectionId}`),
    enabled: Boolean(connectionId),
  });
}

export function useCreateConnection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ConnectionCreate) => api.post<Connection>("/v1/connections", payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["platform", "connections"] }),
  });
}

export function useConnectionVersions(connectionId: string) {
  return useQuery({
    queryKey: pqk.connectionVersions(connectionId),
    queryFn: () => api.get<SecretVersion[]>(`/v1/connections/${connectionId}/versions`),
    enabled: Boolean(connectionId),
  });
}

export function useRotateConnection(connectionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ConnectionRotate) =>
      api.post<SecretVersion>(`/v1/connections/${connectionId}/rotate`, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["platform", "connections"] }),
  });
}

export function useConnectionGrants(connectionId: string) {
  return useQuery({
    queryKey: pqk.connectionGrants(connectionId),
    queryFn: () => api.get<ConnectionGrant[]>(`/v1/connections/${connectionId}/grants`),
    enabled: Boolean(connectionId),
  });
}

export function useGrantConnection(connectionId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ConnectionGrantCreate) =>
      api.post<ConnectionGrant>(`/v1/connections/${connectionId}/grants`, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["platform", "connections"] }),
  });
}

export function useRevokeConnectionGrant() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (grantId: string) => api.del<ConnectionGrant>(`/v1/connections/grants/${grantId}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["platform", "connections"] }),
  });
}

/* --------------------------------------------------------------------- MCP registry */

export function useMcpServers(params: {
  state?: string;
  trust_tier?: string;
  limit?: number;
  offset?: number;
}) {
  const search = clean({ limit: params.limit ?? 50, offset: params.offset ?? 0, ...params });
  return useQuery({
    queryKey: pqk.mcpServers(search),
    queryFn: () => api.get<OffsetPage<McpServerSummary>>("/v1/mcp/servers", search),
  });
}

export function useMcpServer(serverId: string) {
  return useQuery({
    queryKey: pqk.mcpServer(serverId),
    queryFn: () => api.get<McpServerDetail>(`/v1/mcp/servers/${serverId}`),
    enabled: Boolean(serverId),
  });
}

export function useRegisterMcpServer() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: McpServerRegister) => api.post<McpServer>("/v1/mcp/servers", payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["platform", "mcp"] }),
  });
}

/**
 * Promote the observed capability set to the approved one.
 *
 * The snapshot id is required rather than implied. An operator approving "whatever
 * discovery last saw" would approve a set that changed between the page render and the
 * click, which is exactly the substitution the registry exists to prevent.
 */
export function useApproveSnapshot(serverId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (snapshotId: string) =>
      api.post<McpSnapshot>(`/v1/mcp/servers/${serverId}/snapshots/${snapshotId}/approve`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["platform", "mcp"] }),
  });
}

export function useReviewCapability() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ capabilityId, payload }: { capabilityId: string; payload: CapabilityReview }) =>
      api.patch<McpCapability>(`/v1/mcp/capabilities/${capabilityId}`, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["platform", "mcp"] }),
  });
}

export function useMcpGrants(serverId: string) {
  return useQuery({
    queryKey: pqk.mcpGrants(serverId),
    queryFn: () => api.get<McpGrant[]>(`/v1/mcp/servers/${serverId}/grants`),
    enabled: Boolean(serverId),
  });
}

export function useCreateMcpGrant(serverId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: McpGrantCreate) =>
      api.post<McpGrant>(`/v1/mcp/servers/${serverId}/grants`, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["platform", "mcp"] }),
  });
}

export function useRevokeMcpGrant() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (grantId: string) => api.del<void>(`/v1/mcp/grants/${grantId}`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["platform", "mcp"] }),
  });
}

/**
 * Stop a server immediately. One write, and the next tool call against it is denied.
 *
 * Grants are left intact: revoking them one by one is the slow version of the same intent
 * and loses the state needed to restore access afterwards.
 */
export function useQuarantineServer(serverId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: { reason: string }) =>
      api.post<McpServer>(`/v1/mcp/servers/${serverId}/quarantine`, payload),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["platform", "mcp"] }),
  });
}

export function useReleaseServer(serverId: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.del<McpServer>(`/v1/mcp/servers/${serverId}/quarantine`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["platform", "mcp"] }),
  });
}

export function useMcpUsage(serverId: string, days = 14) {
  return useQuery({
    queryKey: pqk.mcpUsage(serverId, days),
    queryFn: () =>
      api.get<McpUsageRollup[]>(`/v1/mcp/servers/${serverId}/usage`, { days: String(days) }),
    enabled: Boolean(serverId),
  });
}

/* ---------------------------------------------------------------------------- audit */

/**
 * The audit stream, newest first, one cursor page at a time.
 *
 * `useInfiniteQuery` rather than a page number because the underlying cursor is opaque and
 * only moves forward: there is no way to construct "page 4" without having walked to it,
 * which is the property that makes the query cheap.
 */
export function useAuditEvents(params: {
  category?: string;
  severity?: string;
  outcome?: string;
  actor_id?: string;
  event_type?: string;
  since?: string;
  until?: string;
  page_size?: number;
}) {
  const filters = clean({ page_size: params.page_size ?? 50, ...params });
  return useInfiniteQuery({
    queryKey: pqk.auditEvents(filters),
    initialPageParam: undefined as string | undefined,
    queryFn: ({ pageParam }) =>
      api.get<KeysetPage<AuditEvent>>("/v1/audit/events", clean({ ...filters, cursor: pageParam })),
    getNextPageParam: (last) => last.next_cursor ?? undefined,
  });
}

/**
 * Headline counts over a bounded window.
 *
 * Computed live rather than cached, which is affordable only because the window prunes to
 * one or two monthly partitions — hence the ceiling on `days` at the API.
 */
export function useAuditDigest(days = 7) {
  return useQuery({
    queryKey: pqk.auditDigest(days),
    queryFn: () => api.get<AuditDigest>("/v1/audit/digest", { days: String(days) }),
  });
}

/** The audit trail for one object, for the "who touched this" panel on a detail page. */
export function useAuditForTarget(targetId: string) {
  return useQuery({
    queryKey: pqk.auditForTarget(targetId),
    queryFn: () =>
      api.get<KeysetPage<AuditEvent>>(`/v1/audit/events/for-target/${targetId}`, {
        page_size: "25",
      }),
    enabled: Boolean(targetId),
  });
}
