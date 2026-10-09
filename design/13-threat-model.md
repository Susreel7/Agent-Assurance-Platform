# 13 · Threat model

> Written 2026-09-22. Sources in [`18-bibliography.md`](18-bibliography.md), cited as `[B-nn]`.
> Tags: **FACT** · **SOURCE-BACKED** · **DESIGN DECISION** · **INFERENCE** · **OPEN**.
>
> This is a threat model of **the enterprise AI estate we are asked to protect** *and* of **our
> own product**. Both are required: a security control that has not modelled its own
> compromise is not a security control.

Frameworks used, so findings map to something a customer's auditor already recognises:
OWASP Top 10 for Agentic Applications 2026 (`ASI01`–`ASI10`) `[B-52]`, OWASP Agentic AI Threats
and Mitigations (`T1`–`T15`) `[B-53]`, OWASP Top 10 for LLM Applications 2026 (`LLM01`–`LLM10`)
`[B-54]`, CSA MAESTRO seven-layer model `[B-55]`, MITRE ATLAS `[B-56]`, NIST AI 600-1 `[B-57]`
and NIST AI 100-2e2025 `[B-58]`.

---

## 1. Actors

| ID | Actor | Motivation | Capability assumed |
|---|---|---|---|
| A-1 | Careless developer | Speed | Full admin of own laptop; can install anything |
| A-2 | Malicious insider | Exfiltration, sabotage | As A-1, plus legitimate credentials and knowledge of what is valuable |
| A-3 | External attacker via content | Anything | Can place text where an agent will read it: issue, PR, README, web page, dependency, MCP tool description |
| A-4 | Malicious/compromised MCP or tool supplier | Supply chain | Controls a server the enterprise approved |
| A-5 | Compromised agent runtime | Persistence | Has written to agent memory, hooks or settings on a developer machine |
| A-6 | Malicious vendor operator (ours) | Insider | Control-plane database and signing key access |
| A-7 | Malicious customer operator | Privilege abuse | Account-owner role in the customer tenant |
| A-8 | Nation-state / advanced | Full | Assume defeats Grade B and C entirely; only Grade A and evidence survive |

**DESIGN DECISION:** A-1 and A-3 are the *design* adversaries — the ones the product must beat
at reasonable cost. A-2 and A-4 we materially raise the cost for. A-8 we explicitly do not
claim to stop; we claim to *record*.

---

## 2. Trust boundaries

```
 ┌─ TB-1 ── developer endpoint (user-administered) ──────────────────────┐
 │  IDE/CLI · agent harness · hooks · shell · filesystem · local MCP     │
 │  TRUST: none for enforcement. Grade B ceiling.                        │
 └────────┬──────────────────────────────────────────────────────────────┘
          │ TB-2  egress (corporate network / SWG / MDM — customer-owned)
 ┌────────▼───────────────┐   ┌──────────────────────────────────────────┐
 │ TB-3 vendor clouds     │   │ TB-4 our DATA PLANE (customer boundary)  │
 │ Cursor · Anthropic ·   │   │ capability gateway · credential broker · │
 │ GitHub · OpenAI        │   │ inspector · payload store · collector    │
 │ TRUST: contractual     │   │ TRUST: holds credentials + payloads      │
 │ only. Cursor sees      │   └───────────────┬──────────────────────────┘
 │ prompts before we do.  │                   │ TB-5 signed bundle down,
 └────────────────────────┘                   │      signed evidence up
                                   ┌──────────▼──────────────────────────┐
                                   │ TB-6 our CONTROL PLANE              │
                                   │ metadata only · never on request path│
                                   └──────────┬──────────────────────────┘
                                              │ TB-7
                                   ┌──────────▼──────────────────────────┐
                                   │ TB-8 downstream systems: VCS, cloud,│
                                   │ DB, ticketing, internal APIs        │
                                   └─────────────────────────────────────┘
```

