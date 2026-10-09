# 03 · Data model

Sketch: `diagrams/04-data-model.excalidraw`

> **Amended 2026-09-22.**
>
> **D-12** adds, all `account_id`-scoped with row-level security and append-only audit:
> `agent_versions` (the unit that gets **approved**, with `composition_digest` and declared
> capabilities), `agent_instances` (one running copy, with `enforcement_grade_available`),
> `sessions` (carrying `taint`), `tasks` (carrying `origin`), and `delegations`
> (parent/child, granted capabilities, depth).
>
> **D-08** renames and generalises: `mcp_servers` → `capability_sources`, `mcp_capabilities`
> → `capabilities` (with a `kind` discriminator), `mcp_grants` → `capability_grants` (adding
> `capability_selector` and `max_taint`).
>
> **D-10** adds `credential_bindings` and `credential_leases`. Every lease joins to the
> action it was issued for, so *"which credential did this action use, and what else did that
> credential do?"* is one query.
>
> **D-09** adds a **mandatory** `enforcement_grade` to every decision row. Backfill as
> `unknown` and treat `unknown` as grade E.
>
> **D-16** — the Postgres/ClickHouse split below is deferred. The MVP is Postgres only, with
> time-partitioned action tables. The rule for choosing between them is still right; it is
> just not a decision the MVP has to make.
>
> Retention and lifecycle for the new tables follow the existing policy: evidence rows are
> append-only, survive agent retirement for the account's retention period, and honour legal
> hold. Full definitions in
> [`14-ai-identity-and-authorization.md`](14-ai-identity-and-authorization.md) §3 and
> [`15-capability-governance.md`](15-capability-governance.md) §4, §6.

Two stores, one rule for choosing: **Postgres holds what an operator edits; ClickHouse holds
what the world did.** Configuration is small, relational, transactional and needs foreign
keys. Activity is append-only, enormous, and must survive the deletion of the configuration
it refers to. They never participate in the same query — the join happens in the API layer,
against ids, after the aggregate has already been reduced.

Conventions everywhere below: `uuid` v7 primary keys (time-ordered, index-friendly),
`timestamptz` in UTC, `account_id` on every tenant table, `created_at` / `updated_at`,
soft delete only where an auditor needs the history (`revoked_at`, `valid_to`), money as
`bigint cost_micros`, enums as `text` + `CHECK` (migrating a Postgres enum is a lock you do
not want at 3am).

---

## A · Identity and tenancy

