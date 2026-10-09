# 18 · Research bibliography

All sources accessed **2026-09-22** unless stated otherwise. Cited as `[B-nn]` throughout
`12`–`17`.

**Source grading**

| Grade | Meaning |
|---|---|
| **P** | Primary — RFC, standards body, official vendor documentation, vendor incident post |
| **S** | Secondary — reputable reporting, peer-reviewed or preprint research, analyst material |
| **V** | Vendor marketing or vendor-authored claim. Never treated as a technical fact. |

> Where a source is graded **V**, the corresponding claim in `12`–`17` is labelled
> "VENDOR CLAIM" or attributed by name. Where a spec is a draft, the draft revision and expiry
> are stated, because a draft is not a standard.

---

## The reference incident

| ID | Grade | Source | What it establishes |
|---|---|---|---|
| B-01 | **P** | Railway engineering blog, *"Your AI wants to nuke your database. Guardrails fix that."* — https://blog.railway.com/p/your-ai-wants-to-nuke-your-database | **The infrastructure provider's own account.** The agent "found a Railway API token stored locally on the user's machine and used it to call `volumeDelete` on a production volume"; the API "honored it the same way it would for a CLI command or a CI pipeline." Railway subsequently made all API deletes soft-delete for 48 hours. |
| B-02 | **S** | AI Incident Database, Incident 1469 / Report 7311 — https://incidentdatabase.ai/reports/7311/ | Independent incident registry entry. Date 2026-04-25, Cursor + Claude Opus 4.6, token provisioned for custom-domain management carried blanket GraphQL authority, exact `curl` against `backboard.railway.app/graphql/v2`, backups co-located in the deleted volume. |
| B-03 | **S** | Vectara, *awesome-agent-failures* case study — https://github.com/vectara/awesome-agent-failures/blob/main/docs/case-studies/pocketos-cursor-database-wipe.md | Corroborating write-up; ~30-hour outage; Railway CEO restored data from underlying snapshots ~2 days later. |

**Note on B-01.** This is graded **P** and is the strongest of the three, because it is the
infrastructure vendor describing its own API's behaviour and the remediation it shipped. The
conclusion drawn in `12` §2.1 — that the failure was credential scope and harness mediation,
not model quality — is Railway's framing as much as ours.

---

## Standards, frameworks and threat taxonomies

| ID | Grade | Source | Establishes |
|---|---|---|---|
| B-52 | **P** | OWASP, *Top 10 for Agentic Applications 2026* — https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/ (pub. 2025-12-09) | `ASI01` Agent Goal Hijack … `ASI10` Rogue Agents |
| B-53 | **P** | OWASP Agentic Security Initiative, *Agentic AI — Threats and Mitigations* | `T1` Memory Poisoning … `T15` Human Manipulation |
| B-54 | **P** | OWASP, *Top 10 for LLM Applications 2026* — https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/ (pub. 2026-08) | `LLM01` Prompt Injection … `LLM10`; `LLM03` is now Excessive Agency |
| B-55 | **P** | Cloud Security Alliance, MAESTRO — https://cloudsecurityalliance.org/blog/2025/02/06/agentic-ai-threat-modeling-framework-maestro (2025-02-06) | Seven-layer agentic threat model; cross-layer analysis |
| B-56 | **P** | MITRE ATLAS — https://atlas.mitre.org/ | Adversarial tactics/techniques; agent tool-invocation and context-poisoning techniques added Oct 2025 |
| B-57 | **P** | NIST AI 600-1, *Generative AI Profile* — https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence (2024-07-26) | Twelve GAI risk categories |
| B-58 | **P** | NIST AI 100-2e2025 — https://csrc.nist.gov/pubs/ai/100/2/e2025/final (2025-03-24) | Adversarial ML taxonomy incl. indirect prompt injection |
| B-102 | **P** | NIST, Control Overlays for Securing AI Systems (COSAiS) — https://csrc.nist.gov/Projects/cosais | Planned NISTIR 8605D covers single- and multi-agent systems; **not yet published** |
| B-103 | **P** | NIST SP 800-207, *Zero Trust Architecture* — https://nvlpubs.nist.gov/nistpubs/SpecialPublications/NIST.SP.800-207.pdf | PDP/PEP separation |
| B-104 | **P** | ISO/IEC 42001 — AI management systems | Referenced for evidence mapping in `17` |

---

## Prompt injection — what is and is not achievable

