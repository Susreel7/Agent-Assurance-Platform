# Naming conventions

Read alongside `AGENTS.md`. That file says how code is *structured*; this one says what things
are *called*. Both are binding. A reviewer should be able to guess the name of anything in this
system from these rules alone.

The reason this file exists: the product's value is that a non-author can read a change and
understand it. That property dies the moment two modules call the same concept by two names.

---

## 1. The six layers and their module names

The layer numbering comes from page 3 of `agent-assurance-hld.drawio` and never changes.

| Layer | HLD name | Code location | Python module |
|---|---|---|---|
| 6 | Consumption | `app/domains/portal/`, `services/web/` | `portal` |
| 5 | Accreditation and attestation | `app/domains/accreditation/`, `materiality/`, `attestation/` | three modules |
| 4 | Assurance | `app/domains/policy/`, `sla/`, `assurance/` | three modules |
| 3 | Agent graph and system of record | `app/domains/customers/`, `engagements/`, `frameworks/`, `registry/`, `releases/`, `bom/`, `evidence/`, `graph/` | eight modules |
| 2 | Adapters and collection | `services/collector/` | — |
| 1 | What it observes | not our code | — |

Layer 2 has no API-side module. Collection is a separate process (`services/collector/`),
and the API side of ingest is `evidence.service.record_events` — the endpoint a collector
posts to. An `app/domains/collection/` was planned and removed: everything it would have
owned is already owned, with adapter registration and reconciliation living in `graph`
(`discovery_sources`, `discovery_findings`). A module whose whole surface is a re-export
is worse than no module.

Module directory names are **singular where the module is a capability** (`policy`, `evidence`,
`graph`) and **plural where it is a collection of records** (`customers`, `releases`,
`frameworks`). This is not arbitrary: `evidence.service` reads as a capability, `releases.service`
reads as a record set, and that is what each one is.

---

## 2. Database

### Tables

- `snake_case`, **plural**. `agents`, `evidence_events`, `graph_edges`.
- A join table is named for the relationship, not concatenated blindly:
  `engagement_agents` (which agents a client has in scope), not `agents_engagements`.
- A table holding the versions of X is `x_versions`: `agent_versions`, `policy_versions`.
- A table holding a *run* of a process is `<process>_runs`: `attestation_runs`, `probe_runs`.
- A table holding a measurement series is `<thing>_measurements`.

### Columns

| Pattern | Meaning | Example |
|---|---|---|
| `id` | surrogate primary key, `uuid` unless volume demands `bigint` | `agents.id` |
| `<table_singular>_id` | foreign key | `agent_id`, `customer_id` |
| `org_id` | tenant key. **Present on every tenant-owned table, always named this.** | — |
| `*_at` | `timestamptz`, a point in time | `created_at`, `approved_at` |
| `*_on` | `date`, no time component | `starts_on`, `ends_on` |
| `*_ms` | integer milliseconds | `request_timeout_ms` |
| `*_days` | integer days | `retention_days` |
| `is_*` / `has_*` | boolean. Prefer a positive: `is_reversible`, never `is_not_reversible` | — |
| `*_count` | a cached integer roll-up, maintained by trigger | `material_count` |
| `*_digest` | `sha256:<hex>` of content we deliberately do not store | `descriptor_digest` |
| `*_ref` | an identifier owned by something outside this system | `contract_ref`, `vcs_ref` |
| `*_uri` | a locator resolvable by the object store or a browser | `pack_uri` |
| `valid_from` / `valid_to` | a validity window; `valid_to IS NULL` means current | ownership, contacts |
| `state` | a value from an explicit state machine with defined transitions | `accreditations.state` |
| `status` | a value describing condition, with no transition rules | `customers.status` |

`state` versus `status` is a real distinction here, not a synonym. If there is a transition
diagram, the column is `state`.

### Timestamps: three different questions

Never collapse these, because an auditor asks them separately.

- `occurred_at` — when the thing happened in the world.
- `recorded_at` — when we learned about it. Differs from `occurred_at` by the collector's buffer.
- `created_at` — when this row was written. Differs again after a replay or a backfill.

### Enums

Postgres `CREATE TYPE`, `snake_case` singular: `lifecycle_state`, `change_category`,
`evidence_kind`. Labels are `snake_case`. Every ORM reference declares `create_type=False`.

Enum labels are **append-only**. Removing or renaming one is a breaking change to every stored
row; add a new label and migrate readers.

### Indexes and constraints

Driven by `NAMING_CONVENTION` in `app/db/base.py`, so hand-written migrations must match:

| Kind | Pattern |
|---|---|
| index | `<table>_<col>_<col>_idx` |
| unique | `<table>_<col>_key`, or a named `<table>_<thing>_unique` constraint |
| check | `<table>_<constraint_name>_check` |
| foreign key | `<table>_<col>_fkey` |
| primary key | `<table>_pkey` |
| RLS policy | `<table>_tenant_isolation` |

---

## 3. Python

### Files — fixed by `AGENTS.md`