```sql
CREATE TABLE accounts (
  id               uuid PRIMARY KEY,
  slug             text NOT NULL UNIQUE,
  legal_name       text NOT NULL,
  deployment_mode  text NOT NULL CHECK (deployment_mode IN
                     ('saas','single_tenant','self_hosted','air_gapped','development')),
  residency_class  text NOT NULL DEFAULT 'region_pinned',
  retention_profile jsonb NOT NULL,      -- hot_days, cold_days, payload_hours, legal_hold
  capabilities     jsonb NOT NULL,       -- egress_internet, scim_inbound, …
  pseudonymous_telemetry boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL
);

CREATE TABLE org_units (
  id            uuid PRIMARY KEY,
  account_id    uuid NOT NULL REFERENCES accounts(id),
  parent_id     uuid REFERENCES org_units(id),
  path          text NOT NULL,           -- '/northwind/eng/ide-users'  (materialised)
  kind          text NOT NULL CHECK (kind IN
                  ('company','business_unit','department','team','distribution_list','cost_centre')),
  name          text NOT NULL,
  source        text NOT NULL CHECK (source IN ('manual','scim','directory_pull','bulk')),
  external_ref  text,                    -- directory object id
  cost_centre_ref text,
  archived_at   timestamptz,
  UNIQUE (account_id, path),
  UNIQUE (account_id, external_ref)
);
CREATE INDEX org_units_path_prefix ON org_units (account_id, path text_pattern_ops);

CREATE TABLE org_unit_closure (          -- ancestor → descendant, incl. self at depth 0
  account_id uuid NOT NULL,
  ancestor_id uuid NOT NULL REFERENCES org_units(id) ON DELETE CASCADE,
  descendant_id uuid NOT NULL REFERENCES org_units(id) ON DELETE CASCADE,
  depth int NOT NULL,
  PRIMARY KEY (ancestor_id, descendant_id)
);

CREATE TABLE org_unit_managers (
  org_unit_id uuid NOT NULL REFERENCES org_units(id) ON DELETE CASCADE,
  member_id   uuid NOT NULL REFERENCES members(id),
  subtree     boolean NOT NULL DEFAULT true,
  source      text NOT NULL,             -- manual | group_rule | directory
  PRIMARY KEY (org_unit_id, member_id)
);

CREATE TABLE members (
  id                 uuid PRIMARY KEY,
  account_id         uuid NOT NULL REFERENCES accounts(id),
  email              text NOT NULL,      -- normalised lower-case
  display_name       text NOT NULL,
  employee_ref       text,               -- HR id, from claims or SCIM
  status             text NOT NULL CHECK (status IN ('invited','active','suspended','removed')),
  primary_org_unit_id uuid REFERENCES org_units(id),
  manager_member_id  uuid REFERENCES members(id),
  job_title          text, timezone text, locale text,
  first_seen_at timestamptz, last_seen_at timestamptz,
  UNIQUE (account_id, email)
);

CREATE TABLE member_identities (
  id        uuid PRIMARY KEY,
  account_id uuid NOT NULL,
  member_id uuid NOT NULL REFERENCES members(id) ON DELETE CASCADE,
  provider_id uuid NOT NULL REFERENCES auth_providers(id),
  issuer    text NOT NULL,
  subject   text NOT NULL,
  email_verified boolean NOT NULL DEFAULT false,
  mfa_verified   boolean NOT NULL DEFAULT false,
  directory_groups text[] NOT NULL DEFAULT '{}',
  last_login_at timestamptz,
  revoked_at    timestamptz,
  UNIQUE (issuer, subject)               -- global: one IdP subject is one person
);

CREATE TABLE member_org_units (
  account_id uuid NOT NULL,
  member_id  uuid NOT NULL REFERENCES members(id) ON DELETE CASCADE,
  org_unit_id uuid NOT NULL REFERENCES org_units(id) ON DELETE CASCADE,
  is_primary boolean NOT NULL DEFAULT false,
  source     text NOT NULL,
  valid_from timestamptz NOT NULL, valid_to timestamptz,
  PRIMARY KEY (member_id, org_unit_id, valid_from)
);
CREATE UNIQUE INDEX one_primary_unit ON member_org_units (member_id)
  WHERE is_primary AND valid_to IS NULL;

CREATE TABLE directory_groups (
  id uuid PRIMARY KEY, account_id uuid NOT NULL,
  external_ref text NOT NULL, name text NOT NULL, kind text,   -- security | distribution
  member_count int, synced_at timestamptz,
  UNIQUE (account_id, external_ref)
);

CREATE TABLE group_org_unit_rules (
  id uuid PRIMARY KEY, account_id uuid NOT NULL,
  directory_group_id uuid NOT NULL REFERENCES directory_groups(id) ON DELETE CASCADE,
  org_unit_id uuid NOT NULL REFERENCES org_units(id),
  grant_role_key text REFERENCES roles(key),   -- optional: group membership implies a role
  grant_subtree boolean NOT NULL DEFAULT true,
  priority int NOT NULL DEFAULT 100,
  UNIQUE (directory_group_id, org_unit_id)
);

CREATE TABLE member_invitations (
  id uuid PRIMARY KEY, account_id uuid NOT NULL,
  email text NOT NULL, org_unit_id uuid REFERENCES org_units(id),
  role_key text REFERENCES roles(key),
  invited_by uuid REFERENCES members(id),
  expires_at timestamptz NOT NULL,
  claimed_by_identity_id uuid REFERENCES member_identities(id),
  claimed_at timestamptz, revoked_at timestamptz
);
CREATE UNIQUE INDEX one_open_invite ON member_invitations (account_id, lower(email))
  WHERE claimed_at IS NULL AND revoked_at IS NULL;

CREATE TABLE sessions (                     -- server-side, revocable, listed in the profile
  id uuid PRIMARY KEY, account_id uuid NOT NULL,
  member_id uuid NOT NULL REFERENCES members(id) ON DELETE CASCADE,
  identity_id uuid REFERENCES member_identities(id),
  token_hash bytea NOT NULL UNIQUE,
  ip inet, user_agent text,
  created_at timestamptz NOT NULL, last_used_at timestamptz,
  expires_at timestamptz NOT NULL, revoked_at timestamptz, revoke_reason text
);
```