**Change from `design/01`:** TB-3 is new and non-negotiable. The old model had two planes.
There is a third party in the path for Cursor and Copilot, and it is upstream of us
`[B-41]`. Any claim of the form "payloads never leave the customer boundary" must be scoped
per client. See [`12-strategic-thesis.md`](12-strategic-thesis.md) §6.

---

## 3. Attack surface inventory

| Surface | Reachable by | Current design covers? |
|---|---|---|
| Model request body | A-1, A-2, A-3 | Yes (`05`) |
| MCP `tools/list` / `tools/call` | A-1…A-5 | Yes (`06`) |
| **Agent shell (`Bash`, terminal, `run_command`)** | A-1, A-2, A-3, A-5 | **No** |
| **Agent outbound HTTP (`curl`, `WebFetch`, SDK)** | same | **No** |
| **Agent filesystem read/write** | same | **No** |
| **Credentials on the developer filesystem** | A-1…A-5 | **No** |
| **Agent memory / `MEMORY.md` / rules files** | A-3, A-5 | **No** |
| **Agent settings and hooks** | A-1, A-5 | **No** |
| Sub-agent / A2A delegation | A-3, A-5 | **No** |
| Retrieval / vector store / RAG context | A-2, A-3 | Partial (`07`) |
| Our policy bundle distribution | A-6, A-8 | Partial (`01`) |
| Our control-plane API and console | A-6, A-7 | Partial (`04`) |
| Our own dependencies and images | A-4, A-8 | **No** |

**Seven of thirteen surfaces are unmodelled.** All seven are on the PocketOS path.

---

## 4. Attack paths

Notation: `→` is a step. Grade is the *best* grade at which we could intervene.

### AP-1 · Credential harvest → out-of-band mutation (the PocketOS path)
`ASI02, ASI03, T2, T3` · **FACT** it happened `[B-01][B-02]`

```
task in staging → agent hits ambiguity → agent greps workspace for a token
 → finds long-lived account-scoped token in unrelated file
 → Bash: curl -X POST <provider GraphQL> volumeDelete
 → production volume + backups destroyed in 9s
```

| Intervention | Grade | Effective? |
|---|---|---|
| Model gateway | — | **No.** Not a model request. |
| MCP gateway | — | **No.** Not an MCP call. |
| `fs.read` policy denying `**/.env*`, `**/*.pem`, credential-shaped files | B | Partial — raises cost, A-2 works around |
| `shell.exec` policy: deny `curl`/`wget` to non-allowlisted hosts | B | Yes for A-1/A-3 |
| Sandbox network allowlist (`strictAllowlist`) `[B-31]` | B | Yes for A-1/A-3 |
| **Credential broker: no long-lived token exists on disk** | **A** | **Yes — this is the control** |
| Environment binding: a staging-scoped identity cannot reach prod | A | Yes |
| Evidence: the action is recorded with subject, argument digest, destination | — | Makes it survivable |

**DESIGN DECISION:** AP-1 is the reference attack for the whole product. Any roadmap change
is tested against "does this move AP-1 coverage from none to A or B?"

### AP-2 · Untrusted content → instruction → destructive action
`ASI01, ASI06, T1, T6, LLM01` · **FACT** `[B-05][B-07]`

```
attacker files public GitHub issue with embedded instructions
 → CI or developer agent reads issue as task context
 → agent treats it as instruction → uses its own legitimate credential
 → publishes package / opens PR / leaks private repo content
```
Interventions: capability reduction on untrusted-context sessions (see §7 taint), approval
gate on `vcs.write`/`package.publish`, broker-scoped credentials, egress allowlist. **Not**
content detection alone — §2.3 of the thesis.

### AP-3 · MCP tool poisoning, rug pull, shadowing
`ASI04, T2, LLM04` · **FACT** `[B-06][B-59]`

