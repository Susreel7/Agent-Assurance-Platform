# M5 — Ledger console (MVP gate)

> Paste this whole file as the only prompt of a fresh session.
> Prerequisite: F2 UI structure, M3 ingest, M4 discovery. After this, the MVP is
> demonstrable.

## Objective

An investigator picks any action from the last 30 days and reconstructs who, which agent,
which version, which capability, which argument facets, which destination, which grade —
without the product ever having stored a prompt, completion or tool argument.

## Read first

- `design/17-research-conclusions.md` §7 MVP gate sentence
- `design/15-capability-governance.md` §9
- `design/12-strategic-thesis.md` §5
- `design/04-authorization-and-dashboards.md` (every displayed number carries a grade)
- Observe detail screens (`ObserveExecutionDetailScreen`, `ObserveSessionDetailScreen`)
- Home shell from F2

## Scope

**In:**

1. **Actions list** — add `/observe/actions` as the canonical UI route backed by
   `GET /v1/agent-actions`. Keep `/observe/executions` for existing OTLP execution
   telemetry; do not pretend an execution and an action are the same record.
   Columns: time, human, agent, harness, kind, resource, outcome, **grade**. Filters in
   the URL: kind, grade, harness, member, agent.
2. **Action detail** — the reconstruction view. Identity chain vertical, capability,
   facets, decision, collector, hash-chain neighbours, session taint, links to instance
   and discovery exposures. No "show prompt" button.
3. **Coverage widget on Home** — counts by grade A–E plus an estimated dark population
   (instances that missed heartbeat, or members with IDE seats and no collector). A
   coverage figure without the denominator does not render.
4. **Session view** — timeline of actions in one `agent_sessions` row. Reuse Observe
   session timeline if it maps cleanly.
5. Copy pass: nowhere on these screens say "prevented", "blocked", or "DLP" unless the
   row's outcome is actually deny **and** grade is A or B.
6. Reuse existing `ObserveExecutionsPanel` table density, URL-filter pattern,
   `ObserveExecutionDetailScreen` layout, `RelativeTime`, `Pagination`, Nexus cards and
   the existing lazy graph component. Extract shared presentation components only when
   both old and new screens use them; do not rewrite the existing Observe graph.

**Out:** policy editor, approvals, MCP onboarding changes, cost, ClickHouse.

## Four states

Every new or touched screen: loading skeleton matching layout, empty ("install the
Claude Code hook"), error with reason + next, data with `freshness_at`.

## Invariants

| Name | Assertion |
|---|---|
| `inv_detail_has_chain` | Detail JSON/UI includes human, agent, version, instance, session, grade |
| `inv_no_prompt_field` | Action detail serializer has no prompt/completion keys |
| `inv_coverage_has_denominator` | Home coverage response includes `graded` and `estimated_total` |
| `inv_url_filters` | Changing kind filter changes the URL |
| `inv_persona_smoke` | member sees own actions; security_admin sees the org |
| `inv_execution_action_distinct` | Execution routes remain OTLP telemetry; action routes remain ledger evidence |

## Gate (this is the MVP)

- [ ] Walkthrough: from Home coverage → action list → one `shell.exec` `curl` row →
      identity chain + host facet + grade B or D.
- [ ] Playwright: member and security_admin, zero console errors on Home, list, detail,
      discovery.
- [ ] A row with `enforcement_grade=unknown` displays as ungraded/E, never as protected.
- [ ] `PROJECT_STATE.md` records MVP gate demonstrated (or lists what is still missing
      honestly).

## Do not

- Do not add a model-routing widget to Home.
- Do not pull accreditation counts back onto Home.
- Do not implement deny.
