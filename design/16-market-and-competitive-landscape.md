# 16 · Market and competitive landscape

> Written 2026-09-22. Sources in [`18-bibliography.md`](18-bibliography.md), cited as `[B-nn]`.
> Tags: **FACT** · **SOURCE-BACKED** · **VENDOR CLAIM** · **INFERENCE** · **HYPOTHESIS** · **OPEN**.
>
> Rule for this document: a capability is a **vendor claim** unless a primary source
> establishes it. Marketing pages are cited as marketing.

---

## 1. Consolidation — the market's own verdict on where value is

**FACT.** Within roughly fourteen months, the standalone AI-security layer was bought:

| Acquirer | Target | Date | Source |
|---|---|---|---|
| Palo Alto Networks | Protect AI | Jul 2025 | `[B-17]` |
| Palo Alto Networks | **Portkey** (LLM gateway) | closed 2026-05-29 | `[B-17]` |
| SentinelOne | Prompt Security | Aug 2025 | `[B-23]` |
| Cato Networks | Aim Security | Sep 2025 | `[B-24]` |
| Check Point | Lakera | Sep 2025 | `[B-25]` |
| F5 | CalypsoAI (~$180M) | Sep 2025 | `[B-26]` |
| CrowdStrike | Pangea | 2025 | `[B-27]` |
| Okta | Permiso (~$200M) | 2025 | `[B-28]` |
| Fortinet | Virtue AI | 2026 | `[B-28]` |
| Snowflake | Natoma (MCP identity, ~$110M) | May 2026 | `[B-19]` |
| A10 Networks | TrojAI | 2026-06-15 | `[B-79]` |
| Cisco | Robust Intelligence → AI Defense | 2024 → GA 2025-26 | `[B-80]` |

**INFERENCE — two readings, both true.**

*Validating:* platform vendors paid real money, so the problem is real and budgeted.

*Cautionary:* the things they bought are **prompt inspection and LLM proxying**. Those
functions are now bundles inside platforms an enterprise already owns. Competing there means
competing with a free add-on to an existing contract. What was **not** consolidated is
cross-vendor agent action evidence and credential mediation — which is where
[`12-strategic-thesis.md`](12-strategic-thesis.md) points the product.

---

## 2. Competitor map

### 2.1 LLM / AI gateways — **commodity**

| Product | Model | Price evidence | Note |
|---|---|---|---|
| LiteLLM | MIT, self-host | **Free at any scale** `[B-16]` | The price floor. Any gateway must beat free. |
| Portkey | Now Palo Alto Prisma AIRS | Dev $0 / Pro **$49/mo** (100k logs) `[B-81]` | FACT (published) |
| TrueFoundry | AI + MCP gateway | **$0 / $499 / $2,999 per month** `[B-82]` | FACT (published) |
| Kong AI Gateway | Add-on | **$100/mo per unique LLM model** proxied `[B-83]` | FACT (published) |
| Bedrock Guardrails | AWS native | **$0.15 / 1,000 text units** `[B-29]` | FACT |
| Model Armor | Google native | 2M tokens/mo free, then **$0.10/1M** `[B-30]` | FACT |

**INFERENCE:** this row is a feature, not a company. `design/05` should be scoped to exactly
what is needed for attribution and enforcement, and nothing more.

### 2.2 MCP gateways — **commoditising fast**

| Product | Licence | Price | Note |
|---|---|---|---|
| Obot | **MIT** | Free; **$35M seed** behind it `[B-18]` | Well-funded free competitor |
| IBM ContextForge | OSS | Free `[B-20]` | Registry + proxy + plugins + OTel |
| Solo.io agentgateway | OSS (LF) | Free core, paid support `[B-21]` | MCP + A2A + LLM |
| Docker MCP Gateway | Apache-2.0 | Free `[B-22]` | Local developer surface |
| MintMCP | Commercial | **$1,250/mo for 50 seats**, +$25/seat `[B-84]` | VENDOR-PUBLISHED |
| Microsoft Agent 365 | Commercial | **$15/user/month** `[B-37]` | FACT — the pricing anchor |
| Arcade.dev | Commercial | Usage-based, **no public tiers** `[B-85]` | |

