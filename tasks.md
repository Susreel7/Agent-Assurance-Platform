# Tasks

Working document. `PROJECT_STATE.md` records what happened; this records what is next and
why. One section per module, each with what exists, what is missing, and the specific work
to close the gap.

Status vocabulary, used strictly:

| Mark | Meaning |
|---|---|
| `done` | Written, exercised against Postgres or a browser, and verified by something that would fail if it broke |
| `partial` | Works for the path it was built for; named gaps below |
| `stub` | Endpoint or screen exists and returns something; not wired to real behaviour |
| `absent` | Not started |

---

## 0. What this product is, so scope arguments have a reference

Four things that are normally four purchases, sold as one suite because they share one
object — the agent — and are worth much less apart:

1. **A registry.** Every agent, its version history, what it is made of. Git-like, but the
   unit of change is an agent's *composition* rather than a file diff.
2. **Tracing.** What the fleet actually did: runs, steps, tool calls, model calls, cost.
   Langfuse and LangSmith territory.
3. **A control plane.** Which model an agent may route to, from where, for which data
   class — and evidence that the rule held.
4. **Assurance.** Accreditations, service levels, an append-only evidence chain a client
   or auditor can verify without trusting us.

The wedge is (1)+(4). Nobody else has them, and they are what makes (2)+(3) defensible
rather than a cheaper Langfuse. **The suite must never be positioned as "observability
with extras".** Tracing is the data source; assurance is the product.

### Where Langfuse and Portkey actually stop

Grounded in the Langfuse instance at `10.76.48.55` and Portkey's published feature set —
not in marketing comparisons.

| They model | They do not model | Our module |
|---|---|---|
| Trace → observation (span, generation, event), session, score | The *agent* as a durable, versioned thing that outlives a trace | `registry`, `composition` |
| Prompt versions, with labels and rollback | Tools, rules, skills, sub-agents, guardrails as versioned, diffable objects | `composition`, `releases` |
| Cost and latency per call, per user, per tag | Cost per **accredited** agent, attributable to a client engagement | `operations` + `engagements` |
| Gateway routing, fallbacks, retries | Whether a route was **permitted** for that data class and region, with proof | `model_routing`, `policy` |
| Scores and evaluations, LLM-as-judge | A verdict an auditor can verify without trusting our database | `evidence`, `accreditation` |
| A trace you can read | A change you can *approve*, by someone non-technical | `materiality`, `releases` |

The one-line version: **Langfuse answers "what happened". We answer "was it allowed, and
can you prove it to your client."** Every feature below should be justifiable against that
sentence, or dropped.

Two things Langfuse does that we currently do worse and should simply match, without
inventing a different vocabulary: **session grouping** (many runs are one user
conversation) and **trace-level scoring**. Both are in §2.

---

## 1. Contract integrity — done, and load-bearing

This is first because its absence caused every visible failure in the last session, and
because everything below is only as trustworthy as this is.

### What went wrong

Three independent failures, each invisible to the test suite:

1. **The console served a bundle from before the work.** `docker compose` built the web
   image and nginx served the frozen `dist`. Every other service reloaded from a source
   mount. Four new screens "did not work" because their routes were genuinely not in the
   bundle being served.
2. **Fifteen of fifty-three console request paths pointed at routes that never existed** —
   `/v1/findings` for `/v1/assurance/findings`, `/v1/sla/...` for `/v1/slos/...`. All
   fifteen returned 200 in mock mode, because the mock handlers were written against the
   same wrong paths.
3. **Roughly a dozen response types had drifted.** `PolicyVersion` declared `version`,
   `digest`, `signed_by` and `signature_status`; the API returns `semver`, `rules_digest`
   and `published_by`, and has no signature status. Those tables rendered blank columns
   and nothing failed, because a hand-written type agrees with itself.

### What now exists

| Guard | Catches | Status |
|---|---|---|
| `web` compose target `dev` runs Vite with source mount | A stale bundle being served as if current | `done` |
| `npm run client` generates `src/api/schema.d.ts` from `openapi.json` | Response shape drift, at compile time | `done` |
| `types.ts` `Wire<"SchemaName">` | Hand-written types diverging from the API | `done` |
| `npm run check:api`, wired into `npm run build` | A request path the API does not serve | `done` |
| `tests/smoke/sweep.py` | A route that raises on real data | `done` |

