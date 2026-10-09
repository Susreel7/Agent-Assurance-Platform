# 15 · Capability governance

> Written 2026-09-22. Sources in [`18-bibliography.md`](18-bibliography.md), cited as `[B-nn]`.
> Tags: **FACT** · **SOURCE-BACKED** · **DESIGN DECISION** · **INFERENCE** · **OPEN**.
>
> This document generalises `design/06` (MCP gateway). MCP becomes **one binding of one
> capability kind**, not the architecture. It also defines the canonical action event, which
> `design/08` consumes.

---

## 1. Why MCP cannot be the model

**FACT** The reference incident (threat model AP-1) used `Bash → curl → GraphQL`. No MCP.
**FACT** `[B-07]` Clinejection used a CI agent's npm token. No MCP. **FACT** `[B-10]` The
Claude Code memory compromise used an npm postinstall script writing to a file. No MCP.

**INFERENCE:** an architecture whose enforcement points are "model requests" and "MCP calls"
is an architecture that is absent from the majority of documented 2026 agent incidents. This
is not an argument against the MCP gateway — that component is well designed and should be
kept nearly as specified. It is an argument that MCP is **one row in a table** that the
current design treats as the whole table.

Secondary argument: **SOURCE-BACKED** `[B-38]` A2A is now Linux-Foundation-hosted with 150+
participating organisations and a v1.0 spec, and delegates authentication to ordinary
OAuth/OIDC/mTLS. Protocol plurality is the steady state, not a transition.

---

## 2. The chain

```
CAPABILITY DEFINITION   what exists, typed and versioned
        ↓
CAPABILITY RISK         verified classification — ours, not the supplier's claim
        ↓
CAPABILITY GRANT        who may invoke it, where, under what conditions
        ↓
CAPABILITY INVOCATION   one attempt, one decision, one enforcement grade
        ↓
CAPABILITY EVIDENCE     content-free, tamper-evident, reconstructable
```

Everything in §3 flows through this chain. One policy model, one grant model, one evidence
model, one screen — regardless of whether the thing invoked was an MCP tool, a shell command,
an HTTP request or a delegated sub-agent.

---

## 3. Capability kinds

The canonical registry. `NEW` marks what does not exist in `design/01`–`11`.

| Kind | Resource | Best grade | How we see it | New? |
|---|---|---|---|---|
| `model.invoke` | model alias, provider endpoint | A / D | Gateway, or vendor usage API | |
| `mcp.tool` | server + tool + args | A | MCP gateway (`06`) | |
| `shell.exec` | command, argv, cwd | **B** | Claude Code `PreToolUse` `Bash` `[B-31]`; Cursor `beforeShellExecution` `[B-33]`; Codex `tool_decision` `[B-76]` | **NEW** |
| `net.http` | method, host, path | **B** → A | Hook interception; sandbox allowlist `[B-31]`; brokered egress proxy | **NEW** |
| `fs.read` | path | **B** | Hook + permission rules (`Read(./secrets/**)`) `[B-77]` | **NEW** |
| `fs.write` | path | **B** | Hook; Claude `PostToolUse`; Cursor `afterFileEdit` | **NEW** |
| `vcs.write` | repo, branch, operation | A | Brokered token; server-side hook; audit log | **NEW** |
| `db.query` | connection, verbs, tables | A | MCP tool, or brokered credential | partial |
| `cloud.api` | provider, service, operation, ARN | A | Brokered short-lived credential | **NEW** |
| `agent.delegate` | child agent, granted set | A | Delegation record (`14` §4) | **NEW** |
| `memory.write` | store, scope, key | **B** | Hook; integrity baseline over memory/rules files | **NEW** |
| `retrieval.query` | index, scope | A / B | Retrieval proxy or hook | **NEW** |
| `package.publish` | registry, package | A | Brokered credential; CI policy | **NEW** |
| `browser.act` | URL, DOM action | **E** | Not addressable in 2026 — say so | **NEW** |