Malicious instructions inside a tool `description`; definition mutated after approval
(`CVE-2025-54136`); a malicious server rewriting the semantics of another server's tools.
**Current design handles this well** — pinned snapshots, digest comparison, quarantine within
one cache TTL. Keep it. Extend to: treat tool descriptions as untrusted input that must never
be rendered to an approver without escaping, and re-approve on `tools/list_changed`.

### AP-4 · Agent memory and configuration persistence
`ASI06, T1, T3` · **SOURCE-BACKED** `[B-10]`

```
malicious dependency postinstall → writes MEMORY.md / hooks / rules file
 → every subsequent session inherits attacker instructions with system authority
```
Interventions: `memory.write` as a governed capability; integrity baseline over agent config
and memory files; Claude Code `ConfigChange` hook can **block** config mutation `[B-31]`;
alert on hook/settings drift. **This is entirely absent from the current design** and is cheap
to add.

### AP-5 · Gateway bypass
See §5 — its own section, because it decides what we may claim.

### AP-6 · Confused deputy via delegation
`ASI03, ASI07, T3, T9`

```
low-trust sub-agent spawned by high-trust agent
 → inherits parent's session credential
 → performs an action the human never authorised and the parent would not have
```
**INFERENCE:** the current design has no agent-instance or delegation concept at all, so this
is unmodellable today. `design/14` introduces the chain and the rule that **authority
attenuates and never widens across a hop**.

### AP-7 · Compromise of our data plane
`A-5, A-8`

The data plane holds upstream credentials and payloads — it is the highest-value target we
create. Mitigations: credentials KMS-wrapped and never returned by any API; broker issues
short-lived downstream credentials so a data-plane compromise yields minutes, not months; every
decision signed and chained so tampering is detectable; no console read path into the payload
store without an audited, time-boxed reveal.

### AP-8 · Compromise of our control plane / malicious vendor operator
`A-6`

**DESIGN DECISION (strengthens `01`):** the data plane **must not** accept a bundle that (a) is
unsigned, (b) has a version lower than the running one (rollback), or (c) *widens* effective
permissions beyond a customer-set ceiling without a second signature. A vendor-side attacker
who can sign a bundle must not be able to silently grant themselves access inside a customer.
Evidence of every bundle activation is written on the **customer** side.

### AP-9 · Evidence suppression
`T8 Repudiation & Untraceability`

An attacker who can stop the collector can make the action invisible. Mitigations: deny
decisions are never shed under backpressure (already in `01` — keep); hash-chained evidence so
a gap is detectable rather than silent; a heartbeat so *absence* of telemetry is itself an
alert; and the agent-side hook records locally before the network call.

---

## 5. Gateway bypass taxonomy

**DESIGN DECISION:** this table ships in the product documentation and in the sales deck.
Claiming universal enforcement is the fastest way to fail a technical evaluation.

Probability is for a 1,000-developer enterprise over a quarter. Sources for each control
mechanism are in §5 of `[B-31]`–`[B-43]`.

