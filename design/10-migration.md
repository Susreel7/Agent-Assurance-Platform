# 10 · Migration from the current implementation

> **Amended 2026-09-22 after prompt regression.** The real control-plane Alembic head is
> `0022_auth_sessions_and_providers`, not `0021`. The numbered `0022`–`0035` table retained
> later in this document is the **historical logical migration plan and must not be executed
> with those revision IDs**.
>
> The executable ledger-first sequence is:
>
> | Real revision | Owner prompt | Status | Change |
> |---|---|---|---|
> | `0022_auth_sessions_and_providers` | F0 | applied | Existing revision: `auth_providers`, `auth_sessions`; finish API/web contract |
> | `0023_agent_runtime_identity` | F1 | written | `agent_instances`, `agent_sessions`, `agent_tasks`, `delegations` |
> | `0024_agent_actions_ledger` | F1 | written | Partitioned, append-only, content-free `agent_actions` |
> | `0025_org_units_visibility` | M2 | not written | Org-unit closure and team backfill |
> | `0026_access_grants_visibility_widen` | M2 | not written | Existing grants widened with mandatory before/after equivalence |
>
> **`written` is not `applied`.** A revision is `applied` only once it has run against a real
> PostgreSQL; until then the DDL is unexecuted text, however carefully reviewed.
> `PROJECT_STATE.md` carries the authoritative status and this table follows it.
>
> Later revisions are assigned from the real head at execution time. Never edit an applied
> migration and never reserve IDs in a prompt beyond the next owned slice.
>
> **The two numbering schemes collide, and the collision is the trap.** Logical `0023` in the
> table below is auth providers and sessions; real `0023` is runtime identity. Logical `0024`
> is org units; real `0024` is the action ledger. Anywhere below, a bare four-digit number
> prefixed `L-` is a *logical* step in the historical plan and names no Alembic revision.

The existing code is a migration source, not a constraint. This document maps what exists
today onto the target model, table by table, and states the order of operations so no step
requires downtime or a destructive drop before its replacement is proven.

## What exists today (migrations 0001–0022)

| Area | Tables | Verdict |
|---|---|---|
| Tenancy | `organizations` | **Keep as the MVP tenant root.** A future `accounts` view/rename is not on the ledger critical path |
| People | `members`, `member_identities` | **Keep and extend** (employee_ref, manager, primary unit, status values) |
| Groups | `teams`, `team_members` | **Fold into `org_units`** (`kind='team'`) + `member_org_units` |
| Access | `roles`, `access_grants`, `access_requests` | **Keep**, widen subject and scope enums, add `subtree`, `environments` |
| Keys | `projects`, `workload_credentials`, `workload_credential_generations` | **Rename to `service_identities`**, keep generations, `member_id` → `acts_for_member_id` |
| MCP | `mcp_servers`, `mcp_snapshots`, `mcp_capabilities`, `mcp_grants`, `mcp_capability_usage_daily` | **Keep — closest thing to the target.** Add trust tier, arg rules, pinned snapshot, transports |
| Models | `model_catalog_entries`, `model_catalog_aliases`, `model_deployments`, `model_routes`, `model_route_targets` | **Restructure** into `model_providers` / `model_endpoints` / `model_aliases` / `alias_targets` with residency columns |
| Router runtime | `router_config_snapshots`, `router_signing_keys`, `gateway_request_logs` | **Keep snapshots and keys** (they become `policy_bundles`); `gateway_request_logs` is superseded by `ai_events` |
| Secrets | `provider_connections`, `connection_secret_versions`, `connection_grants` | **Keep**, rename to `connections` / `secret_versions`, add `purpose` |
| Policy | `policies`, `policy_versions`, `policy_decisions` | **Keep the shape**, add `kind`, bindings, simulate fields |
| Activity | `agent_runs`, `run_steps`, `tool_usage_daily`, `graph_nodes`, `graph_edges`; separate Observe/ClickHouse service | **Keep.** Add content-free Postgres `agent_actions`; link to Observe by IDs rather than replacing either store in MVP |
| Evidence | `evidence_batches`, `evidence_events`, `evidence_checkpoints` | **Keep** — hash-chained evidence is the audit story |
| Audit | `security_audit_events` | **Keep**, add the hash chain if not present |
| Assurance / accreditation | `probe_suites`, `probe_runs`, `findings`, `slo_*`, `posture_scores`, `accreditations`, `accreditation_*`, `attestation_runs` | **Decision D-G** — this is a different product (agent accreditation) from the control plane. Recommend parking it behind a feature flag rather than carrying it through every migration |
| Company / compliance | `customers`, `customer_contacts`, `frameworks`, `framework_controls`, `control_mappings`, `obligation_templates`, `customer_frameworks`, `engagements`, `engagement_*` | **Decision D-G**, same reasoning |
| Registry (legacy) | `agents`, `agent_versions`, `agent_ownership`, `bom_components`, `releases`, `release_changes`, `jobs` | `agents` **keeps** (it is the AI-asset inventory); the release/BOM chain belongs to the parked product |

