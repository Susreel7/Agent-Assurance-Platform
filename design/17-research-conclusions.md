# 17 · Research conclusions

> Research pass executed 2026-09-22. Sources in [`18-bibliography.md`](18-bibliography.md),
> cited as `[B-nn]`. Tags: **FACT** · **SOURCE-BACKED** · **DESIGN DECISION** · **INFERENCE** ·
> **HYPOTHESIS** · **OPEN**.

---

## 1. Executive summary

The existing design is a **well-engineered answer to a question that is narrower than the one
the market has**. It governs model requests and MCP tool calls with real rigour — pinned
snapshots, argument parsing that fails closed, grant-filtered registries, fail-closed
defaults. Those are good instincts and most of them survive this review unchanged.

Three findings force a change of direction.

**Finding 1 — the enforcement points are off the path of real incidents.** The reference
incident of 2026 (`13` AP-1) ran `Bash → curl → GraphQL` using a long-lived token the agent
found on the filesystem `[B-01][B-02]`. The model gateway and the MCP gateway, fully built,
would have seen nothing and stopped nothing. Seven of thirteen attack surfaces in the threat
model are currently unmodelled, and all seven are on that path. **`shell.exec`, `net.http` and
`fs.read` must become first-class governed capabilities.**

**Finding 2 — the layers being built are commodities, and the honest layer is not.** LiteLLM
is free `[B-16]`, Obot has $35M behind an MIT MCP gateway `[B-18]`, and eleven AI-security
companies were acquired in fourteen months `[B-17][B-23]…[B-28][B-79]`. Meanwhile Microsoft
sells Agent 365 at **$15/user/month** `[B-37]`. What is *not* commoditised is **cross-vendor
agent action evidence with honest enforcement grading and credential mediation** — because no
client vendor will ever govern a competitor's tool.

**Finding 3 — the enforcement claims are stronger than the evidence supports.** Cursor's own
documentation states that requests traverse Cursor's backend even with a customer API key
`[B-41]`. The design presents Cursor base-URL routing as equivalent to Claude Code managed
settings. It is not. Roughly half of the realistic bypasses in `13` §5 can only be mitigated
by controls the **customer** owns. Fixing this is not damage control — an explicit A/B/C/D/E
**enforcement grade** on every control and every number is the most defensible differentiator
available, because no incumbent can adopt it without contradicting their own marketing.

**The recommendation:** keep the engineering, narrow the product, change the enforcement
layer, and lead with evidence rather than interception.

---

## 2. What the existing architecture already gets right

**Preserve these. They are better than most of what the competitive research turned up.**

| # | Decision | Why it survives |
|---|---|---|
| 1 | Control plane never on the request path | Removes the availability objection that kills gateway products in architecture review |
| 2 | Signed policy bundles; data plane enforces from cache | Correct offline and partition behaviour |
| 3 | Payload digests in events, payloads in the customer boundary | The right privacy primitive; now enforced by schema (`15` §9) |
| 4 | Pinned MCP snapshots + `capability_digest` + quarantine ≤ 5 s | **Directly defeats `CVE-2025-54136`** `[B-06]`. Ahead of the market. |
| 5 | Supplier claims stored separately from verified findings | Exactly right, and exactly what the MCPoison class exploits |
| 6 | Unparseable argument ⇒ deny | The correct failure direction; most products fail open here |
| 7 | Grant-filtered `tools/list`; absence as denial | Reduces both attack surface and developer confusion |
| 8 | Argument rules with real parsers, not regex | "Block this *use* of `execute_sql`" is the thing customers actually need |
| 9 | Never shed a deny under backpressure | Preserves evidence integrity when it matters most |
| 10 | Measure false-positive rate before a DLP rule may block | Intellectually honest and rare |
| 11 | "We cannot prove a datacentre processed a token" | Already honest about residency. Extend this instinct everywhere. |
| 12 | `aap extract` and declared-vs-observed composition | **The best idea in the repository.** Promoted from a `docs/design` note to a pillar. |
| 13 | Org-unit tree with closure table and scoped visibility | Correct, and the reparenting/matrixed-member handling is non-trivial work already done |
| 14 | Stdio MCP servers run in the data plane, not on the laptop | Correct credential-boundary reasoning |

