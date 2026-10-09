# Phase 5 — MCP gateway: onboarding, grants, tool blocking

> **HISTORICAL — DO NOT EXECUTE.** MCP remains valuable but is one capability binding,
> not the architecture or MVP lead. Existing MCP tables and UI must be generalized through
> [`v1-mcp-and-broker.md`](v1-mcp-and-broker.md), not rebuilt.

> Paste this whole file as the only prompt of a fresh session.

## Objective

Turn the MCP registry into a gateway. Three screens to onboard a server, one place that decides
whether a tool call happens, argument-level rules so `execute_sql` can be allowed for `SELECT`
and blocked for `DELETE`, a registry that hides servers you have no grant for, and a quarantine
that takes effect in seconds.

## Prerequisite

Phase 2's gate (roles and visibility). Phase 3 is not required, but if it is done the platform-key
and bundle machinery is reused rather than rebuilt.

## Read first

- `design/06-mcp-gateway.md` — all of it
- `design/03-data-model.md` §D
- `design/diagrams/07-mcp-governance.excalidraw`

## Scope

**In:** the three-screen onboarding with `mcp.json` import; a discovery worker for all three
transports; immutable snapshots with capability digests; classification with declared-vs-verified
separation; `arg_rules` evaluation; grant-filtered `tools/list` and the registry; the ordered
`tools/call` checks; approvals for write and irreversible tools; drift detection and rug-pull
protection; quarantine and release; the stdio sandbox; generated client configs and preflight.

**Out:** DLP depth (P6 — this phase calls the existing scanner through a stable interface),
ClickHouse (P7 — emit the final envelope to the queue).

## Database (revision 0030, 0037)

```
0030  mcp_servers: transport enum (stdio|sse|http_stream), trust_tier, owner_org_unit_id,
                   environments[], state machine incl. quarantined, health, command/args/env_refs
      mcp_capabilities: declared_* kept separate from verified_*, arg_rules jsonb
      mcp_grants: pinned_snapshot_id, permission (list|invoke|invoke_write), rate_limit_per_min,
                  subject_kind widened to member|org_unit|directory_group|service_identity|agent
      backfill: pin every live grant to the currently approved snapshot
0037  mcp_approvals view over approvals; mcp_discovery_runs (transport, protocol version,
      latency, error); mcp_capability_usage kept for compatibility until P7
```

## Onboarding — the commercial requirement

Under three minutes for an already-deployed server, and a support call is a defect.

- **Screen 1 Declare**: URL or command; transport; owner org unit; environments; credential from
  the vault or created inline. **Import from `mcp.json`** — most customers already have one, and
  reading it is the single biggest onboarding win available.
- **Screen 2 Discover**: `initialize` → `tools/list` → `resources/list` → `prompts/list`; record
  protocol version, latency, and the real error text on failure; store an immutable snapshot with
  `capability_digest` over the normalised capability list.
- **Screen 3 Classify and publish**: per tool, show the server's own `readOnlyHint` /
  `destructiveHint` in a clearly separate column from our findings; templates pre-fill by name
  pattern (`*delete*`, `execute_sql`, `create_pull_request`, `deploy`); a human confirms
  `verified_risk`, `verified_write`, `verified_irreversible`, `verified_data_classes`,
  `arg_rules`. Then approve the snapshot, grant subjects, emit the client config, run preflight.

## The enforcement path

`tools/list` returns only capabilities the caller holds a grant for, from the snapshot pinned by
that grant. A tool the caller cannot use does not appear.

`tools/call` runs the ten ordered checks from `design/06`, all failing closed, all before dispatch
except the response scan. Every failure returns a specific reason code:
`no_grant_for_capability`, `server_quarantined`, `snapshot_mismatch`, `schema_invalid`,
`arg_rule_denied`, `secret_in_arguments`, `rate_limited`, `approval_required`,
`capability_withdrawn`.

Budget: p95 under 5 ms of added decision time, measured with the upstream stubbed.

### Argument rules — the engine

Implement as a small, testable evaluator over a declarative document. Rule kinds:

| Kind | Example |
|---|---|
| enum | `environment.values_requiring_approval: [production]` |
| regex allow/deny | `repository.deny_patterns: ["payments-*", "*-prod"]` |
| path glob with roots | `path.allow_roots: ["${workspace}"]`, `deny_globs: ["**/.env*", "**/*.pem"]` |
| numeric bound | `max_rows: 1000` |
| SQL analysis | real parse; `allow_verbs`, `deny_verbs`, `verbs_requiring_approval`, `deny_tables` |
| JSONPath selection | rules on nested arguments |
| blast radius | matched resource count cap |

Two non-negotiables: an argument a rule cannot parse is treated as matching the **deny** side, and
every rule evaluation is recorded in the decision so "why was I blocked" is answerable from the
event alone.

## The stdio sandbox

The local example in `examples/mcp` is a stdio server, so this is real work, not a footnote.
Run stdio servers **inside the data plane**, never on the developer's machine, or the credential
boundary is lost.

- One process pool per `(server, environment)`; concurrency cap; idle reaping.
- Memory and CPU limits; hard kill on protocol timeout; crash-loop backoff with an alert.
- Environment built **only** from `env_refs`; no inherited environment, no ambient credentials.
- No network egress except an explicit allowlist per server.
- One server must not be able to read another's credential or starve the gateway.