`schemas.py`, `repository.py`, `service.py`, `router.py`. Four files, no fifth, with two
sanctioned exceptions that are pure computation and would otherwise bloat `service.py` past
readability: `domains/releases/differ.py` and `domains/materiality/rules.py`.

### Functions

| Layer | Pattern | Examples |
|---|---|---|
| `repository.py` | verb-first, states the SQL shape | `insert_agent`, `get_agent`, `list_agents`, `count_agents`, `update_agent`, `fetch_rollups` |
| `service.py` | verb-first, states the business intent | `publish_version`, `compute_readiness`, `evaluate_materiality`, `seal_batch` |
| `router.py` | reads as the operation the caller performs | `create_agent`, `get_readiness` |

Repository verbs are a closed set. Use exactly these:

`insert_` `get_` `list_` `count_` `update_` `delete_` `fetch_` `exists_`

`get_` returns one row or `None`. `fetch_` returns a computed or aggregated shape that is not a
plain row. `list_` returns rows without a total; pair it with `count_` when the caller pages.

### Pydantic models

| Suffix | Direction | Example |
|---|---|---|
| `*Create` | inbound, creating | `AgentCreate` |
| `*Update` | inbound, partial — every field optional | `AgentUpdate` |
| `*Upsert` | inbound, create-or-replace | `ContactUpsert` |
| `*Out` | outbound, one nested record | `ContactOut` |
| `*Summary` | outbound, list row. Flat, no joins needed to render | `AgentSummary` |
| `*Detail` | outbound, single-record page. Usually extends `*Summary` | `AgentDetail` |
| `*Page` | outbound envelope: `items`, `total`, `limit`, `offset` | `AgentPage` |
| `*Verdict` | outbound decision with reasons | `ReleaseGateVerdict`, `MaterialityVerdict` |

A model with no suffix is a domain value object used in both directions: `SemanticChange`,
`ReleaseDiff`, `ControlGap`.

### Exceptions

`<Domain><Condition>Error`, deriving from a per-domain base `<Domain>Error`:

```
CustomerError
├── CustomerNotFoundError
└── CustomerSlugTakenError
```

The `Error` suffix is mandatory — ruff `N818` enforces it. Raised in `service.py`, translated to
HTTP in `router.py` via that module's `_STATUS_FOR` dictionary, and nowhere else.

### Private helpers

Leading underscore, module-local: `_canonical_leaf`, `_model_label`. A helper that a second
module needs is not private — move it and drop the underscore.

### Constants

`UPPER_SNAKE` at module level. Frozen lookup tables are annotated explicitly:
`CATEGORY_LABELS: dict[ChangeCategory, str]`.

### Request dependencies

`app/api/deps.py` exports two forms of each guard, because FastAPI needs both and they
cannot share a name:

| Form | Shape | Used as |
|---|---|---|
| `WriteEnabled` | `Annotated[None, Depends(...)]` | a handler parameter: `_: WriteEnabled` |
| `WriteGuard` | `Depends(...)` | a decorator argument: `dependencies=[WriteGuard]` |

Prefer `WriteGuard`: no mutation handler has any use for the result, and an unused `_`
parameter invites someone to delete it. Passing `WriteEnabled` in a `dependencies=` list
raises at import time, not at request time, so the mistake takes the whole app down
rather than one endpoint.

The identity dependencies form a chain, each one depending on the one above it. Ask for
the narrowest that does the job, because asking for more than you need is what puts an
organisation requirement on an endpoint that has no tenant data:

| Name | Yields | Ask for it when |
|---|---|---|
| `Auth` | the verified token: principal and claims | almost never — it exists so the token is verified once per request |
| `CurrentPrincipal` | who is calling | the endpoint needs a caller but no tenant. Reference data, rule text |
| `CurrentOrg` | the organisation id | rare on its own; `Session` already depends on it |
| `Session` | a transaction scoped to that organisation | any endpoint touching tenant data |
| `VerifiedOrg` | the organisation id, confirmed to exist | alongside `Session`, so a stranger gets 403 rather than empty lists |

An endpoint with none of these is unauthenticated. That is occasionally right — `/healthz`
and `/readyz` carry no data and orchestrators do not hold tokens — but it is a decision,
and `tests/unit/test_api_auth.py` enumerates the routes and will fail until the exemption
is written down with its reason.

---

## 4. HTTP API

### Paths

- Plural resource collections, kebab-case where a word break is needed.
  `/v1/agents`, `/v1/releases`, `/v1/graph/blast-radius`.
- Nested only when the child cannot exist alone: `/v1/customers/{id}/frameworks`.
- A collection-level operation that is not a resource sits under `/-/` so it can never collide
  with a UUID path segment: `/v1/customers/-/framework-suggestions`.
- An action on one resource is a verb segment: `POST /v1/accreditations/{id}/submit`.
  Verbs appear **only** at the end of a path, never in the middle.

### Methods

`POST` create · `GET` read · `PATCH` partial update · `PUT` full replace or idempotent set ·
`DELETE` remove. No `PUT` for creation.

