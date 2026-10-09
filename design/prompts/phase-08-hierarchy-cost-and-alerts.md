# Phase 8 — Hierarchy dashboards, cost accounting and alerts

> **HISTORICAL — DO NOT EXECUTE.** Cost accounting is V2 and the old dashboard sequence
> optimizes architectural completeness instead of validating the action-ledger wedge.

> Paste this whole file as the only prompt of a fresh session.

## Objective

Give every person the view of AI usage their role justifies, make the money numbers reconcile to
the provider invoice within 1%, and turn the activity stream into a small number of alerts people
act on rather than a wall of charts.

## Prerequisite

Phase 7's gate (rollups and graph) and Phase 2's gate (visibility).

## Read first

- `design/04-authorization-and-dashboards.md` — the five personas and the hygiene score
- `design/08-activity-and-scale.md` — "Cost and token accounting"
- `design/diagrams/10-dashboards-and-access.excalidraw`

## Scope

**In:** the manager/DL and finance views in full; budgets with burn-down and forecast; anomaly
detection with per-subject baselines; the alert catalogue with routing to Slack/Teams/email/webhook;
scheduled reports and exports; invoice reconciliation; the prompt-hygiene score; cost attribution
rules for shared agents and CI.

**Out:** new enforcement. This phase adds no new block path; it makes the existing ones legible.

## Database (revision 0039)

```
0039  alert_rules (kind, scope, threshold, window, severity, channels[], enabled, cooldown)
      alert_events (rule_id, subject, fired_at, resolved_at, evidence_ref, state, ack_by)
      baselines (subject_kind, subject_id, metric, ewma, mad, updated_at)
      report_schedules (scope, persona, cadence, format, recipients[], last_run_at)
      invoice_reconciliations (provider, period, our_micros, invoice_micros, delta, unattributed)
      hygiene_scores_daily (member_id, day, score, components jsonb)
```

## Cost accounting, finished properly

1. **Attribution:** to the member's **primary** org unit, so subtree sums never double-count a
   matrixed person. Shared agents and CI identities attribute to the service identity's org unit,
   with the triggering member kept as a second dimension so both "what did this team spend" and
   "who caused it" are answerable. State both rules in the UI next to the totals, because the first
   time two numbers differ somebody will ask.
2. **Estimated vs measured:** every surface showing estimated tokens says so. A period whose
   estimated share exceeds a threshold shows a warning, because the invoice will not match.
3. **Corrections:** a price-book change runs a bounded recompute writing a new `ingest_version`
   with a reason; affected reports show a "restated" marker and link to the reason.
4. **Reconciliation:** per provider, per period — our sum, the invoice, the delta, and the requests
   we could not attribute. Within 1% is this phase's gate. When it is not, the report says which
   dimension is missing rather than leaving somebody to guess.
5. **Budgets:** per org unit, per environment, per period, with soft and hard thresholds, a linear
   plus seasonal forecast, and the declared exhaustion behaviour stated in words.

## Anomaly detection

Per-subject baselines with EWMA and MAD, which is robust to exactly the outliers we are hunting.
Subjects: member, agent, service identity, org unit, tool, alias.

| Alert | Condition | Severity | Channel |
|---|---|---|---|
| `spend_spike` | daily cost > baseline + k·MAD, and above an absolute floor | high | manager + finance |
| `volume_spike` | requests/hour > baseline + k·MAD | medium | manager |
| `new_destination` | a data class reaching a provider it never has for this account | high | security |
| `credential_attempt` | any `secret_material` block | critical | security, always an incident |
| `denial_storm` | denials for one member > N in a window | medium | manager + security |
| `runaway_agent` | one session exceeds a request or cost cap | high | member + manager, with a suggested cap |
| `tool_first_use` | a subject calls a high-risk tool for the first time | low | security |
| `budget_soft` / `budget_hard` | threshold crossed | medium / high | manager + finance |
| `shadow_agent` | an agent kind seen that nobody registered | medium | security |
| `attestation_stale` | an endpoint's residency attestation aged out | medium | platform |