| # | Bypass | Prob. | Impact | Detectability | Mitigation | Enforceable by us? | Needs customer network/MDM? |
|---|---|---|---|---|---|---|---|
| 1 | Direct provider API via `curl`/SDK from shell | High | High | Med (egress logs, our `shell.exec` record) | Egress allowlist; deny `Bash(curl *)`; broker | Grade B only | **Yes** |
| 2 | Personal API key / BYOK in the IDE | High | High | Med | Cursor Enterprise **disable BYOK** `[B-42]`; secret scanning | Grade C | Partly |
| 3 | Consumer web UI (chatgpt.com, claude.ai) | **Very high** | High | High at SWG | SWG category block; managed browser | **No** | **Yes** |
| 4 | Browser extension assistants | Med | Med | Med | MDM extension allowlist (Cursor `AllowedExtensions`) `[B-42]` | Grade C | **Yes** |
| 5 | Local model (Ollama, LM Studio, vLLM) | Med | Med | **Low** | Host firewall on inference ports; endpoint inventory | **No** | **Yes** |
| 6 | stdio MCP server on the laptop | High | High | Med (hooks/OTLP if enabled) | `allowManagedMcpServersOnly` `[B-32]`; run stdio in our data plane | Grade B/C | Partly |
| 7 | Remote MCP outside the allowlist | Med | High | High | Cursor Enterprise MCP allowlist (**replace**, not merge) `[B-42]`; Copilot `allowedMcpServers` intersection `[B-36]` | Grade C | No |
| 8 | DNS-over-HTTPS | Med | Med | **Low** | Block known DoH resolvers; force corporate DNS | **No** | **Yes** |
| 9 | Personal VPN | Med | High | Low | MDM VPN policy; NAC | **No** | **Yes** |
| 10 | Personal / mobile device | **High** | High | **None** | VDI-only for sensitive repos | **No** | **Yes** |
| 11 | CI runner with long-lived secrets | High | **Very high** | Med | OIDC-only secrets; runner egress allowlist; broker | Grade A in CI | Partly |
| 12 | Self-hosted Copilot runner (disables GitHub firewall) `[B-35]` | Med | High | Med | Customer must reimplement egress control | **No** | **Yes** |
| 13 | Cursor Composer / Auto internal routing | **Certain** | Med | D only | Reconcile from Admin API; accept Grade D | **No** | No |
| 14 | Copilot IDE traffic | **Certain** | Med | Metadata only | TLS inspection **only** with corporate root CA on the device `[B-35]` | **No** | **Yes** |
| 15 | Alternate CLI (Aider, raw Codex, OpenCode) | Med | Med | Low | Software allowlist; block installs | **No** | **Yes** |
| 16 | Agent spawns a subprocess that calls out | Med | High | Med (EDR, our `shell.exec` record) | Sandbox; deny patterns | Grade B | Partly |
| 17 | Developer edits managed settings (local admin) `[B-32]` | Med | High | Med | Remove local admin; `ConfigChange` hook; drift alert | Grade B detect | **Yes** |
| 18 | Cloud IDE / Codespaces | Low | Med | Med | Org policy; separate egress profile | Grade C | No |

**INFERENCE — the three honest conclusions:**

1. **Roughly half of these are only mitigable by controls the customer owns** (SWG, MDM, NAC,
   removal of local admin). Our product's job is to *tell them which ones are open and produce
   the configuration*, not to pretend we close them.
2. **Rows 3, 5, 9, 10 are Grade E.** The product must estimate and display the size of the dark
   population rather than omit it. A coverage number with no denominator is a lie.
3. **Row 11 (CI) is the most under-rated.** It has the highest blast radius, the longest-lived
   credentials, no interactive human, and it is where Clinejection actually landed `[B-07]`.
   It is also the easiest place to reach Grade A, because CI is infrastructure the customer
   controls. **DESIGN DECISION:** CI agents are in scope from MVP, not deferred.

---

## 6. Threat catalogue by relationship

Condensed; full control mapping in [`15-capability-governance.md`](15-capability-governance.md).

### 6.1 Human → AI
| Threat | Mapping | Control | Grade |
|---|---|---|---|
| Shadow AI usage | `ASI04` | Discovery from endpoint + vendor APIs + egress; inventory | D |
| Accidental secret in prompt | `LLM02` | Inspector on mediated paths only; **cannot** cover Cursor (§6 thesis) | A where mediated |
| Malicious insider using an agent as a laundering layer | `T15` | Attribution to human via agent chain; anomaly on capability mix | B/D |
| Untrusted repo content as task input | `LLM01` | Session taint (§7) | B |

