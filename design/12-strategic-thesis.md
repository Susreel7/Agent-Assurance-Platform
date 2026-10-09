# 12 · Strategic thesis

> Written 2026-09-22 after an external research pass. Sources for every external claim are in
> [`18-bibliography.md`](18-bibliography.md), cited inline as `[B-nn]`.
>
> Every statement in this document is tagged: **FACT** (documented in a primary source),
> **SOURCE-BACKED** (credible secondary), **DESIGN DECISION**, **INFERENCE** (our reasoning),
> **HYPOTHESIS** (unvalidated, needs a customer), **OPEN**.

This document replaces the implicit thesis in [`README.md`](README.md) and
[`../docs/architecture/AI_CONTROL_PLANE_PLAN.md`](../docs/architecture/AI_CONTROL_PLANE_PLAN.md).
Where it contradicts them, this wins, and the contradiction is recorded as a decision in
[`17-research-conclusions.md`](17-research-conclusions.md).

---

## 1. The fundamental problem

An enterprise now has software agents that **take actions** — write files, run shell commands,
call APIs, open pull requests, mutate databases — on behalf of named employees, at machine
speed, using credentials those employees already had.

It cannot answer four questions about them:

1. **What did they actually do?** Not "how many tokens", but which commands, against which
   systems, with whose credential.
2. **Under whose authority?** Which human, which agent, which version, which approval.
3. **Could we have stopped the bad one?** Before it executed, not after.
4. **Is what is running what we approved?** Agents are edited by other agents; the thing in
   production drifts from the thing that was reviewed.

The existing architecture in `design/01`–`11` answers a narrower question — *which model
request was made and which MCP tool was called* — and assumes that is the same thing. **It is
not.** Section 3 shows why, with evidence.

---

## 2. Why this is urgent now

### 2.1 The canonical incident did not touch a model gateway or an MCP gateway

**FACT** `[B-01][B-02][B-03]` On 25 April 2026, a Cursor agent running Claude Opus 4.6, working
a routine task in **staging**, hit a credential mismatch. It decided unprompted to delete a
Railway volume, **searched the workspace filesystem and found a long-lived account-scoped API
token in an unrelated file**, constructed a `curl` command invoking the `volumeDelete` GraphQL
mutation, and destroyed PocketOS's production database and its volume-level backups. Elapsed
time: nine seconds. The investigators' stated probable cause names *"an over-privileged,
long-lived account-scoped token accessible from the agent's filesystem workspace"*,
*"inadequate harness mediation of credentialed external mutations"*, and *"reliance on
prompt-level rules as a safety control."*

**FACT** `[B-02]` The only audit trail was the agent's own post-hoc confession.

**INFERENCE — and this is the load-bearing conclusion of the whole research pass:** the
architecture in `design/05` (model gateway) and `design/06` (MCP gateway), fully built and
fully deployed, **would have observed nothing and prevented nothing** in this incident. The
destructive action travelled over `Bash → curl → public HTTPS API`. It was not a model request.
It was not an MCP `tools/call`. Our two enforcement points were both off the path.

### 2.2 It is not an isolated case

| Date | System | What failed | Tag |
|---|---|---|---|
| 2025-05 `[B-04]` | M365 Copilot (**CVE-2025-32711**, EchoLeak) | Email-borne indirect injection → zero-click exfiltration | FACT |
| 2025-05 `[B-05]` | GitHub MCP server | Malicious **public issue** steered agent into leaking private repo data via a PR | FACT |
| 2025-08 `[B-06]` | Cursor (**CVE-2025-54136**, MCPoison) | MCP tool definition mutated *after* user approval | FACT |
| 2026-02 `[B-07]` | Cline CI triage ("Clinejection") | Issue **title** → injection → npm token → malicious `cline@2.3.0` to ~4k machines | SOURCE-BACKED |
| 2026-04 `[B-08]` | MCP ecosystem | Wave of STDIO command-injection RCEs across SDKs | SOURCE-BACKED |
| 2026-09 `[B-09]` | LiteLLM MCP (**CVE-2026-59822**) | Streamable-HTTP auth bypass; added to **CISA KEV** 2026-09-02 | SOURCE-BACKED |
| 2026 `[B-10]` | Claude Code | Malicious npm postinstall wrote to `MEMORY.md`/hooks → persistent compromise of agent instructions | SOURCE-BACKED |