**INFERENCE:** shipping "an MCP gateway" as the product is not viable. Shipping MCP mediation
as *one binding* inside a capability model, with evidence and credential brokering attached,
is a different proposition.

### 2.3 AI runtime / application security

| Vendor | Sells | Funding | Overlap |
|---|---|---|---|
| **Zenity** | Agent security + governance; SaaS-agent posture and inline runtime; endpoint agent | **$125M Series C**, 2026-08-03; ~$185M total `[B-86]` | **High** — closest to "agent governance" as a category |
| **WitnessAI** | AI visibility + intent-based policy across employees and agents | **$58M Series B**, 2026-01 `[B-87]` | Medium — network-shaped |
| **Noma Security** | AI-SPM + runtime + red teaming | $100M Series B `[B-88]` | Medium |
| **HiddenLayer** | Model supply chain + runtime; 2026 coding-agent harness protection | ~$56M documented; $100M Series B is **vendor claim** `[B-89]` | Medium |
| **Lasso Security** | Guardrails inline at gateways | $30M, 2026-09 `[B-90]` | Low |
| **Knostic** | Knowledge-layer / oversharing for Copilot + Glean | ~$14M `[B-91]` | Low — different problem |
| **Cisco AI Defense** | Validation + runtime, network-embedded | Cisco | Medium |
| **Microsoft Agent 365 + Purview + Defender** | Agent registry, Entra agent identity, DLP, runtime MCP protection | Microsoft | **Highest strategic threat** `[B-37][B-92]` |

**FACT** `[B-92]` Microsoft Defender now provides real-time protection for Agent 365 MCP tool
invocation, and from 2026-07-01 Copilot Studio / Foundry agent security requires an Agent 365
licence.

**INFERENCE — the Microsoft problem, stated honestly.** At $15/user/month bundled into an
existing E5 relationship, Microsoft will win the default. The counter is not features; it is
**scope**. Agent 365 governs the Microsoft agent estate. It does not govern Cursor, Claude
Code, Codex CLI or a LangGraph service on EKS. Any positioning that competes *with* Microsoft
loses; positioning that **consolidates across Microsoft and everything else** is coherent, and
should treat Agent 365 as an ingest source rather than a rival.

### 2.4 AI engineering analytics — adjacent, different buyer

| Vendor | Pricing evidence |
|---|---|
| LinearB | **$29 / $59 per contributor/month** `[B-93]` — FACT, published |
| DX | Per-developer, list not published; **median ACV ~$52k** per third-party deal data `[B-94]` — ESTIMATE |
| Faros AI | No public price; ~$150k/yr entry per third-party `[B-95]` — ESTIMATE |
| Jellyfish | Enterprise custom |
| Cursor AI Code Tracking API | Enterprise-only, Alpha `[B-39]` — FACT |
| GitHub Copilot metrics | GA 2026-02-27 `[B-40]` — FACT |

**INFERENCE:** these own the **CTO/VP Engineering** budget and measure *productivity*. They do
not do authorization, credentials or enforcement. They are a **channel and a comparison
anchor**, not a competitor — but they prove a per-developer price point exists and is paid.

### 2.5 Agent action governance in the SDLC — **the actual competitive set**

| Player | What it does | Evidence |
|---|---|---|
| **Endor Labs — Coding Agent Governance** | Hooks into Claude Code / Cursor / Codex calling `endorctl ai-audit`; agent inventory; centralised audit; **block / alert / ask-permission**; redaction before cloud | `[B-44]` — vendor documentation |
| **Vorlon** | "AI Agent Flight Recorder" + Action Center, cross-app trail | `[B-45]` — VENDOR CLAIM |
| **Project AIR** | Signed intent capsules, Rekor transparency-log anchoring | `[B-96]` — OSS |
| Cycode / Apiiro / Legit / Ox | AI-BOM, MCP config posture, ADLC guardrails | vendor docs |
| GitHub / GitLab native | Agent session telemetry, PR attribution | `[B-40]` |

**This is the honest competitive assessment.** **SOURCE-BACKED** `[B-44]` Endor Labs is
already doing hook-based coding-agent governance with pre-action permission prompts. We are
not first to the wedge. Differentiation must be **specific and defensible**:

| Their position | Our required differentiation |
|---|---|
| AppSec platform, agents as a module | Agent actions as the product; depth over breadth of scanner |
| Hook-based interposition | Same, **plus** Grade A credential brokering — the AP-1 control |
| Audit | Audit **graded** A/B/C/D/E with an estimated dark population |
| Coding agents | Coding agents **plus CI agents plus in-house agents** under one capability model |
| Inventory | Inventory joined to **approved version**: declared vs observed |

**OPEN (Q-O):** is that differentiation enough against an incumbent with an existing AppSec
footprint and a sales team? This is the question a design partner answers, not a document.

---

## 3. Positioning

```
                    CROSS-VENDOR COVERAGE
                             ▲
                             │
  Faros · DX · Jellyfish     │     ◆ TARGET POSITION
  LinearB                    │     cross-vendor agent action
  (observe, many tools,      │     evidence + graded enforcement
   no enforcement)           │     + credential brokering
                             │
  ───────────────────────────┼───────────────────────────▶
  OBSERVE                    │                     ENFORCE
                             │
  Cursor Analytics           │     Microsoft Agent 365
  Copilot metrics            │     Cursor Enterprise
  (observe, one vendor)      │     Claude managed settings
                             │     Endor Labs (partial cross-vendor)
                             ▼
                    SINGLE-VENDOR
```

**INFERENCE:** the upper-right quadrant is genuinely thin. Endor Labs is the only player with
a real claim to it, and their centre of gravity is AppSec scanning. Microsoft is powerful and
structurally confined to the lower-right. The analytics vendors are structurally confined to
the upper-left because enforcement is not their buyer's problem.

---

## 4. Category and buyer

**FACT** `[B-97]` Gartner published a **Market Guide for AI TRiSM** (2025-02-18) — a Market
Guide, not a Magic Quadrant. **SOURCE-BACKED** `[B-98]` In September 2026 Gartner published an
**Emerging Market Quadrant for AI Application Security**, with mandatory capabilities of
discovery, automated testing, runtime defence and cloud AI coverage.

**INFERENCE:** the buying language in 2026 has moved from "AI TRiSM" (board and regulator
framing) toward **"AI application security"** and **"agent governance"** (operational framing).
"AI control plane" is **not** a category buyers search for. **DESIGN DECISION:** rename the
external product framing. Internally the documents may keep their filenames; externally the
product is an **agent action governance and evidence platform**. The first line of the website
should be the question in `12` §1, not an architecture noun.

### Buyer

| Role | Cares about | Evidence |
|---|---|---|
| **Platform / DevEx leadership** | Which agents run, what they cost, what they broke | Owns the tools already; fastest path to a pilot |
| **AppSec / product security** | Can an agent reach prod, what did it do | The technical champion |
| **CISO** | Board question, incident readiness, evidence | Budget, but a longer cycle |
| **CFO / FinOps** | Per-team AI spend | Secondary; funds it when attribution is credible |
| **Blocker: enterprise architecture / procurement** | Latency, availability, data residency, another agent on the laptop | **Read-only MVP exists to avoid this review entirely** |

**FACT** `[B-14]` Among the IANS 2026 cohort (n=113), **81%** of "optimistic" CISOs own the AI
security budget versus 50% of pessimistic ones — **INFERENCE:** budget ownership is still
being decided, which favours a champion-led land over a top-down CISO sale.

**FACT** `[B-99]` ~90% of CISOs expect AI security spending to rise, frequently by
**reallocating** existing budget. **INFERENCE:** we are more likely competing for an existing
line item than creating one — which argues for displacing nothing and attaching to an existing
pain (evidence for an incident, or a cost question) rather than proposing a new category.

---

## 5. Pricing

### 5.1 Anchors — FACT, published

| Anchor | Price |
|---|---|
| Microsoft Agent 365 | **$15 / user / month** `[B-37]` |
| GitHub Copilot Business / Enterprise | **$19 / $39 per user / month** `[B-100]` |
| LinearB | **$29 / $59 per contributor / month** `[B-93]` |
| TrueFoundry | **$499 / $2,999 per month** `[B-82]` |
| MintMCP | **$1,250 / month for 50 seats** ≈ $25/seat `[B-84]` |
| Bedrock Guardrails | **$0.15 / 1,000 text units** `[B-29]` |

