# 11 · Phase plan

Sketch: `diagrams/11-phase-roadmap.excalidraw`
Prompts: [`prompts/`](prompts/)

> **SUPERSEDED 2026-09-22 by [`17-research-conclusions.md`](17-research-conclusions.md) §7.**
>
> The ten phases below were optimised for architectural completeness. They deliver a
> security outcome around phase seven, build three commodity layers on the way
> `[B-16][B-18][B-29][B-30]`, and — the decisive problem — the two enforcement points they
> centre on (P3 model gateway, P5 MCP gateway) were **both absent from the path of the
> reference incident of 2026** `[B-01][B-02]`.
>
> **The replacement is a six-item read-only MVP** — an agent action ledger across Claude
> Code, Cursor and Copilot, with `shell.exec` / `net.http` / `fs.read` observed, enforcement
> grading, and shadow-agent plus credential-exposure discovery. It deploys in days, needs no
> architecture review, adds no latency, and produces the customer's own evidence that they
> need enforcement next.
>
> **The prompts were regenerated on 2026-09-22.** Follow
> [`prompts/README.md`](prompts/README.md): F0 → F1 → F2 → M1 → M3 → M4 → M2 → M5 →
> V1 → packaging. Files named `phase-00-*` through `phase-09-*` are non-executable
> historical records and carry explicit warnings.
>
> **What to keep from this document:** the *Rules for every phase* section below is good
> practice and applies unchanged — design before code, schema before endpoints before UI, no
> dummy data, every earlier gate still passing, invariants are tests, and a phase that finds
> the design wrong stops and says so with a decision ID. Keep all seven.
>
> The ten phases are retained below as the historical record of a superseded decision, per
> the rule that important architectural decisions are never silently rewritten.

Ten phases. Each is one paste-ready prompt, sized for a single working session, with its own
gate. A phase is finished when its gate is **demonstrated** — not written, not "should work" —
`PROJECT_STATE.md` records it, and every earlier phase's tests still pass.

## Order and dependencies

```
P0 Stabilise ──▶ P1 Tenancy & identity ──▶ P2 Authorization & visibility
                                                   │
                           ┌───────────────────────┼───────────────────────┐
                           ▼                       ▼                       ▼
                 P3 Model gateway core     P5 MCP gateway          (P7 can start
                           │                       │                 once P3 emits
                           ▼                       ▼                 events)
                 P4 Catalogue & routing    P6 Data protection
                           └───────────┬───────────┘
                                       ▼
                            P7 Activity graph & scale
                                       ▼
                            P8 Hierarchy, cost & alerts
                                       ▼
                            P9 Deployment packaging
```

Parallel is allowed only where marked: P3→P4 and P5→P6 are two independent chains after P2.
Everything else is sequential, because each one changes a contract the next depends on.

## The phases

| Phase | Name | Session goal | Gate |
|---|---|---|---|
| **P0** | Stabilise the console | Login, session and error handling become structural, not incidental | Every route in the manifest renders for three personas with zero console errors; a failed onboarding leaves no session; no screen shows "Something went wrong" without a reason code |
| **P1** | Tenancy and identity | `accounts`, `org_units` + closure, `auth_providers`, onboarding modes, DL import, admin bootstrap token | 30 DLs × 200 members imported, re-import is a no-op, reparenting rewrites the closure, suspension revokes sessions and keys |
| **P2** | Authorization and visibility | Roles, scoped grants, the visibility function, persona dashboards on real aggregates | A DL admin sees exactly their subtree; a neighbouring unit returns `scope_outside_grant`; payload reveal requires an approval; one test per persona both ways |
| **P3** | Model gateway core | OpenAI chat + responses, Anthropic, Gemini surfaces; platform keys; endpoint registry with residency; policy; cost | Cursor, Claude Code, Codex and Gemini CLI all route through the gateway, attributed to the right member, with p95 added latency under 12 ms |
| **P4** | Catalogue and routing | Hourly discovery, alias lifecycle, modes and weights, failover, budget ladder | A new provider model reaches users with no code change; actual split matches target within 5%; budget exhaustion degrades as declared |
| **P5** | MCP gateway | Three-screen onboarding, all three transports, arg rules, approvals, drift, grant-filtered registry | An unprivileged member can neither see nor call a server; a rug-pulled tool does not take effect; quarantine is live within 5 s |
| **P6** | Data protection | Detector layers, classes, action matrix, annotate mode, token vault, response scanning | Measured false-positive rate per rule before any rule may block; a tokenised round trip returns real values to the developer and never to the provider |
| **P7** | Activity graph and scale | Event envelope, queue, ClickHouse, rollups, sketches, graph projection, retention | 3 000 events/s sustained with dashboard p95 under 300 ms; shedding keeps every deny; graph answers the five security questions |
| **P8** | Hierarchy, cost and alerts | Manager and finance views, budgets, forecasts, anomaly alerts, exports | Cost reconciles to a provider invoice within 1%; a manager's subtree totals do not double-count matrixed members |
| **P9** | Deployment packaging | Helm data plane, signed bundles, offline enforcement, SIEM/OTLP export, evidence packs | A customer-VPC install enforces with no vendor access to payloads; bundle expiry fails closed for regulated classes |

## Rules for every phase

1. **Read `design/` first, not the code.** Where they disagree, the design is the intent and the
   discrepancy is reported.
2. **Schema before endpoints before UI**, in one session, so nothing is half-typed.
3. **No new dummy data, ever.** Fixtures live behind an explicit `demo` profile and are never
   loaded by default. The reported "why is the data never clean" problem came from seeds
   running on startup.
4. **Every phase leaves the previous gates passing.** If a gate regresses, that is the phase's
   first job.
5. **Update `PROJECT_STATE.md`** at the end: module status, migrations with their *real* status,
   a three-line session log, and the next slice. `OK` means written, reviewed and tested.
6. **Invariants are tests.** Each phase adds named invariant tests to the list and never removes
   one. The list is the regression contract for a system where a mistake means a data leak.
7. **A phase that discovers the design is wrong stops and says so**, in the decisions table,
   with an ID. It does not silently improvise a different architecture — which is how the
   organisation model drifted the first time.

## Estimated shape (not a commitment)

| Phase | Backend | Frontend | Infra | Risk |
|---|---|---|---|---|
| P0 | M | L | — | low |
| P1 | L | M | — | medium (0027 grants) |
| P2 | M | L | — | high (authorization) |
| P3 | XL | M | M | high (latency, provider parity) |
| P4 | L | M | — | medium |
| P5 | XL | L | M | high (stdio sandbox) |
| P6 | L | M | — | medium (false positives) |
| P7 | L | M | L | medium (throughput) |
| P8 | M | L | — | low |
| P9 | M | S | XL | medium |

## How to run a phase

Paste `design/prompts/phase-0N-*.md` into a fresh session. Nothing else. Each prompt restates
its own scope, schema, API surface, UI surface, invariants, tests and acceptance criteria, so a
session never has to reconstruct the architecture from eleven documents — and so a mistake in
one phase cannot quietly propagate into the next.