| ID | Grade | Source | Establishes |
|---|---|---|---|
| B-11 | **S** | *On the Inseparability of Instructions and Data* — https://arxiv.org/html/2606.27567 (2026-06) | Formal argument that perfect prompt-injection prevention is unachievable in shared-embedding models without enforced control/data separation |
| B-12 | **S** | Nasr et al., *The Attacker Moves Second*, USENIX Security '26 — https://www.usenix.org/system/files/usenixsecurity26-nasr.pdf | **>90% attack success rate** against multiple deployed commercial defences under adaptive attack, versus near-0% under static evaluation |
| B-13 | **V→S** | Anthropic, *Mitigating prompt injections in browser use* — https://www.anthropic.com/research/prompt-injection-defenses (2025-11-24) | Vendor research: states the problem is "far from solved"; ~1% ASR against a 100-attempt attacker with safeguards |
| B-60 | **S** | Simon Willison, *The lethal trifecta* — https://simonwillison.net/2025/jun/16/the-lethal-trifecta/ (2025-06-16) | Private data + untrusted content + external communication = exfiltration risk. Source of the session-taint control in `13` §7 |
| B-61 | **S** | Debenedetti et al., *Defeating Prompt Injections by Design* (CaMeL) — https://arxiv.org/html/2503.18813v2 | Capability/dual-LLM enforcement; 77% task success with provable security vs 84% undefended |
| B-105 | **S** | AgentDojo — https://arxiv.org/pdf/2406.13352 | Detector efficacy and the utility cost of false positives |
| B-106 | **P** | Google Security blog, *Prompt injections on the web* — https://blog.google/security/prompt-injections-web/ | +32% malicious indirect-injection content on the static web, Nov 2025 → Feb 2026 |

---

## Documented incidents and vulnerabilities

| ID | Grade | Source | Establishes |
|---|---|---|---|
| B-04 | **S** | EchoLeak analysis, **CVE-2025-32711** — https://simonwillison.net/2025/Jun/11/echoleak/ | Zero-click exfiltration from M365 Copilot via email-borne indirect injection |
| B-05 | **S** | Invariant Labs, GitHub MCP exploit — https://invariantlabs.ai/blog/mcp-github-vulnerability (2025-05-26) | Malicious public issue → agent leaks private repository data |
| B-06 | **S** | CSA research note on MCP tool poisoning, **CVE-2025-54136** (Cursor "MCPoison") — https://labs.cloudsecurityalliance.org/research/csa-research-note-mcp-tool-poisoning-ai-agent-exfiltration-2/ | Tool definition mutated after user approval |
| B-07 | **S** | CSA research note, "Clinejection" — https://labs.cloudsecurityalliance.org/research/csa-research-note-clinejection-prompt-injection-cicd-cache-p/ (2026-02) | Issue title → CI agent injection → npm token → malicious package to ~4k machines |
| B-08 | **S** | OX Security, MCP supply-chain advisory — https://www.ox.security/blog/mcp-supply-chain-advisory-rce-vulnerabilities-across-the-ai-ecosystem/ | 2026 wave of MCP STDIO command-injection RCEs |
| B-09 | **S** | Reporting on **CVE-2026-59822** (LiteLLM MCP Streamable-HTTP auth bypass), added to CISA KEV 2026-09-02 | Auth bypass in a widely deployed gateway; KEV listing means observed exploitation |
| B-10 | **S** | Cisco, persistent memory compromise in Claude Code — https://blogs.cisco.com/ai/identifying-and-remediating-a-persistent-memory-compromise-in-claude-code | Malicious npm postinstall wrote to `MEMORY.md`/hooks; fixed in v2.1.50 |
| B-59 | **S** | Invariant Labs, MCP tool poisoning attacks — https://invariantlabs.ai/blog/mcp-security-notification-tool-poisoning-attacks (2025-04-01) | Tool-description poisoning, rug pulls, cross-server tool shadowing |

---

## Client enforcement surfaces (official vendor documentation)

