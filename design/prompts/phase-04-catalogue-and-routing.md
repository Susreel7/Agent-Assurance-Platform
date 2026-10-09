# Phase 4 — Model catalogue automation and routing rules

> **HISTORICAL — DO NOT EXECUTE.** Catalogue/routing is an optional later module, not part
> of the ledger-first MVP. See [`later-optional-modules.md`](later-optional-modules.md).

> Paste this whole file as the only prompt of a fresh session.

## Objective

Make a new model reachable by users **without an engineer**, and make an administrator able to
express routing intent — cost, balanced, quality, residency-strict, with proportional splits,
hard constraints, budgets and a degradation ladder — as a policy rather than as code.

## Prerequisite

Phase 3's gate: all four client surfaces route, residency is attested, cost is accounted.

## Read first

- `design/05-model-gateway.md` — "Making a new model available without an engineer" and "Routing rules an admin writes"
- `design/03-data-model.md` §C
- `design/diagrams/06-clients-and-model-catalogue.excalidraw`

## Scope

**In:** hourly discovery per provider; `model_candidates` with change detection; the review and
approval flow; alias lifecycle (`draft → approved → deprecated → retired`); routing policy with
modes, weights, priorities and failover groups; per-endpoint circuit breakers and health scoring;
budget ladder; split-drift reporting; the routing and catalogue screens.

**Out:** DLP-driven routing decisions beyond the `on_data_class` hook already in place (P6 fills
it in), anything in the activity pipeline (P7).

## Database (revision 0036)

```
0036  model_candidates (raw jsonb, change, first_seen, last_seen, reviewed_by, decision)
      model_endpoints: health_score, breaker_state, breaker_opened_at, last_error_class
      alias_targets: priority, failover_group, mode
      model_aliases: state machine + deprecation_notice, retire_after
      budgets: as designed (scope, period, limit_micros, soft_pct, on_exhaustion, degrade_to)
      routing_decisions_daily (small Postgres rollup: alias, endpoint, target_pct, actual_pct)
```

## Discovery job

One worker, one interface, six implementations:

| Provider | Call | Capability metadata |
|---|---|---|
| Azure Foundry | list deployments on the resource | SKU, region, model, context window |
| Bedrock | `ListFoundationModels`, `ListInferenceProfiles` | modalities, streaming support, profile geography |
| Vertex | publisher model list per configured location | context, modality, location |
| OpenAI | `GET /v1/models` | id, created; capability from the pinned capability table |
| Anthropic | `GET /v1/models` | same |
| Local | runtime `/v1/models` | context from the runtime config |

Rules:

- Runs hourly per account, per provider, with jitter; a provider failure is reported on the
  provider row, never silent, and never blocks the others.
- Writes `model_candidates` with `change ∈ {new, changed, withdrawn}` plus the raw response.
- **Nothing is auto-enabled.** No exceptions, no "trusted provider" shortcut. An auto-enabled
  model is an unreviewed data destination.
- `changed` includes a price change, a context-window change, a deprecation flag or a SKU change.
  A price change is a separate notification because it affects budgets.
- Withdrawal starts a deprecation window: the alias keeps serving from remaining targets, and the
  console names the members who used the departing endpoint in the last 30 days.

## Router

Implement exactly this order, in the data plane, on the cached bundle:

1. **Filter** — hard constraints, data-class rule, budget state, breaker state, health floor.
2. **Score** — `cost` by price; `quality` by the rolling quality proxy; `balanced` by a
   normalised weighted sum of price, latency and success rate; `residency_strict` by strictest
   residency first, then balanced.
3. **Pick** — weighted choice within the highest surviving priority tier, tie-broken
   deterministically on `hash(session_id, alias)` so a conversation stays on one endpoint.
4. **Failover** — on a retryable error or an open breaker, move to the next priority tier within
   the failover group; never across a hard constraint. Attempts are capped and recorded.
5. **Report** — write target vs actual split daily; drift over a threshold raises a warning.
6. **Degrade** — soft budget → notify the manager (not the developer); hard budget → the declared
   `on_exhaustion`; the reason travels on a response header and in the event.