---

## 3. Missing capabilities

| # | Missing | Consequence | Where addressed |
|---|---|---|---|
| M-1 | `shell.exec` as a governed capability | **Reference incident invisible** | `15` §3 |
| M-2 | `net.http` / agent egress | Exfiltration channel ungoverned | `15` §3 |
| M-3 | `fs.read` / `fs.write` | Credential harvest step invisible | `15` §3 |
| M-4 | Credential **brokering** (vault → broker) | Root cause of AP-1 unaddressed | `14` §5 |
| M-5 | `agent_instance` entity | Cannot attribute an action to a running copy | `14` §3.3 |
| M-6 | Delegation / sub-agents | Confused deputy unmodellable | `14` §4 |
| M-7 | Enforcement grading | Every claim is unfalsifiable | `12` §5 |
| M-8 | Session taint | Trifecta undetectable | `13` §7 |
| M-9 | Agent memory / config as governed resource | Persistence vector open `[B-10]` | `15` §3 |
| M-10 | Agent lifecycle state machine | No discover → approve → retire path | `14` §9 |
| M-11 | Shadow-agent discovery | Cannot answer "show me every AI system" | `14` §9, MVP |
| M-12 | Tamper-evident evidence chain | Suppression undetectable | `15` §9 |
| M-13 | CI agents as a first-class surface | Highest blast radius, best grade, omitted | `13` §5 row 11 |
| M-14 | Policy simulation before activation | Cannot answer "what will this break?" | `14` §7 |
| M-15 | Coverage accounting / dark-population estimate | Coverage numbers have no denominator | `15` §8 |
| M-16 | Downstream mutation join (commit / PR / release) | The SDLC join nobody else has | `15` §9 |

---

## 4. Security gaps

| # | Gap | Severity | Resolution |
|---|---|---|---|
| S-1 | Out-of-band credential use (AP-1) | **Critical** | Broker + `shell.exec`/`net.http` policy |
| S-2 | Agent memory/config poisoning (AP-4) | **High** | `memory.write` capability + integrity baseline + `ConfigChange` hook `[B-31]` |
| S-3 | Sub-agent privilege inheritance (AP-6) | High | Attenuating delegation, depth cap |
| S-4 | Bundle rollback attack | High | Refuse lower version; second signature to widen permissions |
| S-5 | Evidence suppression (AP-9) | High | Hash chain + heartbeat; absence is an alert |
| S-6 | Hook removal / fail-open default | **High** | **FACT** `[B-33]` Cursor hooks fail open by default. Always set `failClosed`; treat missing hook telemetry as a coverage incident |
| S-7 | Cloud metadata endpoint from agent shell | High | Explicit deny in sandbox and policy |
| S-8 | Cross-environment reach (staging task → prod resource) | **Critical** | Environment binding on **identity and credential**, not just request metadata |
| S-9 | Tool description rendered to an approver | Medium | Escape, never markdown-render, never concatenate into a generated prompt |
| S-10 | Data-plane compromise exposes long-lived credentials | High | Brokering shortens the blast radius for us too |
| S-11 | No replay protection on approvals | Medium | Single-use, nonce-bound, short-TTL approval tokens |
| S-12 | Self-hosted Copilot runners disable GitHub's firewall `[B-78]` | Medium | Detect and surface as a coverage gap; customer must reimplement |

---

## 5. Competitive gaps

| # | Gap | Evidence |
|---|---|---|
| C-1 | Building four commodity layers | `[B-16][B-18][B-20][B-21][B-22][B-29][B-30]` |
| C-2 | No answer to Microsoft Agent 365 at $15/seat | `[B-37][B-92]` |
| C-3 | **Not first to the wedge** — Endor Labs ships coding-agent governance with hooks and ask-permission today | `[B-44]` |
| C-4 | "AI Control Plane" is not a category buyers search for | `[B-97][B-98]` |
| C-5 | No pricing model; per-action pricing would have punished adoption | `16` §5 |
| C-6 | Buyer not identified; three plausible budgets with different cycles | `16` §4 |

