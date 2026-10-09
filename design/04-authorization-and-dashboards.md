# 04 · Privileges, visibility and dashboards

Sketches: `diagrams/03-hierarchy-and-visibility.excalidraw`, `diagrams/10-dashboards-and-access.excalidraw`

> **Amended 2026-09-22.**
>
> **D-13** — **Cedar** becomes the policy engine. Administrators author in a structured UI
> that compiles to Cedar; Cedar is the audit artefact and the simulation target, never the
> authoring surface. Chosen because its native `principal / action / resource / context`
> shape matches the action model exactly `[B-73]` and because it compiles to SMT with
> machine-checked correctness proofs `[B-74]` — which makes *"will this policy change deny
> anything that is allowed today?"* a solver query rather than a replay harness. Policy
> lifecycle (version, simulation, activation, binding, exception, break-glass, rollback) is
> defined in [`14-ai-identity-and-authorization.md`](14-ai-identity-and-authorization.md) §7.
> **Exceptions and break-glass grants have mandatory expiry — a permanent exception is not
> representable in the schema.**
>
> **D-09** — the decision set expands to `allow · annotate · mask · tokenize ·
> route_internal · require_approval · step_up_auth · rate_limit · quarantine · deny`, and
> **every displayed number carries its enforcement grade**. A coverage figure without a
> denominator is not shipped.
>
> **Risk is categorical for enforcement.** A numeric score orders a review queue and never
> gates an action, and risk may only make a decision stricter — a low score never converts a
> deny into an allow (`14` §8).
>
> The RBAC model, the single visibility rule and the "which grant produced this answer"
> requirement are unchanged and correct.

Two separate questions, deliberately kept separate because conflating them is how
authorization bugs get shipped:

1. **Permission** — *may this caller perform this operation at all?* (`mcp:grant`, `policy:write`)
2. **Visibility** — *whose data may this caller see while doing it?* (self · subtree · account)

A DL admin and an account owner both hold `activity:read`. What differs is visibility. A
security admin and a finance admin both see the whole account. What differs is whether they
can see payloads. Every endpoint states which permission it needs and how it narrows
visibility; a reviewer can check both without reading the query.

## Permission catalogue

Flat strings, `resource:verb`, checked by a guard on the route. Grouped here for reading only.

| Group | Permissions |
|---|---|
| Identity | `member:read` `member:invite` `member:suspend` `org_unit:read` `org_unit:write` `directory:sync` |
| Access | `role:read` `access:read` `access:write` `access:approve` |
| Registry | `registry:read` `registry:read_all` `model:write` `endpoint:write` `endpoint:attest` `alias:write` |
| MCP | `mcp:read` `mcp:register` `mcp:approve_snapshot` `mcp:grant` `mcp:quarantine` `mcp:release` |
| Policy | `policy:read` `policy:write` `policy:simulate` `policy:activate` |
| Keys | `key:read` `key:issue` `key:revoke` |
| Activity | `activity:read` `activity:read_all` `payload:reveal` `graph:query` |
| Security | `incident:read` `incident:manage` `risk:read` `approval:decide` |
| Cost | `cost:read` `budget:write` `price:write` |
| Audit | `audit:read` `audit:export` `legal_hold:manage` |

Two hard separations of duty, enforced by `roles.separation_of_duty` and checked when a grant
is created:

- whoever can **grant access** may not also **decide approvals** on their own requests;
- whoever can **change a policy** may not **activate** it alone in production (two-person
  activation is a per-account setting, on by default for regulated accounts).

## Built-in roles

| Role | Scope | Permissions | Visibility | Who |
|---|---|---|---|---|
| `member` | account (implicit) | `activity:read` (self), `registry:read` (granted servers), `key:read`(own) | self | everyone |
| `dl_admin` | org_unit + subtree | `member:read` `activity:read` `cost:read` `registry:read` `mcp:grant`(within unit) `key:read` | subtree | the DL owner |
| `unit_manager` | org_unit + subtree | `dl_admin` + `budget:write`(unit) `access:write`(within unit, non-admin roles) | subtree | line manager, VP |
| `platform_admin` | account | registry, alias, endpoint, key, MCP register/approve | account, no payloads | the team that runs us |
| `security_admin` | account | `activity:read_all` `incident:*` `risk:read` `graph:query` `mcp:quarantine` `policy:write` `approval:decide` | account, payload only with approval | AppSec / SOC |
| `data_protection_admin` | account | `policy:write`(data) `payload:reveal` `incident:read` | account, payloads by approval | DPO / privacy |
| `finance_admin` | account | `cost:read` `budget:write` `price:write` | account, aggregates only, no prompts, no tool args | FinOps |
| `auditor` | account | `audit:read` `audit:export` `activity:read_all` (metadata only) | account, read-only, cannot change scope | internal audit, external |
| `account_owner` | account | everything, including `access:write` at account scope | account | 1–2 people, bootstrapped once |

Custom roles are permitted as a subset of an existing role's permissions, never a superset,
and never including `access:write` at account scope. That single restriction prevents
privilege escalation through role authoring, which is the usual hole in these systems.

