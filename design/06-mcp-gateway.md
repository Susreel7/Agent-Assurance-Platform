# 06 · MCP gateway

Sketch: `diagrams/07-mcp-governance.excalidraw`

> **Amended 2026-09-22.** This is the strongest component in the folder and most of it
> survives unchanged — the pinned snapshots, digest comparison and quarantine below are a
> direct defence against `CVE-2025-54136` `[B-06]`, and the "unparseable argument is a deny"
> rule is the correct failure direction. Three changes:
>
> **D-08** — MCP becomes **one binding of one capability kind** (`mcp.tool`), not the
> architecture. `mcp_grants` generalises to `capability_grants`; the ordered `tools/call`
> checks generalise to the invocation sequence in
> [`15-capability-governance.md`](15-capability-governance.md) §7, which adds instance
> registration, delegation validity, session taint and credential leasing. The reference
> incident of 2026 used `Bash → curl` and would not have touched this gateway at all.
>
> **D-10** — the token vault becomes one backend of a **credential broker**. Instead of
> holding a long-lived upstream credential and injecting it, the broker issues short-lived,
> audience-bound (RFC 8707), sender-constrained (RFC 9449 / 8705) credentials scoped to one
> task. See [`14-ai-identity-and-authorization.md`](14-ai-identity-and-authorization.md) §5.
>
> **S-9** — a tool `description` is attacker-controlled text `[B-59]`. Store a digest plus
> escaped display text. Never markdown-render it to an approver, and never concatenate it
> into any prompt we generate.
>
> The closing line below — *"we generate these because they reduce accidents, we do not
> count them as controls"* — is superseded by the grading scheme in
> [`12-strategic-thesis.md`](12-strategic-thesis.md) §5. A Claude Code `PreToolUse` hook
> returning exit 2 **does** prevent the call `[B-31]`; it is Grade B, not "not a control".

MCP is where this product is differentiated, and it is also the part where the current
implementation stops at a registry. A registry lists servers. A gateway decides whether a
call happens. The difference is the whole product.

## Why enforcement must be ours

Three facts, in order:

1. The **model** chooses which tool to call and with what arguments. A tool description is an
   untrusted input, and prompt injection in a page, a ticket or a diff can steer that choice.
2. Client-side allowlists (Cursor's MCP configuration and `permissions.json`, Claude Code's
   `allowedMcpServers` and permission rules) run on a machine the developer administers. They
   are worth generating and they raise the bar. They are not attestable.
3. Whoever holds the upstream credential decides what happens. So the upstream credential
   must live in the gateway and never on the laptop.

Therefore: **the client is given a per-member gateway URL and a platform key. The gateway holds
the real credential and makes every decision.**

```
Cursor / Claude Code / agent
        │   streamable HTTP or SSE, Authorization: Bearer <platform key>
        ▼
   MCP GATEWAY  ── policy · grants · arg rules · DLP · approval · audit
        │   the real credential, from the local vault
        ▼
   Bitbucket · Jira · Nexus · Jenkins · Perforce · Postgres · internal APIs
```

## Onboarding in three screens

If this takes an afternoon and a support call, the customer concludes they do not need us. The
target is under three minutes for a server somebody has already deployed.

**Screen 1 · Declare.** Paste a URL, or a command for stdio. Pick transport (`stdio`,
`sse`, `http_stream`), owner org unit, environments, and the credential (from the vault, or
created inline). Optional: import from an existing `mcp.json` — most customers already have
one, and reading it is the fastest possible onboarding.

**Screen 2 · Discover.** A worker connects, performs `initialize`, then `tools/list`,
`resources/list`, `prompts/list`, records latency and protocol version, and stores an
immutable **snapshot** with a `capability_digest` over the normalised capability list. Failures
are reported with the actual protocol error, not "discovery failed".

**Screen 3 · Classify and publish.** For each tool, the server's own `readOnlyHint` /
`destructiveHint` are shown but kept in separate columns from our verified findings — a server
asserting it is read-only is a claim, not a finding. Templates pre-fill by name pattern
(`*_delete_*`, `execute_sql`, `create_pull_request`), and a human confirms:

| Field | Values |
|---|---|
| `verified_risk` | low · medium · high · critical |
| `verified_write` | does it change state |
| `verified_irreversible` | can it be undone |
| `verified_data_classes` | what it can read or emit |
| `arg_rules` | argument-level constraints (below) |

Then approve the snapshot, grant subjects, and the console emits the exact client config plus
a preflight that proves `tools/list` returns a non-zero count for a real user.

## Grants, and why the registry itself is filtered

```
mcp_grants: (server, subject_kind, subject_id, capability_name?, environments[],
             permission ∈ {list, invoke, invoke_write}, pinned_snapshot, requires_approval,
             rate_limit_per_min, expires_at)
```

Subjects can be a **member**, an **org unit** (inherited down the subtree — this is how a DL of
200 people is granted in one action), a **directory group** (so the customer's own group
management drives access), a **service identity** (one platform key), or an **agent**.

The visibility rule for the registry:

> A caller sees only servers they hold a live grant for. Someone with no grant cannot tell the
> server exists. Seeing the whole estate is a privilege (`registry:read_all`) held by platform
> and security admins.

This is what the "only AAP worker key, no grant" case means concretely: a valid platform key
proves *who* is calling; it confers nothing on its own. No grant → `tools/list` returns an
empty list, the registry hides the server, and `tools/call` returns
`403 no_grant_for_capability` naming the server, the tool and who can grant it.

Effective access for a subject is resolved by union, most specific first, with deny winning:
direct member grant, then group, then org unit walking up the tree, then agent, then service
identity. The console shows the resolved answer and **which grant produced it**, because
"why can Ravi call this" is the question an auditor always asks.