`auth_providers` and `provider_claim_maps` are specified in
[02-identity-and-onboarding.md](02-identity-and-onboarding.md).

---

## B · Authorization

```sql
CREATE TABLE roles (
  key text PRIMARY KEY,                  -- account_owner, security_admin, dl_admin, …
  account_id uuid REFERENCES accounts(id),   -- NULL = built-in, shared
  label text NOT NULL, description text NOT NULL,
  permissions text[] NOT NULL,
  assignable_scopes text[] NOT NULL,     -- account | org_unit | project | resource
  separation_of_duty boolean NOT NULL DEFAULT false,
  builtin boolean NOT NULL DEFAULT false
);

CREATE TABLE access_grants (
  id uuid PRIMARY KEY, account_id uuid NOT NULL,
  subject_kind text NOT NULL CHECK (subject_kind IN
    ('member','org_unit','directory_group','service_identity','agent')),
  subject_id   uuid NOT NULL,
  role_key     text NOT NULL REFERENCES roles(key),
  scope_kind   text NOT NULL CHECK (scope_kind IN ('account','org_unit','project','resource')),
  scope_id     uuid,                     -- NULL only for account scope
  subtree      boolean NOT NULL DEFAULT true,
  environments text[] NOT NULL DEFAULT '{dev,staging,prod}',
  granted_by uuid REFERENCES members(id), granted_reason text,
  source text NOT NULL DEFAULT 'manual', -- manual | group_rule | bootstrap
  expires_at timestamptz, revoked_at timestamptz,
  UNIQUE (account_id, subject_kind, subject_id, role_key, scope_kind, scope_id)
    WHERE revoked_at IS NULL
);

CREATE TABLE access_requests (           -- the "request access" flow, end to end
  id uuid PRIMARY KEY, account_id uuid NOT NULL,
  requested_by uuid NOT NULL REFERENCES members(id),
  role_key text NOT NULL, scope_kind text NOT NULL, scope_id uuid,
  justification text NOT NULL, state text NOT NULL,   -- pending|approved|denied|expired
  decided_by uuid REFERENCES members(id), decided_at timestamptz, decision_note text,
  expires_at timestamptz NOT NULL
);

CREATE TABLE approvals (                 -- runtime approvals: risky tool call, payload reveal
  id uuid PRIMARY KEY, account_id uuid NOT NULL,
  kind text NOT NULL,                    -- tool_call | model_request | payload_reveal | policy_change
  subject_digest text NOT NULL,          -- what exactly is being approved
  context jsonb NOT NULL,                -- member, agent, server, tool, arg digest, risk
  requested_by_member uuid, requested_by_service uuid,
  state text NOT NULL, approver_member_id uuid,
  decided_at timestamptz, decision_note text,
  resume_token_hash bytea, uses_allowed int NOT NULL DEFAULT 1, uses_consumed int NOT NULL DEFAULT 0,
  expires_at timestamptz NOT NULL
);
```

**Visibility is computed, cached, never stored as a denormalised list of members.** A
materialised view refreshed on grant/org change, keyed by member, holding the set of org-unit
paths they can see, is acceptable; a table of (viewer, visible_member) pairs is not — at 20k
members that is 400M rows and it will be stale.

```sql
CREATE MATERIALIZED VIEW member_visibility AS
SELECT g.subject_id AS viewer_member_id,
       u.path       AS visible_path,
       bool_or(r.permissions @> ARRAY['activity:read_all']) AS all_members
FROM access_grants g
JOIN roles r ON r.key = g.role_key
LEFT JOIN org_units u ON u.id = g.scope_id
WHERE g.revoked_at IS NULL AND g.subject_kind = 'member'
GROUP BY 1, 2;
```

---

## C · Registry: models, endpoints, aliases, prices