## The visibility rule — one function, used everywhere

```
visible_paths(viewer) :=
    { primary path of viewer }                                         -- always themselves
  ∪ { u.path : grant(viewer, role, scope=org_unit u, subtree=true) }   -- expanded via closure
  ∪ { '/' }                     if viewer holds account-scoped activity:read_all

visible(event, viewer) :=
    event.member_id = viewer
  ∨ ∃ p ∈ visible_paths(viewer) : event.org_path starts with p
```

Enforcement contract, stated so it can be reviewed and tested:

- Every activity, cost, risk and graph endpoint takes an optional `scope` argument and
  **intersects it with `visible_paths(caller)` server side**.
- If the intersection is empty, the response is `403 scope_outside_grant`, never an empty
  chart. An empty chart reads as "no AI usage", which is a false and dangerous answer.
- No endpoint accepts a caller-supplied `member_id` filter without the same intersection.
- The visibility set is computed once per session bootstrap, cached with the session, and
  invalidated on grant or org change. It is never recomputed per row.
- One integration test per role asserts both directions: what they can see, and that a
  neighbouring unit returns 403.

Cost attribution uses the **primary** org unit so subtree sums never double-count a matrixed
person. Visibility uses **all** memberships so nobody disappears from their manager's view.
Both facts are shown in the UI next to the totals, because the first time the numbers differ
somebody will ask.

## Dashboards

Same data, five shapes. There is exactly one aggregate service:

```http
GET /v1/insights/usage
      ?group_by=org_unit|member|agent|model_alias|server|tool|decision|day
      &window=24h|7d|30d|custom
      &scope=/northwind/eng/ide-users
      &environment=prod
      &filter=decision:deny,data_class:customer_pii
→ { buckets[], totals, uniques (HLL), latency (t-digest), freshness_at,
    withheld_fields[], scope_applied }
```

`withheld_fields` and `scope_applied` are part of the response, not implicit. The UI renders
a lock with a reason instead of a blank cell, and states which scope produced the number.

### Member — "My AI"

Requests, tokens, cost, top tools, top models, my denials with the reason and the fix, my
prompt-hygiene score, my active platform keys with last-used, my sessions. No comparison
against colleagues (it is an engineering console, not a leaderboard), but a comparison against
their own trailing average, which is what actually helps somebody notice a runaway agent.

### DL admin / manager — "My organisation"

Subtree rollups with a member table; adoption (active people / assigned people); cost with
burn-down against budget and a linear forecast; denials and incidents in the subtree; the
tools and models their people actually use; MCP grants they own, with an inline revoke. Drill
to one member gives that member's view, minus payloads.

### Security admin — "Incidents and exposure"

Every denial and incident, grouped by reason code, with the member, agent, policy and
evidence; data-class flow map (internal → provider, by class, by volume); the activity graph
with blast-radius queries; agents seen but never registered (shadow AI); MCP servers by
trust tier with drift; one-click actions — quarantine, revoke, require approval, open a case.
Payload reveal is a request, not a button, and the request is itself audited.

### Platform / finance — "Fleet and spend"

Cost by org unit, model, provider and environment; alias split versus target with drift;
endpoint health, latency, breaker state and residency attestation age; price-book history and
corrections; key inventory with age and last use. No identifiable prompt content at all —
this role is the one most often given to a contractor.

### Auditor — "Prove it"

Immutable audit stream with the hash chain verified in the UI; evidence packs (a policy
version, its bindings, the decisions it produced in a window, and the approvals) exported as
a signed archive; policy diffs with who activated them; approval history. Read-only, and
explicitly unable to widen its own scope.

## Graph queries the security persona gets as buttons, not a query language

Backed by `graph_edges` (see [08](08-activity-and-scale.md)):

- Which agents have reached the production database MCP in the last 30 days?
- Which external providers have received `source_code` from this business unit?
- If this member's laptop is compromised, what can their agents reach today?
- Which MCP servers can touch `customer_pii`, and who holds a grant to them?
- Which tools were called with arguments that matched a protected resource pattern?

Each returns a subgraph plus the events that justify every edge, because a security engineer
will not act on an assertion they cannot expand.

## Prompt hygiene score (the "prompt quality" ask, made concrete)

A per-member, per-window score in [0, 100], shown to the member and aggregated for managers.
Composed only of things we can measure without reading the prompt as a human:

| Signal | Weight | Why |
|---|---|---|
| Secret-material attempts blocked | −40 each | Every one is an incident |
| PII classes sent without tokenisation | −10 each | Policy risk |
| Oversized context (p95 above the account norm) | −5 | Cost and leakage surface |
| Whole-repository or whole-file dumps | −5 | Usually avoidable |
| Repeated identical prompts (cache-worthy) | −3 | Cost |
| Denials for a policy already explained to them | −5 | Learning signal |
| Tool calls that required approval and were denied | −5 | Scope mismatch |

The score is never used punitively in the product copy; it is framed as "what to change", and
the member always sees the exact events that moved it. Any metric that a person cannot
inspect becomes a trust problem, and a control plane the engineers distrust gets bypassed.