---

## 6. Architecture changes — decision records

Format per the brief. **Nothing here is a silent rewrite.**

---

**D-08 · The unit of governance is the capability invocation, not the model request**
- **Old:** Two enforcement subsystems — model gateway (`05`) and MCP gateway (`06`) — with separate policy.
- **New:** One capability model (`15`). MCP is one binding. `shell.exec`, `net.http`, `fs.*`, `vcs.write`, `cloud.api`, `agent.delegate`, `memory.write` are added as kinds.
- **Evidence:** `[B-01][B-02]` reference incident; `[B-07]` Clinejection; `[B-10]` memory compromise — none traverse a model gateway or MCP.
- **Reason:** The current enforcement points are absent from the majority of documented 2026 agent incidents.
- **Impact:** `05` and `06` become bindings under `15`. Event model unifies.
- **Migration:** Existing MCP tables generalise with column renames; `mcp_grants` → `capability_grants` with a `capability_selector`.

---

**D-09 · Enforcement is graded A–E and the grade is a mandatory field**
- **Old:** Controls presented as uniformly effective; "the gateway URL is the only path to a working credential."
- **New:** Grade A (mediated) / B (interposed) / C (attested) / D (observed) / E (dark) on every control, event and displayed number.
- **Evidence:** `[B-41]` Cursor backend interposition; `[B-32]` managed settings editable by a local admin; `[B-33]` hooks fail open by default; `13` §5 bypass table.
- **Reason:** Undifferentiated claims fail technical evaluation. Grading converts the honesty requirement into the differentiator (`16` §6.6).
- **Impact:** Schema, UI, marketing, contract language.
- **Migration:** `enforcement_grade` added to every decision row; backfill as `unknown` and treat as E.

---

**D-10 · Token vault becomes a credential broker**
- **Old:** `06` — the gateway holds upstream credentials and injects them for MCP calls.
- **New:** A broker issues short-lived, audience-bound (RFC 8707), sender-constrained (RFC 9449/8705) credentials per task, brokering against Vault / cloud WIF rather than becoming a secrets manager.
- **Evidence:** `[B-01]` Railway: "It found a long-lived token on disk"; `[B-49][B-50][B-51][B-63]` final RFCs; `[B-69][B-70]` existing broker backends; `[B-101]` industry-wide NHI hygiene gap.
- **Reason:** The only Grade A control against AP-1.
- **Impact:** New `credential_bindings` and `credential_leases` tables; downstream integration work per system.
- **Migration:** The existing vault becomes one backend. Nothing is thrown away.
- **Caveat:** **OPEN (Q-N)** — probably not MVP; it asks the customer to move a credential.

---

**D-11 · Cursor claims are corrected**
- **Old:** `05` implies base-URL override gives enforcement and DLP coverage comparable to Claude Code.
- **New:** For Cursor we claim Grade A **tool** mediation (MCP allowlist `[B-42]`), Grade C configuration attestation, Grade D usage reconciliation `[B-39]`. **No prompt DLP claim. No default model-traffic routing.**
- **Evidence:** `[B-41]` — Cursor's own documentation.
- **Reason:** The claim is not supportable, and a second cloud hop costs latency for a control we cannot honestly assert.
- **Impact:** Rewrite `05` §Cursor; the Cursor topology diagram must show the Cursor-cloud hop.
- **Migration:** None built yet.

---