```sql
CREATE TABLE model_providers (
  id uuid PRIMARY KEY, account_id uuid NOT NULL,
  kind text NOT NULL CHECK (kind IN
    ('azure_foundry','bedrock','vertex','openai','anthropic','google','local','other')),
  label text NOT NULL, connection_id uuid REFERENCES connections(id),
  discovery_enabled boolean NOT NULL DEFAULT true,
  enabled boolean NOT NULL DEFAULT true, owner_member_id uuid
);

CREATE TABLE model_endpoints (
  id uuid PRIMARY KEY, account_id uuid NOT NULL,
  provider_id uuid NOT NULL REFERENCES model_providers(id) ON DELETE CASCADE,
  model_ref  text NOT NULL,              -- provider's model / deployment name
  base_url   text NOT NULL,
  deployment_ref text,                   -- Azure deployment, Bedrock inference profile id
  deployment_sku text,                   -- GlobalStandard | DataZoneStandard | Standard | …
  region text, zone text,                -- 'eu-central-1' / 'EU'
  residency_class text NOT NULL CHECK (residency_class IN
    ('region_pinned','zone_pinned','global_unpinned')),
  attested_at timestamptz, attested_by uuid, evidence_ref text,
  context_window int, modalities text[], supports_tools boolean,
  max_data_class text,                   -- highest data class allowed to reach it
  health text NOT NULL DEFAULT 'unknown',
  enabled boolean NOT NULL DEFAULT false,
  UNIQUE (provider_id, model_ref, COALESCE(deployment_ref,''))
);

CREATE TABLE model_aliases (
  id uuid PRIMARY KEY, account_id uuid NOT NULL,
  alias text NOT NULL,                   -- aap-fast | aap-balanced | aap-deep | aap-internal-secure
  label text NOT NULL, description text,
  state text NOT NULL CHECK (state IN ('draft','approved','deprecated','retired')),
  UNIQUE (account_id, alias)
);

CREATE TABLE alias_targets (
  alias_id uuid NOT NULL REFERENCES model_aliases(id) ON DELETE CASCADE,
  endpoint_id uuid NOT NULL REFERENCES model_endpoints(id) ON DELETE CASCADE,
  weight int NOT NULL DEFAULT 100,       -- within the same priority
  priority int NOT NULL DEFAULT 1,       -- 1 primary, 2 failover, …
  mode text NOT NULL DEFAULT 'balanced', -- cost | balanced | quality | residency_strict
  PRIMARY KEY (alias_id, endpoint_id)
);

CREATE TABLE model_candidates (          -- what discovery found and nobody has approved yet
  id uuid PRIMARY KEY, account_id uuid NOT NULL, provider_id uuid NOT NULL,
  model_ref text NOT NULL, raw jsonb NOT NULL,
  change text NOT NULL,                  -- new | changed | withdrawn
  first_seen_at timestamptz NOT NULL, last_seen_at timestamptz NOT NULL,
  reviewed_at timestamptz, reviewed_by uuid, decision text
);

CREATE TABLE model_prices (              -- effective-dated; never overwritten
  id uuid PRIMARY KEY, account_id uuid, provider_kind text NOT NULL, model_ref text NOT NULL,
  input_micros_per_1k bigint NOT NULL, output_micros_per_1k bigint NOT NULL,
  cache_read_micros_per_1k bigint, currency text NOT NULL DEFAULT 'USD',
  effective_from timestamptz NOT NULL, effective_to timestamptz, source text
);
```

---

## D · MCP registry

```sql
CREATE TABLE mcp_servers (
  id uuid PRIMARY KEY, account_id uuid NOT NULL,
  slug text NOT NULL, label text NOT NULL,
  transport text NOT NULL CHECK (transport IN ('stdio','sse','http_stream')),
  endpoint_url text, command text, args text[], env_refs jsonb,
  connection_id uuid REFERENCES connections(id),
  owner_org_unit_id uuid REFERENCES org_units(id),
  environments text[] NOT NULL,
  state text NOT NULL CHECK (state IN ('draft','discovering','in_review','approved','quarantined','retired')),
  trust_tier text NOT NULL DEFAULT 'untrusted',   -- untrusted | internal | vetted
  health text, last_seen_at timestamptz,
  UNIQUE (account_id, slug)
);

CREATE TABLE mcp_snapshots (
  id uuid PRIMARY KEY, account_id uuid NOT NULL,
  server_id uuid NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE,
  capability_digest text NOT NULL,       -- sha256 over the normalised capability list
  raw jsonb NOT NULL, discovered_at timestamptz NOT NULL,
  approved_at timestamptz, approved_by uuid, superseded_at timestamptz,
  UNIQUE (server_id, capability_digest)
);

CREATE TABLE mcp_capabilities (
  id uuid PRIMARY KEY, account_id uuid NOT NULL,
  server_id uuid NOT NULL, snapshot_id uuid NOT NULL REFERENCES mcp_snapshots(id) ON DELETE CASCADE,
  kind text NOT NULL,                    -- tool | resource | prompt
  name text NOT NULL, description text, input_schema jsonb,
  declared_read_only boolean, declared_destructive boolean,   -- the server's own hints, untrusted
  verified_risk text, verified_write boolean, verified_irreversible boolean,
  verified_data_classes text[], verified_by uuid, verified_at timestamptz,
  arg_rules jsonb,                       -- see 06-mcp-gateway.md
  UNIQUE (snapshot_id, kind, name)
);

CREATE TABLE mcp_grants (
  id uuid PRIMARY KEY, account_id uuid NOT NULL,
  server_id uuid NOT NULL REFERENCES mcp_servers(id) ON DELETE CASCADE,
  subject_kind text NOT NULL CHECK (subject_kind IN
    ('member','org_unit','directory_group','service_identity','agent')),
  subject_id uuid NOT NULL,
  capability_name text,                  -- NULL = every capability in the snapshot
  environments text[] NOT NULL,
  permission text NOT NULL CHECK (permission IN ('list','invoke','invoke_write')),
  pinned_snapshot_id uuid REFERENCES mcp_snapshots(id),
  requires_approval boolean NOT NULL DEFAULT false,
  rate_limit_per_min int, expires_at timestamptz, revoked_at timestamptz,
  granted_by uuid, granted_reason text
);
```