| ID | Grade | Source | Establishes |
|---|---|---|---|
| B-31 | **P** | Claude Code hooks reference — https://docs.anthropic.com/en/docs/claude-code/hooks | `PreToolUse`, `PostToolUse`, `ConfigChange`, `SessionStart`, `SubagentStart` and others; **exit code 2 blocks**; `permissionDecision: allow/deny/ask/defer`; hook commands run unsandboxed |
| B-32 | **P** | Claude Code managed settings — https://code.claude.com/docs/en/managed-settings | Precedence: server-managed > MDM > managed files > HKCU; **local admin can edit managed files**; server-managed may not apply when `ANTHROPIC_BASE_URL` is non-Anthropic |
| B-77 | **P** | Claude Code permissions — https://code.claude.com/docs/en/permissions | `allow`/`ask`/`deny` syntax; `allowManagedPermissionRulesOnly`; `disableBypassPermissionsMode`; deny > ask > allow |
| B-107 | **P** | Claude Code sandboxing — https://code.claude.com/docs/en/sandboxing | Bash-only OS isolation; `allowedDomains`, `strictAllowlist`, `allowManagedDomainsOnly`. **`WebFetch` and MCP are not on the same sandbox network path.** |
| B-34 | **P** | Claude Code monitoring usage — https://code.claude.com/docs/en/monitoring-usage | OTLP export, managed `env`, `tool_decision` / `tool_result` events, `OTEL_LOG_TOOL_DETAILS` |
| B-33 | **P** | Cursor hooks — https://cursor.com/docs/hooks | `preToolUse`, `beforeShellExecution`, `beforeMCPExecution`, `afterFileEdit`, `subagentStart`; exit 2 denies; **default is fail-open**, `failClosed: true` must be set; Enterprise > Team > Project > User |
| B-42 | **P** | Cursor enterprise model and integration management — https://cursor.com/docs/enterprise/model-and-integration-management | Dashboard MCP allowlist; precedence **replaces, not merges**; BYOK disable; forced privacy mode |
| B-39 | **P** | Cursor Admin API / AI Code Tracking — https://cursor.com/docs/api · https://cursor.com/docs/account/teams/ai-code-tracking-api | `filtered-usage-events` (hourly aggregates), spend, `model-access` GET/PUT; AI Code Tracking is Enterprise-only, Alpha |
| B-41 | **P** | Cursor documentation on API keys | *"Even if you use your API key, your requests will still go through our backend! That's where we do our final prompt building."* |
| B-43 | **P** | Cursor MCP — https://cursor.com/docs/mcp | Cursor is a direct MCP client for remote servers; sandbox network modes |
| B-35 | **P** | GitHub Copilot policies, content exclusion, network settings — https://docs.github.com/en/copilot/concepts/network-settings | Content exclusion **not supported in agent mode**; TLS inspection only with a corporate root CA installed on the device |
| B-36 | **P** | Copilot enterprise managed settings reference — https://docs.github.com/copilot/reference/enterprise-managed-settings-reference | `allowedMcpServers` **intersection**, `deniedMcpServers` **union**, `allowManagedMcpServersOnly` |
| B-78 | **P** | Copilot cloud agent firewall — https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-the-agent-firewall | Default and custom egress allowlist; **disabled on self-hosted runners** |
| B-40 | **P** | Copilot usage metrics API + agentic audit log — https://docs.github.com/en/enterprise-cloud@latest/rest/copilot/copilot-usage-metrics · https://github.blog/changelog/2026-02-27-copilot-metrics-is-now-generally-available/ | GA 2026-02-27; `actor:Copilot` audit events, 180-day retention |
| B-76 | **P** | OpenAI Codex advanced configuration — https://developers.openai.com/codex/config-advanced | `openai_base_url` in `~/.codex/config.toml`; `OPENAI_BASE_URL` env removed; project config **ignores** `openai_base_url` and `otel`; `codex.tool_decision` events |
| B-108 | **P** | Gemini CLI configuration and sandbox — https://google-gemini.github.io/gemini-cli/docs/cli/sandbox.html | System-wide `settings.json`; `sandboxNetworkAccess` defaults false |

---

## Identity, delegation and authorization standards