**D-12 · Identity gains version, instance, session, task and delegation**
- **Old:** Human / service identity / agent, with agent as a static row.
- **New:** `Human → Agent → Agent Version → Agent Instance → Session → Task → Action`, with delegation as RFC 8693 `sub`/`act` semantics, attenuating authority and a depth cap.
- **Evidence:** `[B-49]`, `[B-68]` (nested `act` is informational), `[B-46]` (`wimse-arch` per-hop re-binding), `[B-71]` (agents as first-class principals).
- **Reason:** "Who is responsible" is unanswerable without it; AP-6 is unmodellable without it.
- **Impact:** `02`, `03`, `04`.
- **Migration:** Additive tables; existing `agents` rows become `agents` + one `agent_versions` row.

---

**D-13 · Cedar is the policy engine; administrators never write it**
- **Old:** Bespoke YAML policy.
- **New:** Structured admin UI compiles to Cedar. Cedar is the audit artefact and the simulation target.
- **Evidence:** `[B-73]` native `principal/action/resource/context` shape; `[B-74]` SMT analysis and Lean-verified correctness; `[B-75]` Rego harder to bound and verify.
- **Reason:** Policy simulation becomes a solver query. For a product whose value is defensible decisions, that is worth more than expressiveness. And inventing a policy language is a non-goal.
- **Impact:** Policy storage, evaluation, simulation, bundle format.
- **Migration:** Existing YAML is a source format that compiles to Cedar.

---

**D-14 · Session taint becomes a first-class control**
- **Old:** Not present. DLP detected instruction-like content.
- **New:** Sessions carry `clean | tainted | tainted_with_secrets`; grants carry `max_taint`.
- **Evidence:** `[B-60]` lethal trifecta; `[B-61]` CaMeL capability enforcement; `[B-11][B-12]` detection is not sufficient.
- **Reason:** Converts an undecidable question ("is this an injection?") into a decidable one ("did this session read untrusted input and now want an outbound channel?").
- **Impact:** Session model, grants, policy.
- **Honesty:** Reduces risk. Does not prove absence.

---

**D-15 · Deployment modes reduce from five to three**
- **Old:** SaaS, single-tenant, self-hosted, air-gapped, local dev.
- **New:** **SaaS control plane + customer data plane** (default), **fully self-hosted**, **local development**. Air-gapped becomes a self-hosted variant with a documented bundle-transfer procedure, not a mode.
- **Evidence:** **INFERENCE** — each mode multiplies test matrix, support surface and release risk. No design partner has yet asked for air-gapped.
- **Reason:** A small team cannot support five deployment topologies and ship a wedge.
- **Impact:** `01`, `09`, packaging.
- **Migration:** None built yet.

---

**D-16 · ClickHouse, Kafka and the six-layer DLP stack leave the MVP**
- **Old:** `07` six detector layers; `08` Kafka → ClickHouse at 3,000 events/s.
- **New:** MVP uses Postgres with time partitioning. ClickHouse arrives when a real customer exceeds it. DLP is one pluggable interface with a small high-precision rule set; multimodal, embeddings and OCR are explicitly **later**.
- **Evidence:** **INFERENCE** — 3,000 events/s is a design target with no customer behind it; **FACT** `[B-14]` only ~15–31% of enterprises run any runtime AI control, so the first customer will not be at that volume.
- **Reason:** Optimising throughput before the first customer is the classic failure of this kind of project.
- **Impact:** `07`, `08`, phase plan.
- **Migration:** Event envelope is designed to be ClickHouse-compatible from day one, so the move is an ingest change, not a redesign.

---

**D-17 · Agent registration is mandatory for Grade A paths only; discovery is always free**
- **Evidence:** **INFERENCE** — a registration wall that developers route around converts a governance product into shadow AI's best recruiter.
- **Impact:** `14` §9.

---

**D-18 · External product framing changes from "AI Control Plane"**
- **Old:** "AI Control Plane."
- **New:** Agent action governance and evidence. Documents keep their filenames; external language changes.
- **Evidence:** `[B-97][B-98]` — analyst and buyer language is "AI application security" and "agent governance"; "AI control plane" is not a searched category.
- **Impact:** README, positioning, website.

---

## 7. The revised MVP

**Old:** ten phases, ending at deployment packaging. Model gateway at P3, MCP gateway at P5,
activity graph at P7 — a security outcome first visible around phase seven.

