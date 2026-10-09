# M1 — Agent identity chain

> Paste this whole file as the only prompt of a fresh session.
> Prerequisite: F1 revisions `0023` and `0024` written and preferably applied. F0
> bootstrap is preferred. F2 nav is preferred for any screen work.

## Objective

Make "who is responsible for an AI action?" a query, not a paragraph. Persist and expose
the chain `Human → Agent → Agent version → Agent instance → Session → Task`.

## Read first

- `design/14-ai-identity-and-authorization.md` §1–§4, §8 (lifecycle)
- `design/02-identity-and-onboarding.md` (amended)
- `design/03-data-model.md`
- Existing `app/domains/registry/`, `workload_identity/`, `members/`
- `design/prompts/README.md`

## Scope

**In:**

1. Services for `agent_instances`, `agent_sessions`, `agent_tasks`, `delegations`.
2. Registration endpoint: an instance **must** register (or be upserted from first
   heartbeat) before it can emit actions in M3. Unregistered ingest in M3 still lands, but
   marked `lifecycle=discovered` and `enforcement_grade=E`.
3. Heartbeat + liveness: a missing collector heartbeat is itself an event (alert later in
   M4; here just `last_heartbeat_at`).
4. Extend `/agents` list/detail to show harness, lifecycle, last seen, instances, grade
   available. Reuse `AgentsListScreen` / `AgentDetailScreen` — do not duplicate.
5. `root_human_basis` required on every instance. CI/scheduled agents use
   `owner_of_record` or `approved_by`, never a fake "system" user.
6. Delegation records with depth cap (account default 3); child capabilities ⊆ parent.

**Out:** ingest of tool events (M3), hooks (M4), Cedar, broker, org-unit rebuild. If org
units still do not exist, scope visibility to the whole `org_id` and say so in
`PROJECT_STATE.md` rather than inventing a tree here. M2 owns the tree.

## API

```
POST   /v1/agents/{id}/instances          register
POST   /v1/agent-instances/{id}/heartbeat
GET    /v1/agent-instances/{id}
GET    /v1/agents/{id}/instances
POST   /v1/agent-instances/{id}/sessions
GET    /v1/agent-sessions/{id}
POST   /v1/agent-sessions/{id}/tasks
POST   /v1/agent-instances/{id}/delegations
```

The explicit `agent-*` namespace prevents collision with browser `auth_sessions`. Reuse
`/v1/agents` for the parent. Do not create a second agent registry.

Use the four-file domain pattern. The service owns registration, human-root resolution,
heartbeat and delegation subset checks; routers remain thin. Do not import the members or
registry repository directly.

## UI

- Agent detail: versions, instances (host, harness, grade, last heartbeat), lifecycle.
- Empty state: "No running copies. Install a collector (M3) or register a CI instance."
- Wrap with `DataBoundary`. Grade chip on every instance row.

## Invariants

| Name | Assertion |
|---|---|
| `inv_instance_has_human` | Insert without `human_member_id` fails |
| `inv_no_service_root` | Service identity cannot be `human_member_id` |
| `inv_delegation_depth_cap` | Depth > account max is rejected |
| `inv_delegation_subset` | Child grant is a subset of parent |
| `inv_heartbeat_updates_last_seen` | Heartbeat updates instance and agent `last_seen_at` |
| `inv_agent_auth_sessions_distinct` | Agent-session endpoints never read or revoke `auth_sessions` |
| `inv_existing_version_reused` | Registration references existing append-only `agent_versions` |

## Gate

- [ ] Agent detail shows at least one instance fixture created through the service, not a
      seed dumped into SQL from the session.
- [ ] Unauthenticated register is 401; cross-org id is 404 not 403 leakage.
- [ ] Tests against real Postgres.
- [ ] `PROJECT_STATE.md` updated.

## Do not

- Do not emit fake actions.
- Do not store prompts on versions. Digests only (`composition_digest`).
- Do not add another `agents`, `agent_versions`, member or service-identity table.