### 5.2 Metric choice

| Metric | Verdict |
|---|---|
| Per governed action | **Reject.** Punishes adoption; the customer's incentive becomes fewer governed actions. Actively harmful to security. |
| Per agent | **Reject.** Agents are cheap to create and the count is unstable. Penalises the decomposition we want. |
| Per million events | **Reject as primary.** Same problem, plus unforecastable. |
| **Per developer with an enrolled agent** | **Adopt.** Tracks value, is forecastable, matches how the adjacent tools in §2.4 are already bought, and is a line the buyer already has. |
| Platform fee + per developer | **Adopt for enterprise.** Covers deployment and integrations. |

**DESIGN DECISION:** price per developer whose agents we govern. Free, unlimited **discovery**
— seeing the estate should never cost money, because discovery is what creates the urgency
that sells the rest.

### 5.3 Hypothesis — clearly labelled

**HYPOTHESIS. These are proposals, not market facts. No customer has validated them.**

| Developers | List $/dev/mo | Platform | Indicative annual | Positioning |
|---|---|---|---|---|
| 100 | 12 | — | ~$14k | Land; single team; credit card if possible |
| 1,000 | 9 | $25k | ~$133k | Typical first enterprise contract |
| 10,000 | 6 | $60k | ~$780k | Multi-BU; self-hosted |
| 50,000 | 4 | $150k | ~$2.55M | Global; regional deployments |

Sanity check: at 1,000 developers this is roughly **60% of the Agent 365 seat price** `[B-37]`
and **under a third of Copilot Enterprise** `[B-100]` — defensible as "a fraction of what you
already pay for the tools we are governing." **INFERENCE:** if the product cannot be justified
at under half the price of the tool it governs, the value story is wrong.

---

## 6. White space

Evidence-based. Each is a gap **because** of a cited fact, not because it sounds unserved.

1. **Cross-vendor consolidation.** Vendor-native governance is excellent and single-vendor
   `[B-31]…[B-37]`. Structural, uncopyable by the incumbents.
2. **The measured policy–enforcement gap.** 66% have policy; ~15–31% have runtime controls
   `[B-14]`. The gap is quantified in a survey a CISO will recognise.
3. **Credential mediation for agents.** **FACT** `[B-101]` CSA 2026: >16% of organisations do
   not track AI-related identity creation; ~20% have formal API-key offboarding. The AP-1 root
   cause is an industry-wide unsolved operational problem.
4. **Tamper-evident approval-to-action binding across vendors.** Emerging (Endor, Vorlon,
   Project AIR `[B-44][B-45][B-96]`), no standard, no dominant player.
5. **`shell.exec` and `net.http` as governed capabilities.** No vendor in this document
   governs the agent's shell as a first-class, policy-evaluated capability with evidence. This
   is the PocketOS surface and it is empty.
6. **Honest coverage accounting.** Nobody publishes what they cannot see. Grading (§`12`.5) is
   differentiating precisely because admitting Grade E contradicts every incumbent's pitch.

---

## 7. Risks to this position

| Risk | Likelihood | Response |
|---|---|---|
| Microsoft extends Agent 365 to third-party coding agents | **Medium** | They would have to govern competitors' tools; more likely they ingest. Be the ingest layer. |
| Endor Labs wins the coding-agent-governance category first | **Medium-high** | Differentiate on credential brokering + grading + CI + declared-vs-observed. Move fast on evidence. |
| Vendors close the hook/telemetry APIs we depend on | **Low-medium** | They are shipping *more* enterprise surface, not less `[B-31]…[B-36]`. But AS-2 in the threat model is real: pin versions, maintain a compatibility matrix. |
| Enterprises standardise on one AI client | **Low** | Contradicted by current multi-tool reality, but it is thesis bet T-1 — test it in conversation one. |
| Category never gets its own budget line | **Medium** | Attach to an existing line: incident response readiness, or AI cost attribution. |
| A free OSS project does the ledger | **Medium** | Likely. The moat must be brokering, grading and the SDLC join — not the collector. |