**New:** one vertical slice that produces a defensible security outcome, shippable read-only.

### MVP — "the agent action ledger"

| # | Capability | Customer problem | Why now | Effort | Security value | Commercial value |
|---|---|---|---|---|---|---|
| 1 | Agent identity registry (human → agent → version → instance → session) | "Which agents exist and who owns them?" | Nothing else attributes | M | Foundational | High — the demo |
| 2 | Evidence ingest: Claude Code OTLP `[B-34]`, Cursor Admin API `[B-39]`, Copilot audit + metrics `[B-40]` | "What did they do?" | APIs exist today | M | Attribution | **The wedge** |
| 3 | Hook collector: `shell.exec`, `net.http`, `fs.read` observed (**not blocked**) `[B-31][B-33]` | "Which commands and which hosts?" | The AP-1 surface | M | **Highest** | High |
| 4 | Capability model + action ledger + one investigation screen | "Reconstruct this incident" | — | M | Forensics | High |
| 5 | Enforcement grading A–E with a dark-population estimate | "What can't you see?" | — | S | Honesty | **Differentiator** |
| 6 | Shadow-agent and credential-exposure discovery | "Show me every AI system, and every token an agent could reach" | Creates the urgency | M | Discovery | **Sells the next phase** |

**Deliberately excluded from MVP:** model gateway, MCP gateway, DLP, tokenisation, ClickHouse,
cost accounting, five deployment modes, credential brokering, blocking.

**The MVP gate — one sentence.** *An investigator picks any action from the last 30 days and
reconstructs who, which agent, which version, which capability, which arguments (by digest),
which policy would have applied, and at what enforcement grade — without the product ever
having stored a prompt, a completion or a tool argument.*

**Why read-only.** It deploys in days, needs no architecture review, adds no latency, cannot
cause an outage, and — critically — **item 6 produces the customer's own evidence that they
need the next phase.** Showing a customer that 41 agents on 12 laptops can reach a
production-scoped token is a better argument for enforcement than any deck.

### V1 — enforcement

Hook-based Grade B deny on the destructive subset (`failClosed` always set, absence alarmed);
Cedar policy with simulation against the last 30 days of ledger data; approval workflow;
session taint; MCP gateway for Grade A tool mediation; **credential broker for the top three
destructive surfaces** (cloud API, VCS write, database).

### V2 — capability platform

Full capability model including `agent.delegate` and A2A; declared-vs-observed reconciliation
against the approved agent version; memory and context governance; multi-region; SIEM export;
cost attribution.

### Platform — authorization plane for non-human actors

Beyond coding agents. Standards alignment as WIMSE/AIMS and ID-JAG settle `[B-46][B-47]`.

### Dependencies

```
MVP(1) ──▶ MVP(2,3) ──▶ MVP(4) ──▶ MVP(5,6)
                            │
                            ▼
         V1: policy+simulation ──▶ V1: hook enforcement ──▶ V1: broker
                            │                                    │
                            ▼                                    ▼
         V1: MCP gateway (Grade A) ────────────────▶ V2: declared-vs-observed
```

**The critical path is MVP(2) — evidence ingest.** If three vendors' event shapes cannot be
reconciled into one action ledger, the capability abstraction is wrong and we learn it in week
two. Build that first.

---

## 8. The CISO objection list

Twenty-eight objections a hostile reviewer would raise, with the honest answer. Where the
answer is "you are right", the architecture changed.

