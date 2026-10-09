# Enterprise AI Control Plane — approval plan

> **Detail lives in [`design/`](../../design/README.md).** This file is the summary an approver
> reads. Each section links to the document that specifies it, and to the Excalidraw sketch that
> shows it. Nothing here may be built before its phase gate opens — see
> [`design/11-phase-plan.md`](../../design/11-phase-plan.md).
>
> **Sequence change from the previous draft, stated explicitly rather than silently:** MCP
> enforcement was Phase 1; it is now Phase 5. Identity, tenancy and authorization come first,
> because an MCP grant is meaningless without a correct subject model — and the organisation and
> login problems that broke the console came from building features on top of an unfinished
> identity model. Nothing about the MCP design is reduced; it is reordered.

## Product boundary

One control plane, three operator outcomes, one graph underneath.

| AI Discovery | AI Governance | AI Security |
|---|---|---|
| Agents | Policies | DLP |
| Models | Routing | Secrets |
| MCP | Identity | Risk |
| Data | Approval | Blocking |

All three write to an **AI Activity Graph**. Security and audit are projections over that graph,
not separate silos. The unit of governance is the **AI action** — human → agent → model →
context → tool → data — not the model request.

The SaaS control plane must never require customer prompts, source code, credentials or tool
payloads to leave the customer's environment.

## Deployment model

Sketch: `design/diagrams/01-deployment-topology.excalidraw` · Spec:
[`design/01-deployment-and-tenancy.md`](../../design/01-deployment-and-tenancy.md)

Commercial default: **SaaS control plane + customer-hosted data plane.** Five supported modes —
SaaS, single tenant, self-hosted, air-gapped, development — as an `accounts.deployment_mode`
value plus capability flags, never a code fork.

The link between planes carries exactly two things: a **signed policy bundle** down, and
**signed telemetry envelopes** up. Outbound-only mTLS. Payload export off by default.

Three invariants that constrain everything else:

1. The control plane is never on the request path. Our outage must neither stop work nor open access.
2. The data plane enforces from the last signed bundle, and fails closed for regulated data classes
   once that bundle expires.
3. Telemetry loss never blocks a decision; shedding keeps every denial and is itself reported.

## User, identity and organisation data

Sketches: `design/diagrams/02-identity-and-onboarding.excalidraw`,
`03-hierarchy-and-visibility.excalidraw`, `04-data-model.excalidraw` · Specs:
[`design/02`](../../design/02-identity-and-onboarding.md), [`design/03`](../../design/03-data-model.md)

**One tree.** `accounts → org_units → members`, where an org unit is a business unit, department,
team **or distribution list** — one table, one closure table, one path column. The shape to fit is
the real one: one account, 30+ DLs, 200+ people in the Cursor DL, one admin per DL, a few admins
above all of them.

- `directory_groups` mirrors the customer's groups/DLs exactly as the directory reports them.
- `group_org_unit_rules` maps a group to an org unit and optionally to a role, so "this DL's admin
  can see these 200 people" is derived from the customer's own group management and survives staff
  changes without our involvement.