## tools/list — filtered, because absence is the best denial

Return only the capabilities the caller can invoke, from the snapshot pinned by their grant. A
tool the caller cannot use should not appear, so the model never proposes it and the developer
never sees an inexplicable refusal mid-task.

`tools/list` never becomes an implicit allowlist for `tools/call`. A patched or malicious
client that invents a tool name gains nothing: every call is re-checked from scratch.

## tools/call — the ordered checks, all failing closed

1. Platform key valid, not revoked, generation current, scope includes `mcp:invoke`.
2. Server `approved`, not `quarantined`, and the request environment is in its environments.
3. A live grant exists for this subject and this capability, with the right permission level
   (`invoke_write` required for `verified_write`).
4. The approved snapshot equals the grant's pinned snapshot — no substitution after approval.
5. Arguments validate against the snapshot's `input_schema`.
6. `arg_rules` pass (below).
7. Input inspection: no secret or PII leaves in the arguments.
8. Rate and concurrency budget for this subject.
9. `verified_write` or `verified_irreversible` → a valid approval token is required.
10. Dispatch, then **scan the response** before returning it to the model.

Everything before dispatch is in-memory against the cached bundle. Budget: p95 under 5 ms of
added decision time; the upstream call dominates.

### Argument-level rules

This is how "block the tool" becomes "block *this* use of the tool", which is what customers
actually need — nobody wants `execute_sql` banned outright.

```yaml
# mcp_capabilities.arg_rules
execute_sql:
  sql:
    parse: sql                       # real parse, not a regex
    allow_verbs: [SELECT, EXPLAIN]
    deny_verbs: [DELETE, DROP, TRUNCATE, ALTER, GRANT]
    verbs_requiring_approval: [INSERT, UPDATE]
    deny_tables: ["customers", "payments", "*_pii"]
    max_rows: 1000
delete_repository:
  deny: always                       # not a policy question
create_pull_request:
  repository:
    deny_patterns: ["payments-*", "*-prod"]
    require_approval_patterns: ["platform-*"]
read_file:
  path:
    allow_roots: ["${workspace}"]
    deny_globs: ["**/.env*", "**/id_rsa", "**/*.pem", "**/secrets/**"]
deploy:
  environment:
    values_requiring_approval: [production]
```

Rule kinds supported: enum, regex allow/deny, glob for paths, numeric bound, SQL verb and
table extraction via a parser, JSONPath selection for nested arguments, and a blast-radius cap
(row count, file count, matched resources). Anything a rule cannot parse is treated as a
match against the deny side — failing open on an unparseable argument is how these systems
get bypassed.

## Drift, rug-pulls and the kill switch

Rediscovery runs on a schedule and on demand, and compares digests.

| Situation | Behaviour |
|---|---|
| New tool appears | Invisible to callers, raises a review item. A new capability is never live because it showed up. |
| Tool definition changed under an approved name | Server moves to `in_review`; existing grants keep working against the **pinned** snapshot, so a rug-pull cannot take effect silently |
| Tool removed upstream | Grant flagged, not deleted; calls return `410 capability_withdrawn` with the date |
| Server unreachable | Health degrades, alert to the owner org unit, grants untouched |
| Malicious or compromised server | **Quarantine**: effective within one cache TTL (≤ 5 s) for every caller and environment |

Quarantine and release are separate permissions. Both record actor and reason. A per-subject
revoke is instant and audited in the same way.

## Transports, in practice

| Transport | Notes |
|---|---|
| `http_stream` (streamable HTTP) | Preferred. Stateless-friendly, works through load balancers, easiest to authenticate per call |
| `sse` | Supported; sticky sessions needed, so it constrains scaling |
| `stdio` | The common case for locally distributed servers (the shipped example is `examples/mcp/demo_server.py`). Runs **inside the data plane** in a pooled, resource-capped sandbox — never on the developer's machine, or we lose the credential boundary |

For stdio: one process pool per (server, environment), with a concurrency cap, memory and CPU
limits, no network egress except an explicit allowlist, a clean environment built only from
`env_refs`, and a hard kill on protocol timeout. A misbehaving MCP server must not be able to
take the gateway down or read another server's credential.

## What every call leaves behind

`member · service identity · agent · session · server · tool · argument digest (not the
arguments) · decision · reason code · risk · approval id · latency · bytes · upstream status`,
plus graph edges `member → agent → server → tool → resource`.

Arguments themselves go to the customer-side payload store under their digest, with the
account's payload TTL, and are readable only through an audited reveal. The event keeps the
digest so "the same query ran 4 000 times" is answerable without storing it 4 000 times.

## The Cursor and Claude Code configs we generate

Per member, per environment, with the platform key already in place:

```jsonc
// Cursor — .cursor/mcp.json  (or the managed team configuration)
{ "mcpServers": {
    "nexus": {
      "url": "https://mcp-gw.internal.acme.com/s/nexus/mcp",
      "headers": { "Authorization": "Bearer ${AAP_PLATFORM_KEY}" }
    }
}}
```

```json
// Claude Code — managed settings, delivered by MDM
{ "allowedMcpServers": ["https://mcp-gw.internal.acme.com/s/*"],
  "allowManagedMcpServersOnly": true,
  "permissions": { "deny": ["Read(./.env)", "Read(./**/*.pem)"] },
  "allowManagedPermissionRulesOnly": true,
  "disableBypassPermissionsMode": "disable" }
```

We generate these because they reduce accidents. We do not count them as controls. The control
is that the gateway URL is the only path to a working credential.