| # | Objection | Answer |
|---|---|---|
| 1 | "Developers will bypass the gateway." | **Correct.** `13` §5 is in the documentation. We grade coverage and estimate the dark population. |
| 2 | "You didn't stop the incident everyone is talking about." | **Correct, in the old design.** D-08 and D-10 are the response. |
| 3 | "Your hooks run on the developer's laptop." | True. That is Grade B, labelled as such. Removal is detected within one heartbeat. |
| 4 | "Cursor sees our code before you do." | True `[B-41]`. We do not claim Cursor prompt DLP (D-11). |
| 5 | "Another proxy in the request path." | Not in the MVP. Read-only, zero latency. |
| 6 | "What if your gateway goes down?" | `13` §8 declares every failure mode. Control plane is never on the path. |
| 7 | "Stale policy after revocation." | Bundle TTL + ≤5 s quarantine + short credential TTL, which degrades better than a revocation list. |
| 8 | "Your DLP will false-positive and my developers will revolt." | Measured FP rate before a rule may block (kept from `07`); MVP does not block. |
| 9 | "False negatives." | Stated: detection reduces risk, never proves absence. |
| 10 | "Compromise of your data plane." | AP-7. Short-lived credentials bound the loss. KMS-wrapped, no API read path. |
| 11 | "Malicious vendor operator." | AP-8. Bundles refuse rollback and refuse to widen permissions without a second signature; activation evidence is written customer-side. |
| 12 | "A customer admin abuses this." | Dual control on payload reveal; all admin actions audited; exceptions must expire. |
| 13 | "Latency." | MVP: none. V1: p95 < 5 ms decision budget, unchanged from `06`. |
| 14 | "Agent behaviour is non-deterministic, so policy is meaningless." | Policy is on **actions**, which are discrete and loggable, not on model behaviour. This is the point of the capability model. |
| 15 | "MCP will be replaced." | D-08 — MCP is one binding. A2A is already governable under the same model `[B-38]`. |
| 16 | "Deployment complexity." | Five modes → three (D-15). |
| 17 | "Data residency claims." | Already honest in `05`; extended. |
| 18 | "Who holds the keys?" | Customer KMS in self-hosted; broker never persists downstream material. |
| 19 | "Multimodal traffic." | Out of scope, stated (D-16). |
| 20 | "Browser and computer-use agents." | Grade E. Listed in the capability registry as ungoverned `[B-15]` §3. |
| 21 | "Local models." | Grade E, bypass row 5. Host-level control is the customer's. |
| 22 | "We already have Palo Alto / CrowdStrike." | They inspect traffic. They cannot tell you the agent was approved at v1.4 and used four capabilities it never declared. |
| 23 | "We already have Microsoft Agent 365." | Excellent for the Microsoft estate. It does not govern Cursor, Claude Code, Codex or your LangGraph services. Treat it as an ingest source. |
| 24 | "Prove you don't store our code." | Schema-level: only digests and facets cross the boundary (`15` §9). Auditable in the open event contract. |
| 25 | "What happens when Anthropic changes the hook API?" | AS-2. Version compatibility matrix; version-pinned collectors; a broken binding is a coverage incident, not a silent failure. |
| 26 | "You can't see CI." | We can, and CI is the best surface we have — customer-controlled, Grade A, highest blast radius. It is in MVP scope. |
| 27 | "Your risk score is a black box." | Risk is categorical for enforcement. The numeric score orders a review queue and never gates an action (`14` §8). |
| 28 | "Give me the evidence for our ISO 42001 audit." | §10 evidence mapping. We emit evidence; we do not become a GRC product. |

---

## 9. Enterprise integrations — classified

**DESIGN DECISION:** everything below "Enterprise v1" is a connector request, not architecture.

| Tier | Integrations |
|---|---|
| **MVP** | Entra ID / Okta (OIDC + SCIM); GitHub + GitHub Enterprise; Claude Code (OTLP + hooks); Cursor (Admin API + hooks); Copilot (audit + metrics API) |
| **Enterprise v1** | Splunk + Microsoft Sentinel (evidence export); GitLab; Bitbucket; Jenkins / Azure DevOps (CI agents); HashiCorp Vault (broker backend); AWS/Azure/GCP workload identity federation; cloud KMS; Jira |
| **Later** | ServiceNow; Datadog; Elastic; CrowdStrike; CyberArk; MDM/Intune posture signals; CAEP/SSF receiver `[B-67]`; A2A registry |
| **Not necessary** | LDAP direct (SCIM covers it); Ping/Keycloak as bespoke work (generic OIDC covers them); every LLM observability vendor |