### Query parameters

`snake_case`. Paging is always `limit` and `offset`. Repeated parameters filter with OR
(`?status=active&status=prospect`); distinct parameters filter with AND. Free text is `search`.

### Headers

`X-Org-Id` in SaaS only. Ignored in `byoc` and `airgap` — see `app/api/deps.py`.

---

## 5. TypeScript and the console

| Thing | Convention | Example |
|---|---|---|
| component file | `PascalCase.tsx` | `AgentDetail.tsx` |
| hook file | `camelCase.ts`, exports `use*` | `useAgents.ts` |
| non-component module | `camelCase.ts` | `formatters.ts` |
| directory | `kebab-case` | `src/features/trust-portal/` |
| type from the API | mirrors the Python name exactly | `AgentSummary` |
| boolean prop | `is*` / `has*` / `can*` | `isLoading`, `canApprove` |
| handler prop | `on*`; the implementation is `handle*` | `onApprove` / `handleApprove` |

Route paths mirror API paths without `/v1`: `/agents/:agentId`, `/releases/:releaseId`.
Route parameters are camelCase and always suffixed `Id`.

Feature directories match the Python domain name one-for-one. `app/domains/releases/` has a
counterpart at `src/features/releases/`, and if it does not, one of the two is misnamed.

---

## 6. Vocabulary — one word per concept

This is the part that matters most. The left column is the only permitted term.

| Use | Never | Because |
|---|---|---|
| **agent** | bot, assistant, workflow | the unit of accreditation |
| **version** | revision, build, snapshot | `agent_versions` is the immutable spine |
| **baseline** | approved version, golden version | the version actually signed off; materiality is computed against it |
| **descriptor** | manifest, spec, card | the AAP document |
| **release** | changeset, deployment, PR | a governed transition between two versions |
| **change** | diff, delta | one typed row in `release_changes`; a *diff* is the whole set |
| **material** | breaking, significant | a change that invalidates an approval |
| **evidence** | log, audit log, trace | a governed fact with a digest, never content |
| **finding** | issue, alert, vulnerability | anything requiring remediation, whatever found it |
| **probe** | test, scan, red team | an adversarial check against a running agent |
| **accreditation** | certification, approval, sign-off | the state machine on page 5 of the HLD |
| **pack** | report, dossier, bundle | the signed rendered artifact |
| **attestation** | re-check, revalidation | a scheduled or triggered re-verification run |
| **control** | requirement, question | one row a framework demands an answer to |
| **framework** | standard, regulation | the container of controls |
| **customer** | client, account | the org our tenant delivers to and seeks approval from |
| **engagement** | project, contract, programme | one customer's delivery scope, carrying residency and SLO terms |
| **org** / `org_id` | tenant, company, workspace | our paying tenant. `tenant` appears only in `Tenancy` config |
| **principal** | user, identity | `person:`, `role:`, `team:` or `service:` prefixed |
| **posture** | health, score | the rolled-up risk figure, always shown with contributors |
| **drift** | divergence, mismatch | declared differs from observed, or deployed differs from accredited |

`customer` versus `org` is the distinction most likely to be got wrong, and it is load-bearing:
a TCS-like tenant is an **org**, the bank it must satisfy is a **customer**, and the work is an
**engagement**. Accreditation is always produced *for a customer*.

---

## 7. Evidence kinds

`evidence_kind` labels name the *fact being evidenced*, not the mechanism that produced it —
`residency_proof`, not `collector_span`. Mechanism goes in `evidence_events.detected_by`.

Every label must have at least one row in `control_mappings`, or it is evidence nobody asked
for. `tests/unit/test_evidence_kinds.py` enforces both directions.

---

## 8. Jobs

`jobs.kind` is `<domain>.<verb>` in the imperative: `attestation.run`, `evidence.seal_batch`,
`graph.rebuild`, `bom.extract`, `pack.render`. The handler is `handle_<domain>_<verb>` in
`app/workers/handlers/<domain>.py`.

`dedupe_key` is `<domain>:<entity_id>[:<window>]` — stable for the same logical work, so an
at-most-one-pending index actually collapses duplicates.

---

## 9. Configuration

Environment variables are `AAP_<SETTING_NAME_UPPER>`, matching the `Settings` field exactly.
`DATABASE_URL` is the one deliberate exception, because every platform-as-a-service injects
that name. `AAP_DATABASE_URL` is accepted as well, via `AliasChoices` — see D-025.

That second name is not a convenience. Declaring a `validation_alias` switches `env_prefix`
off for the field, so listing only `DATABASE_URL` meant the prefixed spelling was read by
nothing, and since the field carries a default the mistake produced no error at all: the
process pointed at `localhost:5432` and carried on. If you ever add another aliased field,
list the prefixed name too, or drop the field's default so a missing value fails loudly.

Nothing reads `os.environ` outside `app/config.py`. That is rule 8 in `AGENTS.md` and it is what
makes one image run in all three deployment modes.