- A member can sit in many units. **Cost attributes to the primary unit** (so subtree sums never
  double-count), **visibility uses all memberships** (so nobody vanishes from their manager's view).
  Both rules are stated in the UI beside the totals.
- Reparenting rewrites closure and paths in one transaction; historical activity keeps the
  `org_path` it was recorded with, with an explicit "restate under current structure" toggle.
- Deprovisioning is designed, not implied: suspension revokes sessions and disables every service
  identity acting for that person, within one sync cycle.

**Login is configuration, not a build constant.** `auth_providers` holds one row per account per
IdP — kind, issuer, JWKS, claim map, group claim, email domains, onboarding mode. Five onboarding
modes (`scim`, `directory_pull`, `jit`, `invite`, `bulk`) converge on one idempotent resolver.
Exactly one auditable path per deployment gives an account its first administrator — a single-use
token, never "whoever logs in first".

**This is also the fix for the reported UI failures.** "Unable to login with Entra ID" and
"Something went wrong · Try again" come from the browser deciding auth mode at build time, saving a
session before onboarding succeeded, and loading each screen through separate queries that can each
403. Three endpoints replace that: `GET /v1/auth/config`, `POST /v1/auth/session` (server-side
exchange; no session exists if onboarding fails), `GET /v1/session/bootstrap` (identity,
permissions and navigation in one response). Phase 0 does only this.

## Privileges and per-persona dashboards

Sketch: `design/diagrams/10-dashboards-and-access.excalidraw` · Spec:
[`design/04`](../../design/04-authorization-and-dashboards.md)

Two separate questions, never conflated: **permission** (may you perform this operation) and
**visibility** (whose data may you see). A DL admin and an account owner both hold
`activity:read`; only the scope differs.

```
visible_paths(viewer) = {self} ∪ {granted org-unit subtrees} ∪ {'/' if account-scoped read_all}
```

Every activity, cost, risk and graph endpoint intersects the caller's requested scope with that set
**server side**. An empty intersection is `403 scope_outside_grant` — never an empty chart, because
an empty chart reads as "no AI usage", which is a false and dangerous answer.

Nine built-in roles: `member`, `dl_admin`, `unit_manager`, `platform_admin`, `security_admin`,
`data_protection_admin`, `finance_admin`, `auditor`, `account_owner`. Custom roles may only be a
subset of an existing role and may never hold account-scoped `access:write`. Two separations of
duty are enforced: you cannot decide your own access request, and production policy activation
takes two people.

Five dashboards over **one** aggregate service (`/v1/insights/*`): member, manager/DL admin,
security admin, platform/finance, auditor. Reading a prompt body is a separate permission
(`payload:reveal`) **plus** an audited approval, and responses declare `withheld_fields` so the UI
shows a lock with a reason rather than a blank cell.

## Model gateway — what is actually possible in Cursor and the other clients

Sketches: `design/diagrams/05-model-request-lifecycle.excalidraw`,
`06-clients-and-model-catalogue.excalidraw` · Spec: [`design/05`](../../design/05-model-gateway.md)

Researched against current vendor documentation. The honest summary:

> **Inside the editor we can configure. At the gateway we can enforce.**

| Client | How we route it | What the org can enforce centrally |
|---|---|---|
| **Cursor** | Settings → *Override OpenAI Base URL* + our platform key | Enterprise: Team Settings → Models baseline and Organization Groups; Admin API model-access routes; disable personal BYOK; MCP server allowlist; `~/.cursor/permissions.json` via MDM |
| **Claude Code** | `ANTHROPIC_BASE_URL` (+ Bedrock/Vertex/Foundry variants) with an auth token | Managed settings: `availableModels` (also checked at `/v1/messages`), `permissions.allow/ask/deny`, `allowManagedPermissionRulesOnly`, `allowedMcpServers`, `allowManagedMcpServersOnly`, `disableBypassPermissionsMode` |
| **Codex CLI** | `~/.codex/config.toml` → `[model_providers.aap]` with `base_url`, `env_key`, `wire_api = "responses"` | Provider keys are user-level; a repo-local config cannot redirect traffic |
| **Gemini CLI** | `GOOGLE_GEMINI_BASE_URL` / `GOOGLE_VERTEX_BASE_URL` | Thin — treat gateway + MDM as the only real control |

Two consequences that shape phase 3:

- Cursor's base-URL override currently carries **all** OpenAI-family traffic, including built-in
  model picks. Our OpenAI surface must therefore be complete and fast (chat completions **and**
  responses, streaming, tools, multimodal), not a thin filter. Codex requires the Responses API
  outright.
- Anything enforced by a file on the developer's machine runs on hardware the developer
  administers. We generate those configs as defence in depth; we never present them to a security
  team as controls. The attestable control is our endpoint holding the upstream credential.

### "Which zone is the model in?" — answered precisely

A model name carries **no** location. Processing location is a property of the endpoint and how it
was provisioned:

| Provider | Pins the location | Does not |
|---|---|---|
| Azure Foundry | `Standard` / `ProvisionedManaged` (deployment region); `DataZoneStandard` (US/EU/APAC zone) | `GlobalStandard` — any Azure region |
| AWS Bedrock | in-region endpoint; **geographic** inference profile (within the geography, SCPs aligned) | **global** inference profile — worldwide, and cheaper, so somebody will have enabled it |
| Vertex AI | a regional endpoint | the global endpoint |
| OpenAI direct | account residency configuration | the model name |
| Self-hosted | the host you run it on | — |

So residency is a **column on `model_endpoints`** (`region`, `zone`, `deployment_sku`,
`residency_class ∈ {region_pinned, zone_pinned, global_unpinned}`, `evidence_ref`, `attested_at`),
attested from the provider's control API, re-verified weekly, ageing to `unverified` after 30 days.
Policy filters on it; an unattested endpoint cannot serve any class above `internal`. The console
shows **attested with evidence** or **unverified**, and never renders an inferred region as proof.
What we cannot do — prove at runtime which datacentre served a token — we say out loud.

### Onboarding a new model without an engineer

Hourly discovery per provider → `model_candidates` with `new | changed | withdrawn` → **nothing is
auto-enabled** → admin review sets residency class, max data class and cost ceiling → alias target.
Clients only ever name an alias (`aap-fast`, `aap-balanced`, `aap-deep`, `aap-internal-secure`), so
a provider change is invisible to them.

### Admin routing rules

A policy, not code: `mode_default` (`cost` | `balanced` | `quality` | `residency_strict`), a
proportional `split` across aliases, `hard_constraints` (residency, max data class, denied
providers), a `budget` with a declared degradation ladder, and `on_data_class` overrides. The
router **filters** on hard constraints, then scores, then picks with session affinity, then reports
target-versus-actual drift. A constraint is never traded off against a weight.

## Tool restriction — how a tool is actually blocked

Sketch: `design/diagrams/07-mcp-governance.excalidraw` · Spec:
[`design/06`](../../design/06-mcp-gateway.md)

The client is given a per-member gateway URL and a platform key. The gateway holds the real
credential. `tools/list` is filtered by grant, so a tool you cannot use does not appear and the
model never proposes it. `tools/call` re-validates independently — a fabricated tool name gains
nothing — through ten ordered checks, all failing closed: key → server state → grant → pinned
snapshot → schema → argument rules → input inspection → rate limit → approval for write or
irreversible → dispatch, then response scanning.

**Argument-level rules** are what customers actually need: `execute_sql` allowed for `SELECT`,
approval for `INSERT`, blocked for `DELETE` and on `*_pii` tables; `create_pull_request` denied on
`payments-*`; `read_file` confined to the workspace with `**/.env*` denied. An argument a rule
cannot parse is treated as a deny match.

The registry itself is grant-filtered: **a member with a valid platform key and no grant cannot see
that the server exists.** Seeing the whole estate is a privilege (`registry:read_all`). Drift and
rug-pulls cannot take effect because grants are pinned to an approved snapshot, and quarantine is
effective for every caller within one cache TTL (≤ 5 s).

stdio servers (the shipped example is `examples/mcp/demo_server.py`) run **sandboxed inside the
data plane** — pooled, resource-capped, no inherited environment, no egress beyond an allowlist —
never on a developer machine, because that would give away the credential boundary.

## PII and secrets in prompts

Sketch: `design/diagrams/08-data-protection.excalidraw` · Spec:
[`design/07`](../../design/07-data-protection.md)

Six detection layers, cheapest first: literal/prefix → structural with checksums → entropy → named
entities → schema-aware against the customer's data catalogue → code-aware. Raw bytes **and**
JSON-decoded values are scanned at any depth; a raw-only scan is bypassed by `sk-\u0070roj-…`.

Actions per `(data class, destination residency)`: `allow` · `annotate` · `mask` · `tokenize` ·
`route_internal` · `require_approval` · `block`. Defaults are a published matrix.

Reversible tokenisation for the classes a model must reason about: `John Smith` →
`<PERSON_1>` on the way out, restored **inside the customer boundary** on the way back, including
across stream chunk boundaries. The vault is AEAD under the customer's KMS key, session-scoped,
TTL in hours; the control plane never receives the map. **Credentials are never tokenised** — a
reversible credential is still a credential.

Two rules that decide whether this succeeds commercially:

1. **A rule may not block until its false-positive rate has been measured** on the customer's own
   traffic in annotate mode, and the rate is displayed next to the toggle.
2. **Detection reduces risk; it does not prove absence.** That sentence ships in the product. For
   classes that cannot leak, the control is the destination (`route_internal`), not redaction
   confidence.

## Monitoring at enterprise volume

Sketch: `design/diagrams/09-telemetry-and-scale.excalidraw` · Spec:
[`design/08`](../../design/08-activity-and-scale.md)

Design point: **100k governed requests per 30 minutes** (~56/s) sustained, 10× burst, ~4 tool calls
each → ~3 000 events/s peak, ~25M events/day, ~9 GB/day compressed.

```
gateway ring buffer → collector (batch, sign, spool) → Kafka/Redpanda (partition by account)
   → consumers: raw insert · rollups · risk · graph → ClickHouse (day partitions, TTL 30d→400d)
```

- **Dashboards never touch raw events.** Three rollup grains (1m/1h/1d) with t-digest latency,
  HyperLogLog actors, integer `cost_micros`, and `org_path` for prefix-scan manager views.
- **Cardinality is a review gate.** Enumerable dimensions only; free-form text is never a
  dimension; the tail beyond top-N folds into `other`.
- Algorithms named and justified: t-digest, HLL, count-min, EWMA+MAD, closure table, token bucket,
  Bloom filter, Aho–Corasick, reservoir sampling.
- Cost is computed at ingest from an effective-dated price book, as integers; estimated tokens are
  marked as such everywhere; corrections restate visibly with a reason; reconciliation against the
  provider invoice targets 1%.
- The **activity graph** is projected from the same stream as the events, so it can never disagree
  with the evidence. Five security questions ship as buttons, each expandable to the calls that
  justify every edge.
- Every dependency failure has a declared, tested behaviour. "Unknown" is not acceptable for what a
  security control does when its dependency is down.

## Migration from what exists today

Spec: [`design/10-migration.md`](../../design/10-migration.md)

Expand → backfill → dual-read → contract, across revisions 0022–0035. Nothing is dropped until its
replacement has served production reads for a full phase. `organizations` becomes `accounts`;
`teams`/`team_members` fold into `org_units`; `workload_credentials` becomes `service_identities`;
the MCP tables are the closest to target and are extended; `model_*` routing is restructured with
residency; ClickHouse is additive.

The one risky revision is **0027 (grants)**, which carries a mandatory diff guard: snapshot every
member's effective permissions, migrate, recompute, and abort the deployment on **any** difference —
including a widening.

**Decision needed (D-G):** roughly 35 of ~60 existing tables belong to the agent-accreditation and
compliance-framework domains, which are a different product from the control plane. Recommendation
is to park them behind a feature flag rather than carry them through every future migration.

## Phase plan

Sketch: `design/diagrams/11-phase-roadmap.excalidraw` · Prompts:
[`design/prompts/`](../../design/prompts/README.md)

| Phase | Name | Gate |
|---|---|---|
| 0 | Stabilise the console | Every route renders for three personas; no reasonless errors; no session without a member |
| 1 | Tenancy and identity | 30 DLs × 200 members imported; re-import is a no-op; suspension cascades |
| 2 | Authorization and visibility | A DL admin sees exactly their subtree, proven both ways; 0027 provably neutral |
| 3 | Model gateway core | Cursor, Claude Code, Codex and Gemini routed and attributed; p95 +12 ms; residency attested |
| 4 | Catalogue and routing | A new model reaches users with no code change; split within 5% of target |
| 5 | MCP gateway | An unprivileged member cannot see or call a server; rug-pulls inert; quarantine ≤ 5 s |
| 6 | Data protection | Measured false-positive rate before any rule may block; tokenised round trip intact |
| 7 | Activity graph and scale | 3 000 events/s with dashboard p95 < 300 ms; denials never shed |
| 8 | Hierarchy, cost and alerts | Cost reconciles to the invoice within 1%; no double counting |
| 9 | Deployment packaging | Customer-VPC install with no vendor access to payloads, demonstrated |

Sequencing: `0 → 1 → 2`, then parallel chains `3 → 4` and `5 → 6`, then `7 → 8 → 9`. Each phase is
one paste-ready prompt, one session, one gate. A phase is finished when its gate is demonstrated,
`PROJECT_STATE.md` records it, and every earlier gate still passes.

## Required engineering boundaries

- Postgres control-plane state is tenant-scoped and row-level secured; tenancy is never enforced by
  remembering a `WHERE` clause.
- High-volume activity never lands in transactional tables.
- Credentials are references to customer/local secret stores, never UI-readable values.
- Policy decisions are deterministic, versioned and explainable, with the same reason code in the
  API error, the console and the audit row.
- A control-plane outage cannot silently bypass enforcement.
- No fixture or demo seed runs in the default profile.
- Destructive database operations require an explicit, scoped command.
- Money is integer micros. Dashboard dimensions are enumerable. Free-form text is never a dimension.
- We never claim proof we do not have — about residency, about DLP coverage, or about client-side
  enforcement.

## Open decisions

Tracked in [`design/README.md`](../../design/README.md#status-of-this-design) as D-A … D-G. They are
answered in that table, not in chat, so the next session finds them where it will look.
