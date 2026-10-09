# F1 — Ledger and runtime-identity schema

> Paste this whole file as the only prompt of a fresh session.
> This is a schema-first slice. Do not add product screens or collectors.

## Objective

Create the smallest additive Postgres schema that supports the identity chain and the
content-free `aap.action.v1` ledger. Start from the **real control-plane Alembic head**
`0022_auth_sessions_and_providers`. Reuse existing entities; do not implement the logical
revision numbers in `design/10-migration.md`.

## Read first

- `agent-assurance/AGENTS.md` and `PROJECT_STATE.md`
- `design/03-data-model.md` amendments
- `design/14-ai-identity-and-authorization.md` §1–§4
- `design/15-capability-governance.md` §3, §4 and §9
- `design/17-research-conclusions.md` §7
- Existing migrations `0001`, `0003`, `0014`, `0017`, `0018`, `0022`
- Existing models for registry, members, access, workload identity, evidence and auth

Before writing anything, run `alembic heads` and inspect whether `0022` is applied. If the
head differs, stop and report it; never guess a revision or edit an applied migration.

## Fixed naming and reuse decisions

- Keep `organizations` and `org_id` throughout the MVP. Do not create `accounts`.
- Reuse `agents`, `agent_versions`, `agent_ownership`, `members`,
  `workload_credentials`, `mcp_*`, `evidence_events` and `security_audit_events`.
- Browser sessions remain `auth_sessions`.
- New agent context windows are `agent_sessions`.
- New ledger rows are `agent_actions`, not `actions` or `ai_events`.
- `agent_versions.descriptor_digest` is the existing composition identity. Extend it only
  when a required field does not already exist; do not create another version table.
- `evidence_events` remains the evidence chain. `agent_actions` is a separate high-volume,
  content-free security ledger.

## Revisions

Write by hand and review line by line:

### `0023_agent_runtime_identity`

Add:

1. `agent_instances`
   - `id`, `org_id`, `agent_id`, `agent_version_id`
   - required `human_member_id` and `root_human_basis`
   - environment, deployment location, host fingerprint, harness kind/version
   - `enforcement_grade_available`
   - lifecycle, registration and heartbeat timestamps
   - optional parent instance and bounded delegation depth
2. `agent_sessions`
   - instance FK, started/ended timestamps
   - taint: `clean | tainted | tainted_with_secrets`
   - bounded context-source classifications only; no context content
3. `agent_tasks`
   - session FK, origin, intent digest, started/ended timestamps
4. `delegations`
   - parent/child instance, granted capability selectors, depth, expiry, revoked timestamp
   - child authority can only be a subset of parent authority

All four are `org_id` scoped with RLS. Add indexes for agent, human root, liveness, session
timeline and active delegation lookup. Use checks/text enums that can be widened safely.

### `0024_agent_actions_ledger`

Add monthly range-partitioned `agent_actions` with:

- identity: org, event, collector, human, agent, version, instance, session, task
- action: capability kind/id, operation, resource and destination classifications
- decision: outcome, enforcement grade, reason codes, policy/version/approval references
- risk: categorical signals and session taint
- credential: lease reference only
- privacy: argument digest plus bounded enumerated facets
- provenance: source harness, source event ID, observed/received timestamps
- integrity: previous event hash and event hash
- downstream mutation reference when known

`enforcement_grade` is mandatory and checked. `unknown` is allowed for ingestion but is
treated as E in every query.

Constraints and indexes:

- `agent_action_receipts` as the small unpartitioned idempotency registry with unique
  `(org_id, event_id)` and the action partition/id; ingestion claims the receipt and writes
  the action in one transaction. A partition-local unique key alone is insufficient because
  Postgres requires the partition key and would allow the same event with a changed time.
- keyset list index `(org_id, occurred_at desc, id desc)`
- investigation indexes by human, agent, instance, session, capability and collector chain
- append-only trigger: no update or delete of a ledger row
- partition-maintenance function and current/next-month partitions
- RLS on parent and partitions

Store no prompt, completion, file body, full path, raw command or raw tool argument.
Reject unbounded free-form JSON. Facets are allow-listed and length bounded.

## ORM and contract

- Add thin models under `app/db/models/`; no relationships or behavior.
- Export every model, including the existing `auth` models from `0022`.
- Add a typed `aap.action.v1` schema in the boundary layer, but no ingest endpoint here.
- Add migration/model drift checks.
- Amend `design/10-migration.md` so its old `0022`–`0035` numbers are explicitly logical
  history and the executable ledger sequence begins at real head `0022`.

## Invariants

| Name | Assertion |
|---|---|
| `inv_single_alembic_head` | Fresh upgrade ends at one head |
| `inv_runtime_identity_has_human` | Instance without a human root fails |
| `inv_auth_agent_sessions_distinct` | `auth_sessions` and `agent_sessions` both exist and serve different principals |
| `inv_agent_actions_append_only` | Update and delete fail |
| `inv_action_grade_required` | Missing grade fails |
| `inv_action_event_idempotent` | Duplicate event identity cannot create two rows |
| `inv_action_content_free` | Schema has no prompt/completion/raw argument/file body field |
| `inv_new_tables_rls` | Cross-org reads and writes fail for every new tenant table |
| `inv_partition_available` | Current and next month accept rows |

## Verification

1. Fresh PostgreSQL: upgrade from base to head.
2. Existing PostgreSQL at `0022`: upgrade to head with existing IDs unchanged.
3. Downgrade latest one revision and re-upgrade.
4. Run SQL invariant tests and real-Postgres repository tests.
5. Inspect every text/JSON field for a documented bound.
6. Confirm no duplicate agent/member/version/MCP/tenant table was created.

## Gate

- [ ] `alembic heads` reports one head at `0024_agent_actions_ledger`.
- [ ] `0023` and `0024` are **written**; mark applied only if actually run on real Postgres.
- [ ] Runtime identity and ledger privacy/RLS/append-only tests pass.
- [ ] `PROJECT_STATE.md` migrations, module status, session log and current position updated.

## Do not

- Do not rename `organizations` or `org_id`.
- Do not create `capability_grants`, credential broker tables or Cedar tables; V1 owns them.
- Do not add ClickHouse, Kafka, Redis or a rollup table.
- Do not weaken the existing append-only triggers or evidence field limits.
- Do not create an ingest endpoint, collector or UI in this slice.