### 6.2 AI → Tool
| Threat | Mapping | Control | Grade |
|---|---|---|---|
| Tool poisoning / shadowing / rug pull | `ASI04, T2` | Pinned snapshot + digest + re-approval + quarantine (`06`, keep) | A |
| Argument manipulation | `ASI02` | Argument rules with real parsers; unparseable ⇒ deny (`06`, keep) | A |
| Destructive / irreversible operation | `ASI02, T2` | Capability risk class + approval + broker scoping | A/B |
| Cross-environment (staging task → prod resource) | `ASI03` | Environment binding on identity **and** credential | A |
| Confused deputy via sub-agent | `ASI03, T3` | Attenuating delegation (`14`) | A |
| Replay | `T2` | Nonce + short-lived approval token, single use | A |

### 6.3 Agent → Agent
**INFERENCE:** entirely unmodelled in the current design; `ASI07`, `ASI10`, `T9`, `T12`, `T13`
all apply. `design/14` adds `agent_instance`, delegation chains, and the attenuation rule.
**SOURCE-BACKED** `[B-38]` A2A is now Linux-Foundation-hosted with signed Agent Cards, and
delegates authentication to ordinary OAuth/OIDC/mTLS — so it is governable by the same
capability model rather than needing a parallel one.

### 6.4 AI → Data
| Threat | Mapping | Control | Grade |
|---|---|---|---|
| Model-mediated exfiltration (lethal trifecta `[B-60]`) | `LLM02` | Break a leg: no outbound capability in a tainted session | B |
| Retrieval poisoning | `ASI06, LLM09` | Provenance on retrieval sources; taint propagation | B |
| Cross-user / cross-tenant retrieval | `ASI03` | Retrieval as a governed capability with the caller's scope | A |
| Memory poisoning | `ASI06, T1` | `memory.write` capability + integrity baseline (AP-4) | B |
| Excessive context | `LLM08` | Observed-context accounting; policy on data-class mix | D |

### 6.5 AI → Infrastructure
`ASI05` (Unexpected code execution) is the row the current design most conspicuously lacks:
SSRF from agent HTTP, arbitrary shell, cloud metadata endpoint access (`169.254.169.254`),
container escape from a poorly sandboxed stdio MCP server, secret harvesting, lateral
movement, persistence. **DESIGN DECISION:** `shell.exec`, `net.http` and `fs.*` become
first-class capabilities precisely so this row has somewhere to live. The stdio sandbox
already specified in `06` (no inherited environment, egress allowlist, resource caps) is
correct and should be strengthened with an explicit cloud-metadata deny.

---

## 7. Session taint — a control the design did not have

**DESIGN DECISION.** Derived from the lethal-trifecta framing `[B-60]` and from CaMeL's
capability approach `[B-61]`, adapted to what we can actually observe.

A session carries a monotonically-rising **taint** once it ingests untrusted content:

```
taint(session) = f(read of public/external content, tool result from external source,
                   web fetch, third-party issue/PR body, dependency install output)
```

Policy may then bind capability availability to taint, which is enforceable and does not
require detecting the injection:

| Taint | Effect |
|---|---|
| `clean` | Normal capability set |
| `tainted` | `net.http` restricted to allowlist; `vcs.write` requires approval; `shell.exec` denied for credential-shaped paths |
| `tainted_with_secrets` | No outbound capability at all until a new session |

**Why this matters:** it converts an undetectable problem (is this text an injection?) into a
decidable one (did this session read untrusted input *and* does it now want an exfiltration
channel?). **INFERENCE:** this is the single highest-leverage novel control in this document
and it is cheap, because we already have to observe `fs.read`, `net.http` and tool results to
build the ledger.

**HONESTY:** this reduces risk. It does not prove absence. Sophisticated flows will find a
channel we did not classify as outbound.

---

## 8. Failure modes — declared behaviour

**DESIGN DECISION:** "unknown" is not an acceptable answer for any row. Extends `design/01`.