## Grants and registry visibility

Subjects: member, **org unit** (inherited down the subtree — how 200 people get access in one
action), directory group, service identity, agent. Resolution: union, most specific first, deny
wins. `/v1/mcp/effective?subject=` explains which grant produced the answer.

The registry list endpoint joins against effective grants. `registry:read_all` (platform and
security admins) sees everything. Everyone else sees only what they can use — a member with a
valid platform key and no grant sees an empty registry and gets
`403 no_grant_for_capability` naming who can grant it.

## Backend surface

```
POST  /v1/mcp/servers                      declare (or import from mcp.json)
POST  /v1/mcp/servers/{id}/discover        run discovery now
GET   /v1/mcp/servers/{id}/snapshots       history with digests
POST  /v1/mcp/snapshots/{id}/approve       approve; pins grants forward
PATCH /v1/mcp/capabilities/{id}            classification + arg_rules
POST  /v1/mcp/grants  · DELETE /{id}       grant / revoke, reason required
GET   /v1/mcp/effective?subject=           resolved access, with the causing grant
POST  /v1/mcp/servers/{id}/quarantine      reason required
POST  /v1/mcp/servers/{id}/release         separate permission
GET   /v1/mcp/servers/{id}/client-config   Cursor / Claude / generic JSON
POST  /v1/mcp/preflight                    per member + environment
# data plane
ALL   /s/{server_slug}/mcp                 streamable HTTP endpoint
GET   /s/{server_slug}/sse                 SSE endpoint
```

## Frontend

- **Registry**: cards or table, grant-filtered, with trust tier, transport, health, tool count,
  write-tool count, drift badge, and "connect" actions per client.
- **Server detail**: overview · tools (with declared vs verified columns, risk, arg rules) ·
  access (grants with the causing rule, inline revoke) · client (generated config + preflight) ·
  activity (recent calls, decisions, denials).
- **Onboarding wizard**: the three screens, with discovery errors shown verbatim.
- **Review queue**: new and changed capabilities awaiting classification, with the diff.
- **Quarantine**: one action, a required reason, and a visible banner everywhere the server appears.

## Invariants to add

| Name | Assertion |
|---|---|
| `inv_list_filtered_by_grant` | `tools/list` returns nothing for a key with no grant |
| `inv_call_rechecks_grant` | A fabricated tool name is denied even if it exists on the server |
| `inv_snapshot_pinned` | A changed capability does not take effect under an approved name |
| `inv_new_tool_invisible` | A newly discovered tool is invisible until classified and approved |
| `inv_unparseable_arg_denied` | An argument a rule cannot parse is denied, not allowed |
| `inv_quarantine_within_ttl` | Quarantine blocks every caller within 5 s |
| `inv_stdio_isolated` | A stdio server cannot read another server's environment or credential |
| `inv_registry_hidden` | A server the caller has no grant for is absent from the registry response |

## Test plan

1. Contract tests against a reference MCP server on all three transports, including protocol
   version negotiation and a deliberately malformed response.
2. The ten-check sequence: one test per check, each asserting the specific reason code and that no
   upstream call happened.
3. `arg_rules` suite: SQL verbs and tables, path globs including traversal attempts, repository
   patterns, numeric bounds, nested JSONPath, blast radius, and unparseable input.
4. Rug-pull test: approve a snapshot, change the tool upstream, assert calls still run against the
   pinned definition and the server moves to `in_review`.
5. Sandbox test: a stdio server that forks, allocates, hangs and tries to open a socket — assert
   containment, kill, backoff and alert.
6. Grant inheritance: grant an org unit, assert all members of that unit can call; revoke, assert all are
   denied within one TTL.
7. Real-client test: Cursor and Claude Code both list and call tools through the gateway, and
   `tools/list` returns a **non-zero** count for a granted member — with the zero-tools case
   producing a named reason in preflight. (This is the exact failure reported earlier; it must
   have a dedicated regression test.)

## Acceptance criteria (the gate)

- [ ] Onboarding a running server takes under three minutes, including preflight, with no support call.
- [ ] An unprivileged member can neither see nor call a server; the reason names who can grant access.
- [ ] `tools/list` is grant-filtered and `tools/call` re-validates independently.
- [ ] Argument rules allow `SELECT` and block `DELETE` on the same tool, with the decision explained.
- [ ] A rug-pulled tool does not take effect; the server lands in review.
- [ ] Quarantine is effective within 5 s for every caller and environment.
- [ ] stdio servers run sandboxed in the data plane, never on a developer machine.
- [ ] Preflight explains a zero-tool result rather than leaving the user to guess.

## Deliverables

Revisions 0030, 0037; discovery worker (three transports); snapshot and digest handling;
classification with templates; the `arg_rules` evaluator; the ten-check enforcement path; the
stdio sandbox; grants with inheritance and explanation; quarantine/release; client-config
generation; preflight; registry, detail, wizard and review screens; eight invariant tests;
updated `PROJECT_STATE.md`.

## Do not

- Do not trust a server's own `readOnlyHint` for any decision. Record it, show it, never act on it.
- Do not let the client's `tools/list` result be an allowlist for `tools/call`.
- Do not run stdio servers on developer machines as a shortcut; that gives away the credential
  boundary, which is the product.
- Do not delete a grant when a capability disappears — flag it, so the history survives.