---

## E · Service identities, secrets, policy, budgets

```sql
CREATE TABLE service_identities (        -- platform keys, agents, CI jobs
  id uuid PRIMARY KEY, account_id uuid NOT NULL,
  kind text NOT NULL CHECK (kind IN ('platform_key','agent','ci','integration')),
  name text NOT NULL,
  acts_for_member_id uuid REFERENCES members(id),   -- required for platform_key
  agent_id uuid REFERENCES agents(id),
  org_unit_id uuid REFERENCES org_units(id),
  project_id uuid, environment text NOT NULL,
  scopes text[] NOT NULL,                -- model:invoke, mcp:invoke, mcp:usage, audit:write
  token_hash bytea NOT NULL UNIQUE, token_prefix text NOT NULL,
  generation int NOT NULL DEFAULT 1,
  expires_at timestamptz, last_used_at timestamptz, revoked_at timestamptz, revoke_reason text
);

CREATE TABLE agents (
  id uuid PRIMARY KEY, account_id uuid NOT NULL,
  kind text NOT NULL,                    -- cursor | claude_code | codex | gemini_cli | custom
  name text NOT NULL, owner_member_id uuid REFERENCES members(id),
  org_unit_id uuid REFERENCES org_units(id),
  framework text, version text,
  first_seen_at timestamptz, last_seen_at timestamptz,
  discovered boolean NOT NULL DEFAULT false   -- true = we saw it before anyone registered it
);

CREATE TABLE connections (               -- every upstream credential, one table
  id uuid PRIMARY KEY, account_id uuid NOT NULL,
  purpose text NOT NULL,                 -- model_provider | mcp_server | idp | webhook | kms
  label text NOT NULL, kms_key_ref text NOT NULL,
  current_version int NOT NULL, rotated_at timestamptz, expires_at timestamptz
);
CREATE TABLE secret_versions (
  connection_id uuid NOT NULL REFERENCES connections(id) ON DELETE CASCADE,
  version int NOT NULL, ciphertext bytea NOT NULL, created_at timestamptz NOT NULL,
  created_by uuid, PRIMARY KEY (connection_id, version)
);
-- No read endpoint exists for secret_versions. The data plane fetches by reference.

CREATE TABLE policies (
  id uuid PRIMARY KEY, account_id uuid NOT NULL,
  kind text NOT NULL CHECK (kind IN ('model','mcp','data','budget','approval')),
  name text NOT NULL, description text,
  state text NOT NULL CHECK (state IN ('draft','simulating','active','archived')),
  document jsonb NOT NULL, version int NOT NULL,
  created_by uuid, activated_by uuid, activated_at timestamptz,
  simulated_from timestamptz, simulated_findings jsonb
);
CREATE TABLE policy_bindings (
  policy_id uuid NOT NULL REFERENCES policies(id) ON DELETE CASCADE,
  subject_kind text NOT NULL, subject_id uuid,
  org_unit_id uuid, environments text[] NOT NULL,
  effective_from timestamptz NOT NULL, effective_to timestamptz,
  PRIMARY KEY (policy_id, subject_kind, COALESCE(subject_id,'00000000-0000-0000-0000-000000000000'))
);

CREATE TABLE budgets (
  id uuid PRIMARY KEY, account_id uuid NOT NULL,
  scope_kind text NOT NULL, scope_id uuid, environment text,
  period text NOT NULL,                  -- day | month | quarter
  limit_micros bigint NOT NULL,
  soft_pct int NOT NULL DEFAULT 80,
  on_exhaustion text NOT NULL,           -- degrade | approval | block
  degrade_to_alias text
);

CREATE TABLE policy_bundles (            -- what the data plane actually runs
  id uuid PRIMARY KEY, account_id uuid NOT NULL,
  version bigint NOT NULL, digest text NOT NULL, signature bytea NOT NULL,
  built_at timestamptz NOT NULL, expires_at timestamptz NOT NULL,
  contents jsonb NOT NULL                -- compiled policies, grants, aliases, endpoints, prices
);
```