Roughly 60 tables exist; about 25 are on the control-plane path. Carrying the other 35 through
every future migration is a real tax on velocity, which is why D-G needs an answer before
phase 1 starts.

## Strategy: expand → backfill → dual-read → contract

No step drops a column or a table until its replacement has served production reads for a full
phase. Each migration below is one Alembic revision, reversible, with its own backfill and its
own verification query.

**These are logical steps, not Alembic revisions.** The `L-` prefix is deliberate: the plan
below was written when the head was believed to be `0021`, and four of its numbers now name a
different change from the real revision with the same digits. Nothing here may be created with
these IDs.

| Logical rev | Change | Backfill | Verification |
|---|---|---|---|
| L-0022 | `accounts` table; `organizations` becomes a view over it | copy every row, id preserved | row counts equal; `SELECT * FROM organizations` still works |
| L-0023 | `auth_providers`, `provider_claim_maps`, `sessions` | insert one provider row per deployment from the current env vars | `/v1/auth/config` returns a provider for the pilot domain |
| L-0024 | `org_units`, `org_unit_closure`, `org_unit_managers`, `member_org_units` | each `team` → `org_unit(kind='team')`; each `team_member` → `member_org_units`; one root company unit; closure built | every member has exactly one primary unit; closure self-rows present |
| L-0025 | `members` extensions; status enum widened | `employee_ref` null, `primary_org_unit_id` from L-0024, manager from directory if available | no member without a status |
| L-0026 | `directory_groups`, `group_org_unit_rules`, `member_invitations` rework | existing invitations migrated | open-invite unique index holds |
| L-0027 | `access_grants` widened (subject kinds, scope kinds, `subtree`, `environments`) | team grants → org_unit grants with `subtree=true` | effective-permission snapshot before/after is identical for every member |
| L-0028 | `service_identities` (from `workload_credentials`), `agents` extended | rename + `member_id → acts_for_member_id`; keep generations | every live key still authenticates; token hashes untouched |
| L-0029 | `model_providers`, `model_endpoints`, `model_aliases`, `alias_targets`, `model_candidates`, `model_prices` | `model_deployments` → endpoints with `residency_class='global_unpinned'` until attested; `model_routes` → alias targets | every existing route resolves to the same provider; nothing regulated can route until attested |
| L-0030 | MCP additions: `trust_tier`, `arg_rules`, `pinned_snapshot_id`, transport enum | pin every live grant to the currently approved snapshot | tool lists unchanged for existing users |
| L-0031 | `policies` extended, `policy_bindings`, `policy_bundles` (from `router_config_snapshots`) | current snapshot becomes bundle v1 | data plane starts on v1 and enforces identically |
| L-0032 | `budgets`, `approvals`, `audit_events` hash chain | none | chain verifies from genesis |
| L-0033 | ClickHouse schema + dual-write from the gateway | none (forward only) | event counts match gateway request counts within 0.1% |
| L-0034 | Cut dashboards over to rollups | none | side-by-side numbers match the Postgres tables for 7 days |
| L-0035 | **Contract**: drop `teams`, `team_members`, `gateway_request_logs`, the `organizations` view, legacy routing tables | — | only after L-0034 has held for a phase |