| Dependency down | Fail | Security impact | Availability impact | Customer sees | Recovery | Evidence |
|---|---|---|---|---|---|---|
| Control plane unreachable | **Open** for existing bundle | None while bundle valid | None | Nothing | Auto on reconnect | Bundle age on dashboard |
| Bundle expired (> TTL) | **Closed** for regulated classes, open + alarm for `internal` | Bounded | Partial | Reason code `bundle_expired` | Re-fetch | Alarm both planes |
| Policy engine error | **Closed** | None | Action blocked | `policy_evaluation_failed` | Fix + replay | Recorded as deny |
| Credential broker down | **Closed** | None | Action blocked | `credential_unavailable` | Retry | Recorded |
| Inspector (DLP) down | **Closed** for `restricted`+, **open + annotate** below | Bounded | Partial | `inspection_unavailable` | Auto | Recorded with grade downgrade |
| Collector / queue down | **Open**, spool to disk | Evidence delay | None | Nothing | Drain | Gap markers in chain |
| Spool full | **Shed allows, keep every deny** | Statistics degraded | None | Coverage banner | Auto | Shed count published |
| Evidence store down | **Open** for allows, **closed** for `irreversible` | Repudiation risk | Partial | `evidence_unavailable` | Auto | Alarm |
| KMS down | **Closed** for anything needing decryption | None | Partial | `kms_unavailable` | Auto | Recorded |
| Hook binary missing on endpoint | **Cursor default is fail-open** `[B-33]` | **Enforcement silently lost** | None | — | — | **Must alert**: see below |
| Clock skew > 60s | Reject approval tokens | Prevents replay | Minor | `clock_skew` | NTP | Recorded |

**Two entries deserve emphasis.**

- **FACT** `[B-33]` Cursor hooks **fail open by default**; `failClosed: true` must be set
  explicitly. **DESIGN DECISION:** we always emit `failClosed: true` for security-relevant
  hooks, and we treat *absence of expected hook telemetry* from an enrolled endpoint as a
  Grade-B coverage failure that appears on the dashboard within one heartbeat interval. A
  control that can be disabled by deleting a file must be monitored by its own absence.
- **Bundle rollback** is an attack, not a failure: the data plane refuses any bundle with a
  version lower than the running one (AP-8).

---

## 9. Residual risk — stated in the product, not only here

**DESIGN DECISION.** These sentences ship in the UI next to the relevant numbers.

1. **We cannot prevent prompt injection.** We reduce what a persuaded agent can reach.
   `[B-11][B-12][B-13]`
2. **We cannot prove a datacentre processed a token.** We prove which endpoint we called and
   how it is configured. (Unchanged from `05` — this was already honest and is kept.)
3. **Detection reduces risk; it does not prove absence.** (Unchanged from `07` — kept.)
4. **Grade B controls run on hardware the user administers.** A local administrator can remove
   them. We detect the removal; we cannot prevent it. `[B-32]`
5. **Grade E traffic exists and we estimate it.** Personal devices, consumer web UIs and local
   models are outside every control we have.
6. **For Cursor, content reaches Cursor before it reaches us.** `[B-41]`
7. **A compromised data plane exposes payloads and upstream credentials** for the lifetime of
   those credentials — which is why brokering short-lived credentials is a security control
   for *us*, not only for the customer.

---

## 10. Assumptions

**OPEN — each is a place the model breaks if it is wrong.**

| ID | Assumption | If false |
|---|---|---|
| AS-1 | The customer can deploy managed settings / MDM to developer endpoints | Grade B is unavailable; product is Grade A + C + D only |
| AS-2 | Vendors keep hook and managed-settings APIs stable | Grade B enforcement breaks on a client release; needs a compatibility matrix and version pinning |
| AS-3 | Developers have no local admin, or removal is detectable | Grade B is advisory only |
| AS-4 | The customer will let us broker credentials to downstream systems | The strongest control (AP-1 Grade A) is unavailable |
| AS-5 | CI is customer-controlled infrastructure | Row 11 drops from A to D |
| AS-6 | Vendor admin APIs keep exporting per-user usage | Grade D attribution degrades to aggregate |