Verified: typecheck clean, lint clean, build passes, 56 of 56 console paths resolve
against 125 routes, 78 of 85 readable routes return 2xx with zero server errors.

The sweep found one real bug on its first run: `column c.name does not exist` in
`materiality/repository.py`, in raw SQL that named `customers.name` when the column has
been `display_name` since migration 0002. Two queries, both fixed.

### Remaining

- [ ] **`check:api` should also compare response shapes, not only paths.** It proves the
      URL exists; `Wire<>` proves the type matches *the spec we last generated from*.
      Neither proves `openapi.json` is current. Add a CI step that regenerates it from a
      running API and fails on a diff. Without this the whole chapter is theatre after the
      first backend change. **Highest priority item in this file.**
- [ ] Run `sweep.py` in CI against a seeded stack, `--post` included.
- [ ] `services/api/AGENTS.md` is a zero-byte file. Either it holds the contract or it
      should not exist; an empty file named after the coding contract is worse than none.

---

## 2. Tracing — `partial`, and the biggest build ahead

### What exists

- `agent_runs` (0008) and `run_steps` (0009), both partitioned monthly by `started_at`,
  both append-only with immutability triggers once terminal.
- `run_steps` models nesting via `parent_seq`, and `seq` is the reporter's own counter
  rather than a timestamp — concurrent graph branches routinely start in the same
  millisecond, so time ordering would shuffle them differently on every read.
- Observed graph derived from real step data, not from the descriptor.
- `docs/contracts/tracing.md` is the shared spec.
- Screens: Runs list, run detail waterfall, per-agent activity, cost, tools and MCP.

### What is missing, in priority order

- [ ] **Sessions.** A user conversation is many runs. Langfuse has this and it is the
      first thing anyone familiar with Langfuse will look for. Needs a `session_id` on
      `agent_runs`, a sessions list, and a session view that stitches runs in order with
      cumulative cost. *Do not invent a new word for this.* Migration + repository +
      screen.
- [ ] **Ingest that real agents can use.** This is the single thing blocking the product
      from being real: there is no machine credential, so a LangGraph agent cannot report.
      See §9. Until then every trace in the console is seeded.
- [ ] **OpenTelemetry GenAI semantic conventions on the ingest path.** Accept OTLP with
      `gen_ai.*` attributes and map to `run_steps`, rather than defining a bespoke
      wire format. This is how we get Cursor SDK and LangGraph instrumentation without
      writing an SDK per framework, and it is why the collector service exists.
- [ ] **Step payloads, deliberately bounded.** Right now there is nowhere to put a prompt
      or a tool argument, and the migration bounds every text column so they cannot be
      smuggled in. That was the right default and it is now the main gap versus Langfuse:
      you cannot debug a run you cannot read. Design decision required, not just code —
      see the open question at the end of this section.
- [ ] **Trace search that is not a `LIKE` scan.** Filter by outcome, model, tool, cost
      band, duration band, error kind, and free text over step names.
- [ ] **Waterfall that survives a thousand steps.** Virtualised rows, collapsed subtrees
      by default, a critical-path highlight. The current one renders every step.
- [ ] **Scores.** Per-run and per-step, human or automated, so evaluation results have
      somewhere to live. Feeds §6.
- [ ] Live tail for a running trace.

**Open question for you:** step payloads. Storing prompts and completions makes debugging
possible and makes us useful on day one. It also means the platform holds the exact
customer data that the residency rules in §4 exist to protect, which is an awkward thing
to explain in the same sales conversation. Three options, and I would want your call
rather than mine: store nothing (current), store digests plus a redacted preview, or store
full payloads in a customer-held bucket with only pointers in our database. The third is
the most defensible and the most work.

---

## 3. Change review — `partial`

The differentiator. Git for agent composition, readable by someone non-technical.

### What exists

- `composition` domain (0010): tools, rules, skills, sub-agents, configs, model policy,
  memory sources, guardrails — each with a stable identity so it can be tracked across
  versions rather than diffed as text.