**DESIGN DECISION:** `browser.act` is listed with grade **E** deliberately. Computer-use and
browser agents are real and we cannot govern them. Naming the row and admitting the grade is
better than an inventory that silently omits the thing the customer is most worried about.

**INFERENCE:** `shell.exec` and `net.http` alone convert the product from "observed the wrong
layer" to "observed the layer where the incidents happen". They are the highest-value two rows
in this table and they are both Grade B — which is precisely why §5 of the threat model and
the grading scheme in `12` exist.

---

## 4. Capability definition

```
capabilities(
  capability_id, account_id, kind, binding_ref,
  name, version, capability_digest,
  -- supplier's claim, quarantined from our finding
  declared_read_only, declared_destructive, declared_description_digest,
  -- our verified finding
  verified_risk        ∈ low|medium|high|critical,
  verified_write       bool,
  verified_irreversible bool,
  verified_data_classes[],
  arg_schema, arg_rules,
  classified_by, classified_at, classification_basis ∈ template|human|inherited
)
```

**Two properties carried over from `06` because they are correct and rare:**

1. **Supplier claims are stored in different columns from our findings.** A server asserting
   `readOnlyHint` is evidence about the server, not about the tool. **FACT** `[B-06]`
   `CVE-2025-54136` is exactly the case where trusting the declaration was the vulnerability.
2. **An unparseable argument is a deny, not an allow.** Failing open on something we could not
   parse is how these systems are bypassed.

**Extension:** a tool `description` is attacker-controlled text `[B-59]`. It is stored as a
digest plus escaped display text, never rendered as markdown to an approver, and never
concatenated into any prompt we generate.

---

## 5. Capability risk classification

Defaults by kind and pattern, always human-confirmable, never silently promoted:

| Pattern | Default | Rationale |
|---|---|---|
| `*_delete_*`, `drop_*`, `truncate_*`, `volume*delete*` | critical, irreversible | AP-1 |
| `execute_sql`, `run_query` | high, arg-rule mandatory | Verb-dependent |
| `shell.exec` with `curl`/`wget`/`nc`/`ssh` | high | Egress channel |
| `shell.exec` matching credential paths | high | AP-1 harvest step |
| `net.http` to a non-allowlisted host | high | Exfiltration channel |
| `memory.write` | high | AP-4 persistence |
| `package.publish`, `deploy` to prod | critical | Clinejection `[B-07]` |
| `fs.read` of `**/.env*`, `**/*.pem`, `**/id_rsa`, `**/.aws/**` | high | AP-1 harvest step |
| `read_*`, `get_*`, `list_*` | low | Bulk of traffic |

**DESIGN DECISION:** classification is versioned and auditable. "Who decided `execute_sql` was
medium?" must be answerable with a name and a date.

---

## 6. Grants — one model for every kind

`design/06`'s `mcp_grants` generalises with the schema essentially unchanged:

```
capability_grants(
  grant_id, account_id, capability_selector,      -- kind + pattern, or explicit id
  subject_kind ∈ member|org_unit|group|service_identity|agent|agent_version,
  subject_id, environments[],
  permission   ∈ list|invoke|invoke_write,
  pinned_capability_digest,                        -- rug-pull defence, all kinds
  requires_approval, rate_limit_per_min,
  max_taint    ∈ clean|tainted|tainted_with_secrets,   -- NEW
  expires_at, granted_by, reason
)
```

Two additions:

- **`capability_selector`** allows `shell.exec` grants like `deny curl to *` without
  enumerating commands — necessary because shell argv space is unbounded.
- **`max_taint`** binds a grant to session cleanliness, implementing threat model §7. This is
  the trifecta-breaking control expressed as a grant condition rather than a special case.

Resolution is unchanged from `06` and was already right: union, most specific first, deny
wins, and the console shows **which grant produced the answer**.

**Visibility rule, generalised:** a caller sees only capabilities they hold a live grant for.
Absence is the best denial. `tools/list` is never an implicit allowlist for `tools/call`.