Circuit breaker per endpoint: rolling window, open on error-rate or latency breach, half-open
probe, close on success. Breaker state is visible in the UI, because "why is everything on the
expensive model today" must be answerable in one screen.

## Policy surface

```
POST /v1/policy/model            create or update a model policy (draft)
POST /v1/policy/{id}/simulate    replay the last N days of events against the draft
POST /v1/policy/{id}/activate    two-person activation when the account requires it
GET  /v1/policy/{id}/diff        against the active version
```

**Simulate before activate is enforced server side.** Activation of a policy that has never been
simulated is refused. The simulation report states: requests that would newly deny, requests
that would change endpoint, projected cost delta, and the members most affected. Nobody should
discover a policy's blast radius in production.

## Frontend

- **Catalogue**: candidates with a diff view, provider evidence, and an approve flow that forces
  residency class, max data class and cost ceiling to be set.
- **Aliases**: targets with weights and priorities, a live preview of "with today's traffic, this
  split would send X% here", state transitions with deprecation notices.
- **Routing policy editor**: form-first with a YAML view; inline validation; a simulate button
  that shows the report before activate is available; diff against the active version.
- **Health**: endpoint table with health score, breaker state, p95, error classes, attestation age.
- **Budgets**: per org unit and environment, burn-down with forecast, what happens at exhaustion
  stated in words, not just a number.

## Invariants to add

| Name | Assertion |
|---|---|
| `inv_no_auto_enable` | A discovered model is never selectable until a human approves it |
| `inv_filter_precedes_score` | A constraint-failing endpoint is never selected at any weight or mode |
| `inv_failover_respects_constraints` | Failover never crosses residency or data-class constraints |
| `inv_session_affinity` | The same session and alias resolve to the same endpoint while it is healthy |
| `inv_simulate_before_activate` | Activation without a simulation is refused |
| `inv_split_drift_visible` | Target vs actual split is recorded daily and surfaced |

## Test plan

1. Discovery: fixture responses per provider; assert `new`, `changed`, `withdrawn` detection and
   that a price change raises its own notification.
2. Router property test: 10 000 synthetic requests across a mixed endpoint set; assert the
   realised split is within 2% of target, that no constraint-failing endpoint ever appears, and
   that affinity holds per session.
3. Failover: kill the primary mid-stream and assert a clean failover within the group, with the
   attempt recorded and the constraint respected.
4. Breaker: drive errors past the threshold, assert open → half-open → closed, and that the UI
   reflects each state.
5. Budget: soft and hard thresholds; each declared `on_exhaustion` behaviour; the member-visible
   reason.
6. Simulation: a policy that would deny 4% of last week's traffic reports exactly that, with the
   affected members listed.
7. End-to-end: add a new provider model and make it reachable from Cursor with **no code change
   and no deploy** — time it and record the number in the phase summary.

## Acceptance criteria (the gate)

- [ ] A new provider model reaches users through review and approval only, with no code change.
- [ ] Realised split matches target within 5% over a day of real traffic.
- [ ] Failover and breakers work and are visible, and never violate a hard constraint.
- [ ] Budget exhaustion degrades or blocks exactly as declared, with a reason the developer sees.
- [ ] A routing policy cannot be activated without a simulation report.
- [ ] Withdrawal of an endpoint names the affected members before it takes effect.

## Deliverables

Revision 0036; discovery workers; candidate review flow; alias lifecycle; router with filter →
score → pick → failover → report → degrade; circuit breakers; budgets; policy simulate/activate
with diff; catalogue, alias, routing, health and budget screens; six invariant tests; updated
`PROJECT_STATE.md`.

## Do not

- Do not let weights override a hard constraint "when nothing else is available". Deny is the
  correct answer; a quiet residency violation is not.
- Do not auto-approve models from a provider the customer already uses.
- Do not tune the scorer with magic constants in code; they are account configuration with
  defaults, and they are visible in the UI.