---

## F · Activity (ClickHouse)

One wide table, written once, never updated, plus materialised views. Nothing here is a
foreign key: ids are denormalised copies so activity outlives configuration.

```sql
CREATE TABLE ai_events (
  event_id        UUID,
  occurred_at     DateTime64(3, 'UTC'),
  account_id      UUID,
  environment     LowCardinality(String),
  kind            LowCardinality(String),   -- model.request | mcp.call | mcp.list | policy.decision | dlp.finding
  -- identity
  member_id       UUID,
  service_identity_id UUID,
  agent_id        UUID,
  agent_kind      LowCardinality(String),
  session_id      String,
  org_path        String,                   -- '/northwind/eng/ide-users'  → prefix filters
  -- model side
  model_alias     LowCardinality(String),
  endpoint_id     UUID,
  provider_kind   LowCardinality(String),
  region          LowCardinality(String),
  residency_class LowCardinality(String),
  -- tool side
  server_slug     LowCardinality(String),
  tool_name       LowCardinality(String),
  arg_digest      String,
  -- outcome
  decision        LowCardinality(String),
  reason_code     LowCardinality(String),
  policy_id       UUID,
  approval_id     UUID,
  risk_score      UInt16,
  finding_kinds   Array(LowCardinality(String)),
  data_classes    Array(LowCardinality(String)),
  -- accounting
  tokens_in       UInt32, tokens_out UInt32, tokens_cached UInt32,
  tokens_measured UInt8,                   -- 0 = estimated, and the UI says so
  cost_micros     UInt64,
  latency_ms      UInt32, upstream_ms UInt32, inspect_ms UInt16,
  bytes_in        UInt32, bytes_out UInt32,
  http_status     UInt16,
  -- payload reference, resolvable only inside the data plane
  payload_ref     String,
  ingest_version  UInt16
)
ENGINE = ReplacingMergeTree(ingest_version)
PARTITION BY toDate(occurred_at)
ORDER BY (account_id, occurred_at, event_id)
TTL toDateTime(occurred_at) + INTERVAL 30 DAY TO VOLUME 'cold',
    toDateTime(occurred_at) + INTERVAL 400 DAY DELETE;
```

Rollups, graph edges, sketch columns and the retention story are in
[08-activity-and-scale.md](08-activity-and-scale.md).

Audit is separate from activity and stricter: `audit_events` in Postgres, append-only, hash
chained (`prev_hash`, `row_hash`), never TTL'd, covering who changed a policy, grant, role,
endpoint, snapshot, quarantine, approval or payload reveal. Activity answers "what did the
AI do"; audit answers "who changed the rules", and an auditor will ask for the second one
first.

## Index and query rules

| Query | Access path |
|---|---|
| Can this caller see this org unit | `member_visibility` prefix match, in memory after bootstrap |
| Members of a subtree | `org_unit_closure` join, or `path LIKE '/a/b/%'` |
| Effective grants for a subject | `access_grants` by (subject_kind, subject_id), filtered live in the bundle |
| Manager dashboard | rollup table, `org_path` prefix, bucketed time — never `ai_events` |
| One member's last 50 actions | `ai_events` with `account_id`, `occurred_at` range, `member_id` filter |
| Registry list for a caller | `mcp_servers` ⋈ effective `mcp_grants`; unprivileged callers cannot bypass the join |
| Cost for a period | rollup by day, summed as integers |

Forbidden, in review as much as in code: `SELECT count(*) FROM ai_events` without a
partition filter; any dashboard query that touches `ai_events`; any tenant query without
`account_id`; any float money.