Rules for alerts, or nobody will keep them on: an absolute floor as well as a relative one; a
cooldown per (rule, subject); grouping so one incident is one message; every alert names the
member, agent, policy, reason code and evidence, and carries the one-click actions. An alert
nobody can act on gets deleted from the catalogue, not tuned forever.

## Frontend

- **Manager / DL view**: subtree cost, tokens, requests, adoption (active of assigned), ranked
  members, top tools and models, denials and incidents, budget burn-down with forecast, MCP grants
  they own with inline revoke, and drill-through to one member.
- **Finance view**: cost by org unit, model, provider, environment; estimated share; alias split vs
  target; price-book history; reconciliation report; export.
- **Member view**: completed — usage, cost, top tools, denials with fixes, hygiene score with the
  exact events that moved it, my keys, my sessions, and who can see my activity.
- **Alerts**: catalogue with thresholds and channels; feed with ack, assign, resolve; each alert
  opening onto its evidence.
- **Reports**: schedule a persona view to a cadence and recipients; CSV, XLSX and PDF; every export
  audited.
- **Hygiene**: the components table from `design/04`, always expandable to the underlying events —
  a metric a person cannot inspect becomes a trust problem, and distrusted controls get bypassed.

## Invariants to add

| Name | Assertion |
|---|---|
| `inv_no_double_count` | A member in three units contributes once to any ancestor total |
| `inv_estimated_marked` | Any total including estimated tokens is marked in the API response and the UI |
| `inv_reconciliation_explains_delta` | A reconciliation over the threshold names the missing dimension |
| `inv_alert_cooldown` | One condition produces one notification per cooldown per subject |
| `inv_alert_has_evidence` | Every alert links to the events that caused it |
| `inv_export_audited` | Every export writes an audit row with scope and recipient |
| `inv_hygiene_explainable` | Every score component expands to its events |

## Test plan

1. Attribution test: a member in three units; assert every ancestor total counts them once and the
   member's own total is unchanged.
2. Reconciliation test: a fixture of events plus a synthetic invoice; assert the delta, the
   unattributed bucket, and the named missing dimension when it exceeds 1%.
3. Correction test: change a price retroactively; assert restated markers, the reason link, and that
   the original rows are still recoverable.
4. Anomaly test: inject a 10× spend day for one member; assert `spend_spike` fires once, to the
   right channel, with evidence, and does not fire again inside the cooldown.
5. Forecast test: a seasonal fixture (weekday/weekend); assert the forecast error stays inside a
   stated tolerance.
6. Scheduled report test: run a schedule, assert content matches the interactive view for the same
   scope and window, and that the export is audited.
7. Playwright: manager and finance views over a 20 000-member fixture under 2 s.

## Acceptance criteria (the gate)

- [ ] Cost reconciles to a provider invoice within 1%, with the delta explained.
- [ ] Subtree totals do not double-count matrixed members, and the rule is stated in the UI.
- [ ] Every alert in the catalogue fires on a fixture, with evidence, cooldown and one-click actions.
- [ ] A scheduled report matches the interactive view exactly for the same scope and window.
- [ ] A member can see and expand every component of their hygiene score.
- [ ] Estimated token totals are marked everywhere they appear.

## Deliverables

Revision 0039; cost attribution and reconciliation; budgets with forecast; baselines and the ten
alert rules with channels; manager, finance and member views; alert catalogue and feed; scheduled
reports and exports; hygiene score; seven invariant tests; updated `PROJECT_STATE.md`.

## Do not

- Do not add an alert without an absolute floor and a cooldown. Noisy alerting is how the whole
  product gets muted.
- Do not show a number whose provenance the UI cannot explain.
- Do not recompute history silently. Restatement is visible, reasoned and audited.
- Do not build a leaderboard of employees. Compare a person to their own trailing average.