| ID | Grade | Source | Establishes |
|---|---|---|---|
| B-49 | **P** | **RFC 8693** OAuth 2.0 Token Exchange — https://www.rfc-editor.org/info/rfc8693 | Delegation (`sub` + `act`) vs impersonation; nested actor chains |
| B-50 | **P** | **RFC 9449** DPoP — https://www.rfc-editor.org/rfc/rfc9449.html | Application-layer sender-constrained tokens |
| B-51 | **P** | **RFC 8705** mTLS client auth and certificate-bound tokens — https://www.rfc-editor.org/rfc/rfc8705.pdf | Certificate-bound access tokens |
| B-63 | **P** | **RFC 8707** Resource Indicators — https://www.rfc-editor.org/info/rfc8707/ | Audience-binding a token to one resource |
| B-64 | **P** | **RFC 9396** Rich Authorization Requests — https://datatracker.ietf.org/doc/rfc9396/ | Structured `authorization_details` instead of flat scopes |
| B-65 | **P** | **RFC 7523** JWT profile for client authentication and authorization grants — https://www.rfc-editor.org/info/rfc7523 | Signed assertion instead of a static client secret |
| B-62 | **P** | SPIFFE / SPIRE — https://spiffe.io/docs/latest/spiffe-specs/x509-svid/ ; CNCF graduation 2022-09-20 | SPIFFE ID and SVID; workload attestation; short-lived rotation |
| B-46 | **P** | IETF WIMSE — `draft-ietf-wimse-arch` (§3.4.11 AI/ML intermediaries, multi-hop delegation, context re-binding); `draft-ietf-wimse-aims-00` — https://datatracker.ietf.org/doc/draft-ietf-wimse-arch/ | **Working-group drafts, not RFCs.** Source of the per-hop re-binding rule |
| B-47 | **P** | OAuth Identity Assertion Authorization Grant (Cross-App Access) — https://datatracker.ietf.org/doc/draft-ietf-oauth-identity-assertion-authz-grant/ | **`draft-04`, updated 2026-05-21, expires 2026-11-22.** Not a dependency |
| B-66 | **P** | MCP authorization specification, revision `2026-07-28` — https://modelcontextprotocol.io/specification/2026-07-28/basic/authorization | MCP servers are OAuth 2.1 resource servers; mandates RFC 9728 and RFC 8707. **OAuth 2.1 is itself still a draft.** |
| B-48 | **P** | MCP `enterprise-managed-authorization` extension — https://blog.modelcontextprotocol.io/posts/enterprise-managed-auth/ | Declared **Stable 2026-06-18**; profiles ID-JAG for IdP-managed MCP access |
| B-38 | **P/S** | A2A protocol, Linux Foundation — https://www.linuxfoundation.org/press/a2a-protocol-surpasses-150-organizations-lands-in-major-cloud-platforms-and-sees-enterprise-production-use-in-first-year (2026-04-09) | 150+ organisations, v1.0; Agent Cards; auth delegated to OAuth/OIDC/mTLS; signed cards |
| B-67 | **P** | OpenID CAEP 1.0 Final — https://openid.net/specs/openid-caep-1_0-final.html (approved 2025-08-29) | `session-revoked`, `credential-change`, `risk-level-change` security event tokens |
| B-68 | **S** | WorkOS, multi-hop delegation for AI agents — https://workos.com/blog/oauth-multi-hop-delegation-ai-agents | Nested `act` claims are informational and must not be the sole basis for access decisions |
| B-69 | **P** | HashiCorp Vault SPIFFE auth — https://developer.hashicorp.com/vault/docs/auth/spiffe | SVID-based authentication to Vault; dynamic secrets |
| B-70 | **P** | Google Cloud Workload Identity Federation — https://docs.cloud.google.com/iam/docs/workload-identity-federation | OIDC assertion → short-lived cloud credentials |
| B-71 | **P** | OpenFGA, AI agent authorization — https://openfga.dev/docs/use-cases/ai-agent-authorization | Agents as first-class principals; `can_act_on_behalf_of`; task-scoped tuples |
| B-72 | **S** | Agent Identity Protocol — https://datatracker.ietf.org/doc/html/draft-prakash-aip-01 ; survey https://arxiv.org/html/2603.24775v1 | Capability tokens (macaroons, Biscuit) for attenuated multi-hop delegation |
| B-73 | **P** | AWS Cedar — https://github.com/cedar-policy/cedar | `principal / action / resource / context`; deny by default |
| B-74 | **P** | AWS, Cedar Analysis — https://aws.amazon.com/blogs/opensource/introducing-cedar-analysis-open-source-tools-for-verifying-authorization-policies/ (2025) | SMT compilation; machine-checked Lean proofs; equivalence and always-allow/deny analysis |
| B-75 | **S** | Comparative analyses of Cedar and OPA/Rego for authorization workloads | Rego is more general and harder to verify/bound |
| B-101 | **P** | CSA, non-human identity and agentic AI governance whitepaper (2026-05) — https://labs.cloudsecurityalliance.org/ | >16% of organisations do not track AI-related identity creation; ~20% have formal API-key offboarding |