---

## 10. Compliance evidence mapping

**DESIGN DECISION:** we emit evidence. We do not manage controls, audits or attestations.

| Framework | What our evidence naturally supports | What it does not |
|---|---|---|
| **NIST AI RMF / AI 600-1** `[B-57]` | MAP: AI asset inventory with ownership and provenance. MEASURE: action ledger, policy violations, coverage. MANAGE: approval and quarantine records. | GOVERN — organisational policy is the customer's |
| **ISO/IEC 42001** `[B-104]` | Operational control evidence: agent lifecycle, approvals, change records, incident trail | Management-system documentation |
| **SOC 2** | Logical access (grants, approvals), change management (agent versions), monitoring (coverage), incident response (investigation trail) | Everything outside the AI estate |
| **EU AI Act** | Logging and traceability for deployed systems; human oversight records | Classification, conformity assessment, fundamental-rights assessment |
| **GDPR** | Data-class tagging on actions; deletion and retention on evidence; legal hold | Lawful basis, DPIA, subject rights |
| **OWASP Agentic Top 10** `[B-52]` | Direct mapping per threat in `13` §6 | — |

---

## 11. Explicit non-goals

**DESIGN DECISION.** Refusals, with reasons. Each has been considered and rejected.

| # | Not building | Why |
|---|---|---|
| 1 | A general-purpose LLM gateway | LiteLLM is free `[B-16]`; Portkey is inside Palo Alto `[B-17]` |
| 2 | A prompt-injection detection engine | Formally unsolvable at that layer `[B-11]`; >90% bypass under adaptive attack `[B-12]` |
| 3 | A full DLP/CASB engine | Six-vendor consolidated market; we call a detector, we do not build one |
| 4 | An identity provider | We consume Entra/Okta forever |
| 5 | A SIEM | We export. Retention is somebody else's margin. |
| 6 | A GRC / compliance-management platform | We emit evidence (§10) |
| 7 | A secrets manager | We broker against Vault and cloud WIF `[B-69][B-70]` |
| 8 | A model evaluation / prompt management tool | Different buyer, different product |
| 9 | An agent framework or runtime | We govern agents; we do not host them |
| 10 | A code-scanning / SAST product | Crowded; adjacent; not our abstraction |
| 11 | A new policy language | Cedar exists and is formally analysable `[B-73][B-74]` |
| 12 | A new identity format | SPIFFE and OAuth RFCs exist `[B-62][B-49]` |
| 13 | Multimodal DLP (image/audio/video/OCR) | Not until a customer has the traffic |
| 14 | Air-gapped as a first-class mode | Self-hosted variant with a documented procedure (D-15) |
| 15 | Browser/computer-use agent control | Grade E. Inventory it, do not claim it. |
| 16 | An on-premises model-hosting story | Not our problem |

**The test for any new feature:** does it make an AI action more **attributable**, more
**authorizable**, or more **reversible**? If not, it belongs to someone else.

---

## 12. Research-backed opportunities

| # | Opportunity | Evidence |
|---|---|---|
| O-1 | Cross-vendor consolidation — structurally uncopyable by client vendors | `[B-31]…[B-37]` |
| O-2 | Credential brokering for agents; the reference-incident root cause | `[B-01][B-101]` |
| O-3 | Enforcement grading as a trust instrument | `13` §5; nobody publishes what they cannot see |
| O-4 | CI agents: highest blast radius, best achievable grade, under-served | `[B-07]`; `13` §5 row 11 |
| O-5 | Declared-vs-observed reconciliation as a moat | `../docs/design/01-agent-composition.md` |
| O-6 | Session taint as an enforceable trifecta control | `[B-60][B-61]` |
| O-7 | The SDLC join: action → commit → PR → release | No competitor in `16` holds it |
| O-8 | Standards-alignment lead while WIMSE/AIMS and ID-JAG settle | `[B-46][B-47][B-48]` |

---

## 13. Risks