- `aap extract` derives composition from a repository by static analysis.
- Reconciliation of declared against observed, emitting findings for undeclared use.
- `materiality` assigns a verdict per change against a rule ladder, with `rules_fired`
  recorded so a verdict can be explained.
- Review brief: deterministic plain-language summary. No LLM in the verdict path — a
  generated verdict cannot be an audit record.
- Release detail: semantic changes grouped by category, raw descriptor diff, impact rail
  now showing the real assessment, affected accreditations, and the rules that decided it.

### What is missing

- [ ] **The console cannot approve anything.** `/v1/releases/{id}/transition` exists and is
      unused by the UI, so the entire review workflow is read-only. This makes every demo
      end with "and then you would approve it". First frontend job. Needs optimistic
      update, the reviewed digest echoed back for the guard, and a rejection reason.
- [ ] **Push code and get a diff.** The stated product is "push your code here and see
      what changed". Today that means running the CLI yourself. Needs a repository
      connection, a webhook, extract-on-push, and a release opened automatically.
- [ ] Reviewer assignment and an "needs my approval" queue.
- [ ] Side-by-side rendering for prompt and rule text changes; the current diff is
      structural and unhelpful for prose.
- [ ] Explain *why* a change was ruled material, in the reviewer's words, tracing back to
      the specific rung of the ladder that fired.

---

## 4. Model routing and residency — `partial`

### What exists

- Model catalogue with provider, region, and the data classes each model may see (0012).
- Allowed-model resolution from agent policy plus the engagement's cross-border rules.
- Gateway config emission, LiteLLM-compatible.
- Drift detection: compares models actually observed in `run_steps` against what policy
  allows.
- `policy_decisions` records requested region against effective region, so a reroute is
  visible. The Rules screen now shows this, which is the clearest expression of the
  residency story anywhere in the product.

### The honest architectural position

**We do not block anything.** Enforcement requires sitting in the request path, and we are
not there — an external gateway is. We are the policy source and the evidence layer:
we decide what is allowed, emit configuration that makes a gateway enforce it, and hold
the proof afterwards.

That is a defensible position and it must be stated plainly in every demo, because the
scenario you described — "if the model routed is outside the country, block it" — is
answered by *our config running in their gateway*, not by us. Claiming otherwise fails the
first technical review.

### What is missing

- [ ] **A reference deployment where a block actually happens.** LiteLLM in compose, our
      emitted config loaded, an agent attempting a disallowed region, the refusal landing
      as a policy decision and an evidence event. Until this exists the residency feature
      is a claim. Highest-value demo asset in the product.
- [ ] `auto` model selection is the case you raised and the hardest one: the SDK chooses
      at call time, so the allowed set has to be resolved per request, not per deployment.
      Needs the gateway to call us, or a signed allow-list it can evaluate locally.
- [ ] Per-request residency attestation, so a client can ask "where did my data go on
      Tuesday" and get an answer from the evidence chain.
- [ ] Alert on drift rather than waiting for someone to open the screen.

---

## 5. Console and UI — `partial`, redesign not yet done

### Current state, honestly

Every screen now compiles, typechecks, lints, and calls a route that exists. That is a
floor, not a design. The layout is a navigation rail plus panels and tables, with design
tokens and chart primitives in place; it is coherent but it is not yet good, and the
information hierarchy on several screens is still "here is a table of everything".

### What is missing

- [ ] **A real design pass, screen by screen**, against one rule: a reader who did not
      build this should know, within five seconds of landing, what needs their attention
      and why. The Overview is closest; Findings, Evidence and Graph are furthest.
- [ ] Write actions everywhere they are missing — approve, reject, triage, resolve,
      acknowledge. The console is almost entirely read-only, which is the deepest UI
      problem and not a cosmetic one.
- [ ] Empty states that explain the feature rather than saying "No records". Started on
      the Rules and Service levels screens; needs doing across all of them.
- [ ] Keyboard navigation and a command palette that actually navigates.
- [ ] Saved views and shareable filter URLs.
- [ ] Density toggle. Auditors and engineers want different row heights.
- [ ] **Delete `services/web/SPEC.md` or make it true.** It describes the console as
      designed months ago and is now a third independent account of the same thing, which
      is exactly the pattern that produced the type drift.

---

## 6. Stress testing and rule suggestion — `partial`