---

## Market, competition and pricing

| ID | Grade | Source | Establishes |
|---|---|---|---|
| B-16 | **P** | LiteLLM — MIT licence, self-hostable | The price floor for LLM gateways is zero |
| B-17 | **P/S** | Palo Alto Networks acquisitions of Protect AI (2025-07) and Portkey (closed 2026-05-29) into Prisma AIRS | Consolidation of gateway + AI security |
| B-18 | **S** | Obot — $35M seed for an MIT-licensed MCP gateway | Well-funded free competitor in MCP mediation |
| B-19 | **S** | Snowflake acquires Natoma (~$110M, 2026-05) | MCP identity consolidated into a data platform |
| B-20 | **P** | IBM ContextForge — https://github.com/ibm/mcp-context-forge | Free OSS MCP registry/proxy with plugins and OTel |
| B-21 | **P** | Solo.io agentgateway — https://www.solo.io/products/agentgateway | OSS MCP + A2A + LLM gateway, LF-hosted |
| B-22 | **P** | Docker MCP Gateway — https://docs.docker.com/ai/mcp-catalog-and-toolkit/mcp-gateway/ | Apache-2.0, free |
| B-23 | **S** | SentinelOne acquires Prompt Security (2025-08) | |
| B-24 | **S** | Cato Networks acquires Aim Security (2025-09) | |
| B-25 | **S** | Check Point acquires Lakera (2025-09) | |
| B-26 | **S** | F5 acquires CalypsoAI (~$180M) — https://siliconangle.com/2025/09/11/f5-boosts-ai-security-capabilities-acquisition-calypsoai/ | CalypsoAI brand retired into F5 AI Guardrails |
| B-27 | **S** | CrowdStrike acquires Pangea (2025) | |
| B-28 | **S** | Okta acquires Permiso (~$200M); Fortinet acquires Virtue AI | |
| B-79 | **P** | A10 Networks acquires TrojAI — https://www.a10networks.com/news/press-releases/a10-networks-acquires-trojai-inc-expanding-ai-roadmap/ (2026-06-15) | |
| B-80 | **P** | Cisco AI Defense — https://blogs.cisco.com/ai/cisco-ai-defense-comprehensive-security-for-enterprise-ai-adoption | Robust Intelligence heritage; validation + runtime |
| B-29 | **P** | AWS Bedrock Guardrails pricing — https://aws.amazon.com/bedrock/pricing/ | $0.15 / 1,000 text units (content filters, denied topics); $0.10 (sensitive info) |
| B-30 | **P** | Google Model Armor pricing — https://cloud.google.com/security/products/model-armor | 2M tokens/month free, then $0.10 per additional 1M tokens |
| B-37 | **P** | Microsoft Agent 365 — https://www.microsoft.com/en-us/microsoft-agent-365 | **$15 / user / month** list, annual. Agent registry, Entra agent identity, Purview, Defender |
| B-92 | **P** | Microsoft Learn, Defender security for AI — https://learn.microsoft.com/en-us/defender-xdr/security-for-ai/defender-security-for-ai | Real-time protection for Agent 365 MCP tool invocation; 2026-07-01 licensing transition |
| B-81 | **P** | Portkey pricing — https://docs.portkey.ai/docs/product/product-feature-comparison | Dev $0 (10k logs); Pro $49/month |
| B-82 | **P** | TrueFoundry pricing — https://www.truefoundry.io/pricing | $0 / $499 / $2,999 per month |
| B-83 | **P** | Kong pricing — https://konghq.com/pricing | AI Gateway add-on $100/month per unique LLM model proxied |
| B-84 | **V** | MintMCP — https://www.mintmcp.com/blog/self-hosted-vs-managed-enterprise | Vendor-published: $1,250/month for 50 seats, +$25/seat |
| B-85 | **V** | Arcade.dev — https://www.arcade.dev/ | MCP runtime with token vault; usage-based, no public tiers |
| B-86 | **S** | Zenity $125M Series C — https://www.calcalistech.com/ctechnews/article/b1ahbbcbfe (2026-08-03) | ~$185M total raised; agent security and governance |
| B-87 | **S** | WitnessAI $58M Series B — https://www.securityweek.com/witnessai-raises-58-million-for-ai-security-platform/ (2026-01-14) | >$85M total |
| B-88 | **S** | Noma Security $100M Series B — https://www.reuters.com/world/middle-east/israeli-cyber-startup-noma-security-raises-100-million-private-funding-round-2025-07-31/ | $132M total |
| B-89 | **V** | HiddenLayer $100M Series B — https://www.hiddenlayer.com/news/hiddenlayer-100m-series-b-ai-security/ (2026-09-02) | **Vendor announcement only**; not independently confirmed in this research pass |
| B-90 | **S** | Lasso Security $30M — https://siliconangle.com/2026/09/02/lasso-security-launches-cpu-only-ai-guardrail-raises-30m/ | >$37M total |
| B-91 | **S** | Knostic $11M — https://www.morningstar.com/news/pr-newswire/20250305dc33201/knostic-nabs-11-million-to-eliminate-enterprise-ai-data-leaks | ~$14.3M total; knowledge-layer governance |
| B-44 | **P** | Endor Labs, Coding Agent Governance — https://docs.endorlabs.com/agent-governance | **Closest direct competitor to the wedge.** Hooks into Claude Code / Cursor / Codex calling `endorctl ai-audit`; inventory; block / alert / **ask-permission**; redaction before cloud |
| B-45 | **V** | Vorlon, AI Agent Flight Recorder — https://vorlon.io/vorlon-announces-launch-ai-agent-flight-recorder-action-center | Vendor claim of a cross-app immutable agent action trail |
| B-96 | **P** | Project AIR — https://github.com/vindicara-inc/projectair | Signed intent capsules anchored to a Rekor transparency log |
| B-93 | **P** | LinearB pricing — https://linearb.io/pricing | $29 / $59 per contributor/month |
| B-94 | **S** | Third-party deal data for DX (getdx.com) via Vendr aggregation | Median ACV ~$52k. **Estimate, not list price.** |
| B-95 | **S** | Third-party estimates for Faros AI | ~$150k/yr entry. **Estimate, not list price.** |
| B-100 | **P** | GitHub Copilot pricing | Business $19 / Enterprise $39 per user/month |
| B-97 | **S** | Gartner, *Market Guide for AI TRiSM* (2025-02-18, G00785960), via vendor reprint | A Market Guide, **not** a Magic Quadrant |
| B-98 | **S** | Gartner, *Emerging Market Quadrant for AI Application Security* (2026-09-14), via vendor citation | eMQ, not MQ; mandatory capabilities: discovery, automated testing, runtime defence, cloud AI coverage |
| B-14 | **S** | IANS Research / Artico Search 2026 CISO survey (n=113, fielded Apr–May 2026) — https://www.iansresearch.com/resources/all-blogs/post/security-blog/2026/08/25/ai-governance-is-advancing-while-the-attack-surface-expands | 66% dedicated AI policy, 61% NIST AI RMF alignment, 60% approved-tool register; ~31% prompt monitoring, ~19% injection detection, ~15% output guardrails, ~16% red teaming; 81% vs 50% budget ownership split |
| B-15 | **S** | IANS Research, same cohort — https://www.ians.com/blog/ians-research/ai-controls-reduce-risk-organizational-readiness-builds-confidence | 71% have not adversarially tested an AI system |
| B-99 | **S** | RH-ISAC CISO Benchmark 2026 (n=201) — https://rhisac.org/wp-content/uploads/CISO-Benchmark-2026_CLEAR.pdf | ~90% expect AI security spending to rise, frequently by reallocation |

---

## Deliberate gaps and unresolved items

Recorded so that a later reader does not mistake absence for completeness.

| Gap | Status |
|---|---|
| OpenAI's published position on agent injection resistance | Primary page returned HTTP 403 during research. Secondary reporting exists; **not cited as fact**. |
| Exact MITRE ATLAS version and technique counts | Confirm against `atlas.mitre.org` before any compliance mapping is published to a customer. |
| List pricing for Zenity, WitnessAI, Noma, HiddenLayer, Knostic, Cisco AI Defense, Jellyfish, Faros | **Not public.** No estimate substituted. |
| Cloud-marketplace private-offer pricing (AWS / Azure / GCP) for the AI-security vendors | Not retrieved. Highest-value next research pass for pricing calibration. |
| NIST agentic-AI control overlay (NISTIR 8605D) | **Not yet published.** Do not cite as an existing standard. |
| Whether an enterprise will accept Grade B as a control | **No evidence either way.** This is thesis bet T-5 in `12` §11 and can only be settled by a customer. |