---

## 7. Invocation — the ordered checks

Generalised from `06` §`tools/call`, with the new steps marked:

```
 1. Caller authenticated; key/SVID valid, not revoked, generation current
 2. Agent instance registered, version approved, not quarantined            [NEW]
 3. Delegation chain valid; depth ≤ max; authority attenuates               [NEW]
 4. Capability approved, not quarantined; environment matches
 5. Live grant for this subject + capability at the right permission level
 6. Approved digest == grant's pinned digest
 7. Session taint ≤ grant.max_taint                                         [NEW]
 8. Arguments validate against schema
 9. Argument rules pass (unparseable ⇒ deny)
10. Inspection of arguments for secrets/PII (mediated paths only)
11. Rate and concurrency budget
12. write/irreversible ⇒ valid, single-use, unexpired approval token
13. Credential lease issued: audience-bound, scoped, short TTL              [NEW]
14. Dispatch
15. Scan response before returning it to the model
16. Emit evidence with enforcement_grade                                    [NEW]
```

Steps 1–13 are in-memory against the cached bundle. The existing budget — **p95 under 5 ms of
added decision time** — stands; steps 2, 3, 7 are hash lookups and step 13 is the only one
that can involve a network call, which is why leases are cached per (instance, binding) for
their lifetime.

---

## 8. Bindings — what enforcement actually looks like

| Binding | Mechanism | Grade | Caveat |
|---|---|---|---|
| MCP remote | Our gateway URL is the only allowlisted one `[B-42][B-36]` | **A** | Requires vendor allowlist to be set and verified |
| MCP stdio | Runs in our data plane sandbox, never on the laptop (`06`) | **A** | Loses locality; some servers assume local FS |
| Claude Code shell/fs/net | `PreToolUse` hook; exit 2 or `permissionDecision: "deny"` blocks `[B-31]` | **B** | Local admin can remove; hooks run unsandboxed |
| Cursor shell/MCP | `beforeShellExecution` / `beforeMCPExecution` with `failClosed: true` `[B-33]` | **B** | **Default is fail-open** — must be set, and absence must alarm |
| Codex CLI | `tool_decision` OTEL events; sandbox modes `[B-76]` | B/D | No vendor MDM product documented |
| Copilot IDE | Enterprise policies + `managed-settings.json` MCP intersection `[B-36]` | **C** | Content exclusion **not supported in agent mode** `[B-35]` |
| Copilot cloud agent | Network firewall + allowlist `[B-78]` | **C** | **Disabled on self-hosted runners** |
| CI agents | Broker + runner egress + our wrapper | **A** | Customer-controlled infrastructure — best surface we have |
| In-house (LangGraph, SDK) | SDK middleware calling our PDP | **A** | Requires code change; highest fidelity |
| A2A | Agent Card + OAuth at our gateway `[B-38]` | **A** | Roadmap |
| Browser/computer use | — | **E** | Stated, not solved |

**DESIGN DECISION — the coverage ledger.** For every enrolled endpoint we track which bindings
are *installed*, *configured*, *verified* and *reporting*. A binding that stops reporting is a
**coverage incident** with the same visual weight as a policy violation. **INFERENCE:** the
most likely real-world failure of this product is not a bypassed policy; it is a hook that
quietly stopped running three weeks ago and nobody noticed.

---

## 9. The canonical action event

**DESIGN DECISION:** one envelope for every capability kind. This supersedes the separate
model-request and MCP-call event shapes in `design/08`. Version it from day one; it is the
hardest thing to change later.