The table above is retained as architectural history. Its concepts may be reused by later
optional modules, but its revision IDs are invalid and its ClickHouse-first ordering is
superseded by D-16 and `design/prompts/README.md`.

Two of its steps have since been answered by real revisions doing different work. Logical
L-0023's auth providers and sessions shipped as real `0022_auth_sessions_and_providers`, with
`auth_sessions` rather than `sessions` and no separate `provider_claim_maps` — the claim map is
a `jsonb` column on the provider. L-0033's ClickHouse event store is superseded for the MVP by
the Postgres `agent_actions` ledger in real `0024`; `design/17` §7 defers the analytical split
until the row count justifies operating a second store.

### The one risky migration

**L-0027 (grants).** A mistake here either locks everyone out or silently widens access.
Protocol:

1. Before: snapshot the effective permission set for every member into a temporary table.
2. Migrate.
3. After: recompute and diff. **Any** difference aborts the deployment, including a widening.
4. Only then drop the snapshot table.

Nothing else in this list can escalate privilege, so nothing else needs this treatment.

## Identity data migration, concretely

Today the pilot account has one organisation, a handful of members, a dev-bypass identity, and
grants bootstrapped by "first login becomes owner". Target state:

1. Keep the organization tenant root for the MVP and set deployment mode through the
   current configuration path. Do not create a parallel account row.
2. Create one `auth_providers` row for Entra with the real issuer, client id, claim map and
   `email_domains = {northwind.example}`, `onboarding_mode = invite` initially.
3. Convert the existing `account_owner` grant to an explicit, audited grant with
   `source='bootstrap'` and a recorded reason, so the provenance of the most powerful grant in
   the system is not "an implicit code path".
4. Delete the `dev.<email>` bearer bypass from the API. Development uses a `development`
   provider kind that is refused unless `deployment_mode='development'` — same code path as
   production, no special-cased header parsing in `deps.py`.
5. Import the pilot DLs: `directory_groups` from the DL export, `group_org_unit_rules` mapping
   each DL to an org unit, `dl_admin` granted by rule. Re-run the import; it must be a no-op.

## Frontend migration

| Today | Target | Phase |
|---|---|---|
| Build-time `VITE_OIDC_*` | `GET /v1/auth/config` | F0 |
| `sessionStorage` session, saved before activation | server session cookie, created after onboarding | F0 |
| N parallel queries per screen for identity/permissions | one `session/bootstrap` | F0 |
| Client-side route list | server navigation manifest | F0/F2 |
| Generic error boundary | reason-code `DataBoundary` with `next` actions | F0/F2 |
| `SuiteProjectProvider` gate that blocks screens without a project | project as a filter | F0/F2 |
| Existing OTLP execution UI | Keep; add separate `/observe/actions` over `agent_actions` | M3/M5 |

## Rollback posture

Every revision is reversible except the ClickHouse forward-fill, which needs no rollback because
it is additive. The data plane runs bundle version N and refuses N−1, so a bad policy bundle is
rolled back by publishing N+1 with the previous contents — never by editing history. Feature
flags are per account, so a failed cutover affects one tenant.

## What to delete, and when

Deletion is a phase-gate activity, never opportunistic:

- After P2: `teams`, `team_members` (replaced by org units), the dev bearer bypass, `OrgGate`
  remnants and any `X-Org-Id` handling.
- After P4: legacy `model_routes` / `model_route_targets` / `model_deployments`.
- After P7: `gateway_request_logs`, `agent_runs`, `run_steps`, `tool_usage_daily`,
  `graph_nodes`/`graph_edges` in Postgres.
- Behind a flag from P1, deleted only on your decision: the assurance/accreditation and
  company/compliance domains (D-G).