### What exists

- Probe suites with deterministic oracles (0013). A probe asserts on observable state, not
  on whether an LLM judge liked the answer.
- LLM-as-judge is advisory only and recorded as such.
- Rule gap analysis against framework controls.

### What is missing

- [ ] **Probes cannot reach a real agent.** Same credential gap as §2, so the runner
      targets a synthetic. Everything here is unproven until an agent can be invoked.
- [ ] Suggested rules should arrive as a reviewable proposal, not a list.
- [ ] Regression suites per agent: probes that passed must keep passing, and a release
      that breaks one should be blocked by the gate.
- [ ] Prompt-injection corpus that is refreshed rather than fixed.

---

## 7. Evidence and assurance — `done` for the core, gaps at the edges

### What exists

- Append-only evidence events, Merkle batches per RFC 6962, published checkpoints.
- Inclusion proofs, chain verification, both surfaced in the console and the trust portal.
- Accreditation lifecycle with transitions and attestation runs.
- Service levels with measurements, breaches and credit calculation.

### What is missing

- [ ] **Nothing checks the published chain from outside.** The verifier is our own code
      reading our own database, which is the one thing a trust claim cannot rest on. Needs
      a standalone verifier that takes a checkpoint and a proof and needs no access to us.
- [ ] Checkpoint publication to somewhere we do not control.
- [ ] The trust portal has no authentication. It is public by slug, which is fine for a
      demo and not for a client.
- [ ] Evidence retention and legal hold.

---

## 8. Registry, BOM, graph — `done` for the core

- [ ] `AgentRef` resolves agent names by fetching the whole agent list and indexing it in
      the browser, because findings, evidence events and policy decisions return only an
      id. Correct at tens of agents, wrong at thousands: **denormalise the agent display
      name onto those list rows.**
- [ ] Graph discovery is seeded rather than discovered. Real discovery means reading
      runtime configuration and reconciling.
- [ ] Blast radius returns reachable nodes but not the traversed edges, so the console
      derives edges by checking both endpoints. Fine, but the API should return the paths.

---

## 9. Machine identity — `absent`, and it blocks three modules

**This is the most important unstarted item in the product.**

There is no way for an agent to authenticate. Human auth is OIDC-backed; machines have
nothing. Consequences: no real traces (§2), no real probe execution (§6), no push-to-diff
(§3). Every one of those features is currently demonstrated with seeded data, and a
technical buyer will find that out in the first session.

- [ ] Workload identity: a credential an agent holds, scoped to one agent and one
      environment, revocable, short-lived, with rotation.
- [ ] Reporter libraries for LangGraph and the Cursor SDK that carry it.
- [ ] Ingest authorisation that verifies the reporting agent is the agent being reported
      on — otherwise any agent can write any other agent's history into an append-only
      store, which is worse than no history.

---

## 10. Packaging the suite

The user requirement is a suite sold as a package, not one product. That has a technical
consequence: each module needs to be separately deployable and separately licensable, and
the one-way domain dependency rule (`AGENTS.md`, enforced by
`tests/unit/test_domain_layer_order.py`) is what makes that possible. It must not be
relaxed for convenience.

| Bundle | Modules | Sold as |
|---|---|---|
| Observe | `operations`, `graph`, `home` | Tracing and cost. Competes with Langfuse. Loss leader. |
| Control | `policy`, `model_routing`, `assurance` | Residency and guardrails. Competes with Portkey. |
| Review | `composition`, `materiality`, `releases` | Change review. **No direct competitor.** |
| Assure | `evidence`, `accreditation`, `attestation`, `sla`, `portal` | Client-facing assurance. **No direct competitor.** |

- [ ] Per-module licence gating and a deployment profile per bundle.
- [ ] Each bundle must be demonstrable alone, which is not currently true — the Overview
      screen reads from six domains.

---

## Immediate order of work

1. Regenerate-and-diff `openapi.json` in CI. Everything else is untrustworthy without it.
2. Release approve and reject in the console. Ends the read-only demo.
3. Machine identity. Unblocks tracing, probes and push-to-diff.
4. Sessions on traces.
5. LiteLLM reference deployment where a residency block actually happens.
6. Design pass on Findings, Evidence and Graph.