```jsonc
{
  "schema": "aap.action.v1",
  "event_id": "uuid-v7",                    // time-ordered
  "occurred_at": "RFC3339 with offset",
  "received_at": "RFC3339",                 // clock-skew forensics
  "account_id": "...", "environment": "prod",

  "subject": {
    "human_member_id": "...",
    "root_human_basis": "triggered_by",
    "agent_id": "...", "agent_version_id": "...", "composition_digest": "sha256:...",
    "instance_id": "...", "session_id": "...", "task_id": "...",
    "delegation_depth": 0, "parent_instance_id": null,
    "service_identity_id": null,
    "attestation": "config_signed"
  },

  "capability": {
    "kind": "shell.exec", "id": "...", "version": "...",
    "digest": "sha256:...",
    "risk_class": "high", "write": true, "irreversible": false
  },

  "resource": {
    "kind": "host", "identifier": "backboard.railway.app",
    "owner_org_unit_id": "...", "data_classes": ["internal"]
  },

  "arguments": {
    "digest": "sha256:...",                 // never the content
    "facets": { "binary": "curl", "method": "POST", "host": "...",
                "sql_verbs": [], "paths": [] },
    "payload_ref": "cust://...",            // customer-side only, audited reveal
    "truncated": false
  },

  "decision": {
    "outcome": "deny",
    "reason_code": "egress_host_not_allowlisted",
    "enforcement_grade": "B",               // A|B|C|D|E — mandatory
    "policy_id": "...", "policy_version": 47,
    "matched_grant_id": "...",
    "approval_id": null,
    "risk_signals": ["session_tainted", "credential_path_read_earlier_in_session"],
    "latency_added_ms": 3
  },

  "credential": {
    "lease_id": "...", "binding_id": "...",
    "audience": "https://backboard.railway.app",
    "scope": ["volume:read"], "ttl_seconds": 300, "proof_method": "dpop"
  },

  "context": {
    "session_taint": "tainted",
    "context_sources": ["github_issue:public", "repo:internal"],
    "device_posture": "managed", "network_posture": "corporate",
    "harness": "cursor", "harness_version": "..."
  },

  "provenance": {
    "collector_id": "...", "collector_version": "...",
    "bundle_version": 47, "bundle_age_seconds": 12,
    "prev_event_hash": "sha256:...",        // hash chain, per collector
    "signature": "..."                       // signed at the collector
  },

  "outcome": {
    "upstream_status": null, "bytes_in": 0, "bytes_out": 0,
    "downstream_mutation_ref": null          // commit SHA, PR, ticket, resource ARN
  }
}
```

**What this envelope buys, that the current one does not:**

- **Reconstruct without payloads.** Every question in brief §15 — who, which agent, which
  version, which prompt digest, which context, which tools, which arguments, which data
  classes, which policy version, which approval, which credential, which destination, which
  downstream mutation — is answerable from fields above, with zero customer content.
- **`enforcement_grade` is mandatory.** No event can claim protection it did not provide.
- **`prev_event_hash` + `signature`** make suppression detectable (threat model AP-9). A gap in
  the chain is visible; a deleted row is not.
- **`downstream_mutation_ref`** is the SDLC join — the field that lets "this action" become
  "this commit, in this release" and that no competitor in `16` currently holds.

**DESIGN DECISION on payloads:** `arguments.digest` and `facets` travel to the control plane.
`payload_ref` resolves **only** inside the customer boundary, through an audited, time-boxed,
dual-control reveal. This preserves the `AGENTS.md` rule and makes it enforceable by schema
rather than by discipline.

---

## 10. Open questions

| ID | Question | Recommendation |
|---|---|---|
| Q-H | Do we ship an SDK middleware for in-house agents in MVP, or only harness bindings? | Harness bindings first — in-house agents are a smaller population and need a code change |
| Q-I | Argument facets for `shell.exec`: how deep do we parse argv before it becomes its own product? | Binary + flags + hosts + paths. No shell grammar. Unparseable ⇒ high risk + deny on write |
| Q-J | Is `browser.act` worth an inventory row if it is permanently grade E? | Yes — an honest gap beats a silent one |
| Q-K | Should `retrieval.query` be MVP? It is where cross-tenant leakage lives, but only for customers with RAG | Defer to V2 unless a design partner has RAG in production |