| # | Risk | Likelihood | Response |
|---|---|---|---|
| R-1 | Endor Labs owns the wedge first `[B-44]` | **Medium-high** | Differentiate on brokering, grading, CI and declared-vs-observed. Move on evidence now. |
| R-2 | Microsoft extends Agent 365 across vendors `[B-37]` | Medium | Unlikely — they would govern competitors. Be the ingest layer. |
| R-3 | Vendor APIs change or close (AS-2) | Medium | Compatibility matrix; pinned collectors; coverage incidents |
| R-4 | Grade B rejected as a control (bet T-5) | **Medium** | Would collapse the product to broker + MCP. **Ask in design-partner conversation one.** |
| R-5 | No budget line exists (bet T-2) | Medium | Attach to incident-response readiness or AI cost attribution |
| R-6 | Free OSS ledger appears | Medium | The moat must be brokering, grading and the SDLC join, never the collector |
| R-7 | Build capacity vs scope | **High** | The MVP is now six items, not nine phases. Hold the line. |
| R-8 | Enterprises standardise on one client (bet T-1) | Low | Test in conversation one |

---

## 14. Open questions

Mirrored into the README table.

| ID | Question | Recommendation | Blocked by |
|---|---|---|---|
| Q-H | SDK middleware for in-house agents in MVP? | No — harness bindings first | Design partner's agent mix |
| Q-I | How deep to parse `shell.exec` argv? | Binary + flags + hosts + paths; no shell grammar | — |
| Q-J | Inventory `browser.act` at permanent Grade E? | Yes — honest gap beats silent gap | — |
| Q-K | Is `retrieval.query` MVP? | No, unless a partner has RAG in production | Design partner |
| Q-L | Read-only MVP, or blocking from day one? | **Read-only** — no architecture review, no latency, and it sells the next phase | Bet T-4 |
| Q-M | Which client first if only one? | **Claude Code** — best enforcement surface `[B-31][B-32]` — but breadth *is* the thesis | Bet T-1 |
| Q-N | Is credential brokering MVP or V1? | **V1.** Use the MVP ledger to prove the exposure first | Bet T-2 |
| Q-O | Is our differentiation enough against Endor Labs? | Unknown | Design partner |
| Q-P | Who signs the contract — platform, AppSec or CISO? | Unknown; evidence says budget ownership is unsettled `[B-14]` | Design partner |

---

## 15. Recommended next experiments

**Before writing any more code.** Ordered; each is cheap and each can falsify the thesis.

| # | Experiment | Falsifies | Cost |
|---|---|---|---|
| E-1 | Five conversations with engineering leaders running 2+ AI clients. One question: *"Can you tell me what your coding agents did last week?"* Say nothing else. | T-1, T-2 | Days |
| E-2 | Prototype the three-vendor ingest (Claude OTLP + Cursor Admin API + Copilot audit) against one real org. Can they reconcile to one ledger? | **The capability abstraction itself** | 1–2 weeks |
| E-3 | Run a credential-exposure scan on one real developer machine. Count reachable long-lived tokens. | The AP-1 premise | Hours |
| E-4 | Show a security architect the Grade A–E table. Ask whether Grade B counts as a control. | **T-5 — the most dangerous bet** | One meeting |
| E-5 | Ask three prospects to react to $9/developer/month. | Pricing hypothesis | Three calls |
| E-6 | Install Endor Labs' agent governance. Understand exactly what it does and does not do. | R-1 | Days |

**E-2 and E-4 are the two that matter.** E-2 tests whether the architecture is right. E-4
tests whether the product is sellable. Both can be done before Phase 1.

---

## 16. Sources

Full bibliography with source grading in [`18-bibliography.md`](18-bibliography.md).

**Counted:** 108 source entries · 31 competitors and products · 24 standards, RFCs and drafts ·
16 major architectural areas reviewed.

**Found:** 16 missing capabilities · 12 security gaps · 6 commercial gaps · 11 questionable
assumptions changed via decision records D-08 to D-18.