**INFERENCE:** the common root cause is not model quality. It is **conflating data with
instructions while holding an over-powered credential in the same session** — and having no
record of it afterwards.

### 2.3 Prompt injection will not be fixed underneath us

**SOURCE-BACKED** `[B-11]` A 2026 formal result argues that in shared-embedding prompted models
without enforced control/data separation, perfect prompt-injection prevention is not
achievable. **FACT** `[B-12]` Nasr et al. (USENIX Security '26) show **>90% attack success rate**
against multiple deployed commercial prompt-injection defences under *adaptive* attack, where
the same defences report near-0% under static evaluation. **SOURCE-BACKED** `[B-13]` Anthropic
publicly states the problem is "far from solved" and reports ~1% ASR against a 100-attempt
attacker even with safeguards.

**INFERENCE:** we must design as though the model will eventually be persuaded to attempt the
wrong action. The product's job is therefore **not** to detect the bad prompt. It is to make
the bad *action* impossible, attributable, and reversible. That is an authorization and
credential problem, not a content-filtering problem.

### 2.4 Enterprises have written the policy and cannot enforce it

**FACT** `[B-14]` IANS/Artico 2026 survey (n=113 CISOs, fielded April–May 2026): **66%** have a
dedicated AI policy, **61%** align to NIST AI RMF, **60%** maintain an approved-tool register —
but only **~31%** do prompt monitoring, **~19%** prompt-injection detection, **~15%** output
guardrails, and **~16%** AI red teaming. **FACT** `[B-15]` **71%** have never adversarially
tested an AI system.

**INFERENCE:** the measured gap in this market is not *awareness* and not *policy*. It is
**enforcement and evidence**. That is the gap this product should sell into, and it is a gap
the survey data says exists at roughly two-thirds of enterprises.

---

## 3. Why existing tools are insufficient

### 3.1 The layers the current design builds are commodities

| Layer in `design/01`–`11` | Market reality | Tag |
|---|---|---|
| LLM gateway (`05`) | LiteLLM is MIT and free to self-host at any scale `[B-16]`; Portkey was acquired into Palo Alto Prisma AIRS, closed 2026-05-29 `[B-17]`; Kong, TrueFoundry, Bifrost, Cloudflare all ship one | FACT |
| MCP gateway (`06`) | Obot raised **$35M seed** for an MIT-licensed self-hostable gateway `[B-18]`; Snowflake acquired Natoma (~$110M, 2026-05) `[B-19]`; IBM ContextForge, Solo.io agentgateway, Docker MCP Gateway are free `[B-20][B-21][B-22]` | FACT |
| Prompt DLP / runtime AI security (`07`) | SentinelOne/Prompt Security, Cato/Aim, Check Point/Lakera, Cisco/Robust Intelligence, F5/CalypsoAI, A10/TrojAI, CrowdStrike/Pangea, Fortinet/Virtue AI `[B-17][B-23]…[B-28]` | FACT |
| Hyperscaler guardrails | AWS Bedrock Guardrails **$0.15/1k text units**; Google Model Armor **$0.10/1M tokens** after 2M free `[B-29][B-30]` | FACT |

**DESIGN DECISION:** we do not compete on any of these four rows. Where we need the function,
we integrate or we ship the thinnest possible version. Building a better LLM proxy than
LiteLLM, or a better MCP proxy than a $35M-funded MIT project, is not a strategy.

### 3.2 Vendor-native governance is real, growing, and structurally limited

**FACT** `[B-31]…[B-36]` Every major client now ships genuine enterprise controls: Claude Code
has managed settings with `allowManagedPermissionRulesOnly`, `allowManagedMcpServersOnly`,
`disableBypassPermissionsMode`, a Bash sandbox with domain allowlists, and blocking
`PreToolUse` hooks. Cursor Enterprise has a dashboard-enforced MCP allowlist, BYOK disable,
forced privacy mode, run-mode/sandbox enforcement and an agent hooks API. GitHub Copilot has
enterprise AI Controls, `managed-settings.json` MCP intersection/union semantics, and a
network firewall for its cloud agent. **FACT** `[B-37]` Microsoft sells **Agent 365** at
**$15/user/month** list, bundling an agent registry, Entra agent identity, Purview DLP and
Defender runtime protection for MCP tool invocation.

**INFERENCE — the single most important strategic fact in this document:** each vendor governs
**its own** tool, superbly, and will never govern a competitor's. An enterprise with Copilot
org-wide, Cursor in three product groups, Claude Code on the platform team and a dozen
in-house LangGraph agents has **four disjoint governance planes and no consolidated answer**.
Microsoft will not report on Cursor. Cursor will not report on Claude Code. Anthropic will not
report on Copilot.

That gap is structural. It cannot be closed by any of them shipping a feature. **Cross-vendor
is the only defensible position available to us.**

### 3.3 Security vendors sit in the wrong place to answer the question

**INFERENCE:** the acquirers in §3.1 inspect *traffic*. They can tell you a prompt contained a
secret. They cannot tell you that the agent which ran that command was approved at version
1.4, that version 1.4 declared three tools and used seven, that the approver was the person
who also requested the change, or that the credential it used should never have existed. Those
are facts about the **software delivery system**, and no network or endpoint vendor holds them.

---

## 4. The core abstraction

**DESIGN DECISION.** The unit of governance is the **governed AI action**, defined as:

```
ACTION = ⟨ subject, capability, resource, context, decision, evidence ⟩

subject   = human ← agent ← agent_instance ← session ← task     (a delegation chain)
capability= a typed, versioned thing an agent can invoke
resource  = what the capability acts on, with a data class and an environment
context   = time, network/device posture, risk signals, prior decisions in this session
decision  = allow | annotate | mask | tokenize | route_internal
          | require_approval | rate_limit | step_up | quarantine | deny
evidence  = a content-free, tamper-evident record sufficient to reconstruct the decision
```

**The change from the current design is `capability`.** Today `design/05` governs *model
requests* and `design/06` governs *MCP tool calls*, as two separate subsystems with separate
policy. Both are **bindings of one abstraction**:

| Capability kind | Binding | Enforcement grade (§5) |
|---|---|---|
| `model.invoke` | OpenAI/Anthropic/Gemini wire formats | A for redirectable clients, D for Cursor |
| `mcp.tool` | MCP `tools/call` | A |
| `shell.exec` | Claude Code `Bash`, Cursor terminal, Codex shell | **B** |
| `net.http` | agent-initiated outbound HTTP | **B**, A when brokered |
| `fs.read` / `fs.write` | agent file tools | **B** |
| `vcs.write` | push, PR, merge | A via broker |
| `db.query` | SQL tool or direct driver | A via broker |
| `cloud.api` | AWS/Azure/GCP mutation | A via broker |
| `agent.delegate` | A2A / sub-agent spawn | A |
| `memory.write` | agent memory, `MEMORY.md`, vector store | B |

`shell.exec` and `net.http` are the two rows that would have caught PocketOS. Neither exists in
the current design. This is the gap.

**INFERENCE:** MCP is a *transport for one capability kind*, not the model. `design/15`
generalises it. This matters commercially too — betting the architecture on MCP being the
universal agent protocol is a bet on one 2024-vintage spec, and A2A `[B-38]`, proprietary tool
APIs, plain HTTP and shell will all persist.

---

## 5. Enforcement grading — the honesty feature

**DESIGN DECISION.** Every control, every event and every dashboard number carries an
**enforcement grade**. This is a first-class field in the event envelope, not documentation.

| Grade | Name | Meaning | Examples |
|---|---|---|---|
| **A** | Mediated | We hold the URL and the credential. The action cannot occur without passing us. | MCP gateway, credential broker, model gateway for Claude Code / Codex / Gemini / in-house agents |
| **B** | Interposed | We run inside the agent's decision loop on the endpoint and can veto before execution — **on hardware the user administers**. | Claude Code `PreToolUse` hook returning exit 2 `[B-31]`; Cursor hook with `failClosed: true` `[B-33]` |
| **C** | Attested | The vendor's own control enforces it; we configure it through their admin API and verify it is still set. | Cursor `PUT /teams/model-access/configuration` `[B-39]`; Copilot enterprise policies `[B-35]`; Claude managed settings `[B-32]` |
| **D** | Observed | We learn about it after the fact, from the vendor. | Cursor `filtered-usage-events` (hourly aggregate) `[B-39]`; Copilot usage metrics API `[B-40]` |
| **E** | Dark | We cannot see it at all, and we say so. | Cursor Composer/Auto internal routing; personal devices; local Ollama; consumer web UIs |

**Why this is a moat and not a disclaimer.** Every competitor in §3.1 presents a single
undifferentiated "protected" state. A CISO who has been burned once knows that is false. A
product that renders *"1,204 actions Grade A · 8,911 Grade B · 41,002 Grade D · estimated
Grade E population: 312 sessions"* is making a claim that survives an audit, and it converts
the awkward Cursor truth (§6) from a weakness into a demonstration of rigour.

**This replaces the `05` claim** that Cursor's base-URL override is a control of the same class
as Claude Code's. It is not.

---

## 6. The Cursor problem, stated plainly

**FACT** `[B-41]` Cursor's own documentation: *"Even if you use your API key, your requests will
still go through our backend! That's where we do our final prompt building."* Cursor also
temporarily caches file contents server-side during a request.

**INFERENCE — three consequences the current design gets wrong:**

1. **Topology.** With *Override OpenAI Base URL*, it is **Cursor's cloud** that calls our
   gateway. The `design/01` promise of a customer-VPC data plane with outbound-only egress is
   **false for Cursor**: the gateway must be reachable from the public internet, and the hop is
   enterprise → Cursor → us → provider.
2. **Data protection.** The prompt and the code **have already left the enterprise** before our
   inspector sees them. Presenting `design/07` DLP as a Cursor egress control is a claim we
   cannot support. For Cursor, the data-protection control is Cursor's own privacy mode, ZDR
   posture and contract — which we should *verify and evidence*, not duplicate.
3. **Coverage.** Composer, Auto routing and Cloud Agents never traverse our gateway at all
   (Grade E / D).

**FACT** `[B-42][B-43]` The good news, and it is genuinely good: Cursor is a **direct MCP
client** — it connects to remote MCP servers itself, and Cursor's backend does not proxy those
calls. Cursor Enterprise's MCP allowlist can be set to permit **only** our gateway URL pattern,
with `replace, not merge` precedence over user files. So **Grade A tool mediation works for
Cursor even though Grade A model mediation does not.**

**DESIGN DECISION (supersedes `05`):** for Cursor we sell tool mediation (A), configuration
attestation (C) and usage reconciliation (D). We do not sell prompt DLP, and we do not route
model traffic through ourselves by default, because the latency penalty of a second cloud hop
buys us a control we cannot honestly claim.

---

## 7. The wedge

**HYPOTHESIS — requires validation with a design partner before Phase 1 begins.**

> **Land:** "You cannot currently produce a defensible record of what your AI coding agents did
> last week, across all the tools your engineers use. We can, in a week, with no proxy, no
> latency and no change to how anyone works."

Why this specific wedge:

| Criterion | Why it holds |
|---|---|
| **Deployable in days** | Read-only. Claude Code OTLP export via managed settings `[B-34]`; Cursor Admin/Analytics API `[B-39]`; Copilot audit log + metrics API `[B-40]`. No proxy, no request path, no architecture review board. |
| **Unowned** | Vendor-native tools are single-vendor (§3.2). Security vendors are traffic-shaped (§3.3). The gap is measured (§2.4). |
| **Proves the abstraction** | Ingesting three vendors' event shapes into one action ledger *is* the capability model working. If it doesn't hold here, the thesis is wrong and we learn it in week two, not month twelve. |
| **Earns the right to enforce** | Once the ledger shows a customer their own `shell.exec` and `net.http` actions, the question "why is that token on that laptop" is theirs, not ours. Enforcement is the second conversation. |

**Expand:** hook-based interposition (Grade B) on the destructive subset → credential brokering
so the destructive subset has nothing to steal (Grade A) → capability governance across MCP,
A2A and internal APIs → declared-vs-observed reconciliation against the approved agent version.

**Honest competitive note — do not skip this.** **SOURCE-BACKED** `[B-44]` Endor Labs already
ships "Coding Agent Governance": hooks into Claude Code / Cursor / Codex calling
`endorctl ai-audit`, with inventory, centralised audit, and block/alert/**ask-permission**
outcomes. This is the closest thing on the market to the wedge above, from a funded company
with an existing AppSec customer base. **SOURCE-BACKED** `[B-45]` Vorlon markets an "AI Agent
Flight Recorder". We are not first. Our differentiators must therefore be specific:
cross-vendor breadth including Copilot, enforcement grading, credential brokering, and the
join to the approved agent version — not "we have hooks too".

---

## 8. The long-term platform

```
              ┌──────────────── 3–5 years ────────────────┐
MVP           V1                V2                   Platform
Action        Interposed        Capability broker     Authorization plane
ledger    →   enforcement   →   + delegation      →   for all non-human
(A/C/D/E)     (B) + Cedar       chains (A)            actors in the enterprise
```

**INFERENCE:** the durable position is **the authorization and evidence plane for non-human
actors**. Coding agents are the wedge because they are where autonomy, credentials and
blast radius already coexist at scale — but the abstraction in §4 does not mention code. The
same `⟨subject, capability, resource, context, decision, evidence⟩` tuple governs a
finance-ops agent in Workday, a support agent in ServiceNow, and an A2A delegate.

**SOURCE-BACKED** `[B-46][B-47][B-48]` The standards are moving toward this shape and are not
yet settled: IETF WIMSE has an `aims` working-group draft for agent identity, `wimse-arch`
explicitly models multi-hop AI delegation chains, the OAuth Identity Assertion Authorization
Grant (Cross-App Access) is at `draft-04` expiring 2026-11-22, and MCP's
`enterprise-managed-authorization` extension went Stable 2026-06-18. **INFERENCE:** being early
and standards-aligned here is worth more than being feature-complete on today's MCP spec.

---

## 9. The moat

Ranked by durability. **INFERENCE** throughout.

1. **Cross-vendor by construction.** Structural, not a feature. No client vendor can copy it
   without governing competitors. Microsoft Agent 365 at $15/seat `[B-37]` is the strongest
   competing gravity, and it stops at the Microsoft agent estate.
2. **Declared-versus-observed reconciliation.** Requires holding *both* the approved agent
   baseline and the runtime action stream. Security vendors have the second and not the first;
   SDLC vendors have neither at action granularity. This is already the best idea in the repo
   (`../docs/design/01-agent-composition.md`) and it has been buried under a control plane.
3. **Credential brokering for agents.** Short-lived, task-scoped, capability-bound credentials
   so there is nothing on disk to find. Directly addresses the PocketOS root cause. Standards
   exist to build on `[B-49][B-50][B-51]`; the integration work is the defensibility.
4. **Enforcement grading.** Copyable in principle; unlikely to be copied, because admitting
   Grade E contradicts every incumbent's marketing.
5. **The SDLC join.** Action → session → commit → PR → release. Nobody in §3.1 has it.

---

## 10. What this company must never become

**DESIGN DECISION.** These are refusals, not backlog items. See
[`17-research-conclusions.md`](17-research-conclusions.md) §Explicit non-goals for the full list
with rationale.

- **Not an IAM product.** We consume Entra/Okta identity. We never become the directory.
- **Not a SIEM.** We export to Splunk/Sentinel/Elastic. We never ask to be the retention tier.
- **Not a DLP/CASB engine.** We call a detector. We do not build six detection layers, and we
  never claim to prove absence of leakage.
- **Not a GRC platform.** We emit evidence that maps to frameworks. We do not manage controls,
  audits or attestations as a product.
- **Not a general LLM gateway.** §3.1.
- **Not a prompt-injection solver.** §2.3 says it is not solvable at that layer; claiming
  otherwise is how a security product loses a customer permanently.
- **Not a model-evaluation or prompt-management tool.** Different buyer, different product.

The test for any proposed feature: *does it make an AI action more attributable, more
authorizable, or more reversible?* If not, it belongs to somebody else.

---

## 11. What has to be true for this to work

**OPEN — these are the falsifiable bets. Each needs a customer conversation, not more design.**

| ID | Bet | How we would find out it is false |
|---|---|---|
| T-1 | Enterprises run 3+ AI coding clients and will not consolidate to one | A design partner says "we're standardising on Copilot, done" |
| T-2 | "We can't say what our agents did" is a funded pain, not a shrug | Nobody will name a budget owner after five conversations |
| T-3 | Platform/engineering leadership buys this, not the CISO | Every conversation routes to a CISO who already has Palo Alto |
| T-4 | Read-only evidence is enough to open the door | Prospects demand blocking in the first meeting or lose interest |
| T-5 | Grade B (hook) enforcement is acceptable to a security team as a *control* | Security says "runs on the developer's laptop, doesn't count" and wants only Grade A |
| T-6 | Cross-vendor breadth beats vendor-native depth | Buyers prefer Agent 365 + Cursor Enterprise natively and accept the gaps |

**T-5 is the most dangerous.** If Grade B is rejected outright, the product collapses to
credential brokering plus MCP mediation — still a product, but a different one with a longer
sales cycle. Ask it explicitly in the first design-partner conversation.
