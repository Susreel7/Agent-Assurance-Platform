# 14 · AI identity and action authorization

> Written 2026-09-22. Sources in [`18-bibliography.md`](18-bibliography.md), cited as `[B-nn]`.
> Tags: **FACT** · **SOURCE-BACKED** · **DESIGN DECISION** · **INFERENCE** · **OPEN**.
>
> This is a foundational document. `design/02` (identity and onboarding), `design/03` (data
> model) and `design/04` (authorization) are subordinate to it where they disagree.

The current design has three principal kinds — human, service identity, agent — and treats an
agent as a static registry row. That is insufficient for one reason: **it cannot answer who is
responsible for an action.** This document answers it.

---

## 1. The question

> A pull request deleted a production table at 02:14. Who is responsible?

Candidate answers, all partly true and none sufficient on their own: the developer whose
laptop it ran on; the developer who wrote the task; the team that owns the agent; the person
who approved the agent version; the person who granted the credential; the author of the
poisoned issue that steered it.

**DESIGN DECISION.** Responsibility is not a single field. It is a **chain**, and the product's
job is to record the whole chain and make each link independently queryable.

```
HUMAN            the accountable person — always present, never synthetic
  └─ AGENT       a named, versioned, owned, approved piece of software
      └─ AGENT INSTANCE   one running copy, on one host, in one environment
          └─ SESSION      one continuous context window; carries taint
              └─ TASK     one unit of intent
                  └─ ACTION   one capability invocation — the governed unit
```

Every action carries the full chain. A query for "everything this human's agents did in
production last week" and a query for "everything this agent version did across all humans"
are both single-index lookups, not joins across three systems.

**Rule (non-negotiable): no action without a human at the root.** A scheduled or CI-triggered
agent is rooted at the human who registered or last approved it — recorded as
`root_human_basis = registered_by | approved_by | triggered_by`, so the evidence never implies
someone was at a keyboard when they were not. **INFERENCE:** the alternative — allowing
"system" as a root — is how accountability disappears, and it is the failure mode of every
service-account model that preceded this one.

---

## 2. Grounding in standards

**DESIGN DECISION:** we implement standard mechanisms and do not invent identity formats.
Status as of 2026-09-22:

| Concern | Standard | Status | Our use |
|---|---|---|---|
| Workload identity + attestation | SPIFFE/SPIRE `[B-62]` | CNCF **Graduated** | `agent_instance` identity in customer-run environments; X.509-SVID → mTLS to the gateway |
| Delegation, not impersonation | **RFC 8693** Token Exchange `[B-49]` | RFC | `sub` = human, `act` = agent chain |
| Audience binding | **RFC 8707** Resource Indicators `[B-63]` | RFC | Every brokered credential is bound to one downstream resource |
| Sender constraint | **RFC 9449** DPoP `[B-50]` / **RFC 8705** mTLS `[B-51]` | RFC | Brokered credentials are proof-of-possession, not bearer |
| Fine-grained grants | **RFC 9396** RAR `[B-64]` | RFC | Capability grants expressed as `authorization_details` |
| Agent client auth | **RFC 7523** JWT bearer `[B-65]` | RFC | Agent instance authenticates with a signed assertion, not a shared secret |
| Enterprise SSO → resource | ID-JAG / Cross-App Access `[B-47]` | **`draft-04`, expires 2026-11-22** | Roadmap only. Not a dependency. |
| Agent identity | IETF WIMSE `aims` `[B-46]` | **WG draft** | Track; align naming; do not depend |
| Multi-hop AI delegation | `wimse-arch` §3.4.11 `[B-46]` | WG draft | Source of the re-binding rule in §4 |
| MCP authorization | MCP spec `2026-07-28` `[B-66]`; EMA extension **Stable 2026-06-18** `[B-48]` | Stable extension over draft OAuth 2.1 | Implement as a resource server |
| Continuous revocation | OpenID **CAEP/SSF 1.0 Final** (2025-08-29) `[B-67]` | Final | Kill agent sessions on IdP risk signals |

**Honest caveat — FACT:** the MCP authorization spec mandates OAuth 2.1, which is itself still
`draft-ietf-oauth-v2-1` and not an RFC `[B-66]`. **INFERENCE:** we build on the final RFCs
(8693/8707/9449/8705/9396/7523) and treat OAuth 2.1 and the agent-identity drafts as a moving
target to track, not to bet the schema on.

---

## 3. The entities

### 3.1 `agents` — the registered definition

```
agent_id, account_id, name, slug
owner_org_unit_id, owner_member_id          -- accountability, both required
purpose                                      -- free text, mandatory, shown to approvers
kind          ∈ interactive_ide | cli | ci | service | subagent | third_party
harness       ∈ claude_code | cursor | copilot | codex | gemini_cli
                | langgraph | custom | unknown
trust_tier    ∈ untrusted | standard | elevated | privileged
lifecycle     ∈ discovered | registered | assessed | approved | restricted
                | quarantined | retired         -- see §8
provenance    -- repo URL, commit, build attestation, who registered, how discovered
first_seen_at, last_seen_at
```

### 3.2 `agent_versions` — what was actually approved

**DESIGN DECISION:** approval attaches to a **version**, never to an agent. This is what makes
declared-versus-observed reconciliation possible, and it is the existing best idea in this
repository (`../docs/design/01-agent-composition.md`), now load-bearing.

```
agent_version_id, agent_id, version, composition_digest
declared_capabilities[]        -- from static extraction (`aap extract`) or registration
declared_data_classes[]
declared_environments[]
model_policy                   -- declared models / providers
rule_source_digests[]          -- system prompts, rules files, skills: digests only
subagent_refs[]
approval_status, approved_by, approved_at, expires_at
sbom_ref, attestation_ref
```

`composition_digest` covers the normalised declaration. Any change produces a new version,
which is `registered`, not `approved`. **A changed agent is a new agent until a human says
otherwise.**

### 3.3 `agent_instances` — one running copy

**This is the entity the current design is missing, and most of the threat model needs it.**

```
instance_id, agent_id, agent_version_id, account_id
human_member_id, root_human_basis
environment, host_fingerprint, harness_version
started_at, last_heartbeat_at, ended_at
attestation ∈ none | config_signed | spiffe_svid | tpm     -- see §7
parent_instance_id, delegation_depth                        -- §4
enforcement_grade_available ∈ A|B|C|D|E                     -- what we can do here
```

`enforcement_grade_available` is computed at registration from the observed harness and the
controls we could verify. It is why the dashboard can be honest per-session instead of
per-product.

### 3.4 `sessions` and `tasks`

```
session_id, instance_id, started_at, ended_at
taint ∈ clean | tainted | tainted_with_secrets        -- threat model §7
context_sources[]                                     -- what was ingested, by provenance
task_id, session_id, intent_digest, origin ∈ human | schedule | webhook | parent_agent
```

`origin` matters: a task originating from a webhook carrying a public issue body is
`tainted` from birth.

### 3.5 `service_identities` — kept, narrowed

Retained from `design/02` for non-agent machine callers (a CI job that is not an agent, an
exporter). **DESIGN DECISION:** a service identity may **not** be the root of an action chain.
If it acts as an agent, it registers as one.

---

## 4. Delegation

**FACT** `[B-49]` RFC 8693 distinguishes delegation (`sub` = original subject, `act` = acting
party, nestable) from impersonation (`sub` replaced, actor invisible). **SOURCE-BACKED**
`[B-68]` RFC 8693 also states that prior actors in a nested `act` chain are **informational**
and must not be the sole basis for an access decision.

**DESIGN DECISION — three rules.**

1. **Delegation, never impersonation.** Every token and every event carries the human as
   subject and the agent chain as actor. We never mint a credential that makes an agent look
   like a person.
2. **Authority attenuates monotonically.** A child instance's effective capability set is a
   **subset** of its parent's, intersected with its own grants. Widening at any hop is a
   policy error that fails closed. This is the confused-deputy control (threat model AP-6).
3. **Decide on the current hop; audit the whole chain.** Following `[B-68]`, the authorization
   decision uses the current actor plus the attenuated capability set. The full chain is
   recorded for forensics and is *never* the thing that grants access.

```
delegations(parent_instance_id, child_instance_id, granted_capabilities[],
            expires_at, depth, reason)
```

`max_delegation_depth` is an account policy, default **3**. **INFERENCE:** unbounded agent
spawning is how a bounded blast radius becomes unbounded, and depth is the cheapest cap that
works.

---

## 5. Credentials — from vault to broker

**DESIGN DECISION — the most significant single change in this research pass.**

`design/06` specifies a token vault: the gateway holds the real credential and injects it
upstream. That is correct for MCP and it is not enough, because **the credential the agent
abuses is usually not ours** — PocketOS found a token on the filesystem (threat model AP-1).

### 5.1 Target model

```
  agent instance                    NOT:  agent instance
      │ SVID / signed assertion            │  reads long-lived token from ~/.config
      ▼                                    ▼
  CREDENTIAL BROKER                    downstream system
      │  policy check (§6) + capability grant + audience + TTL
      ▼
  short-lived, audience-bound, sender-constrained credential
      │  RFC 8707 audience · RFC 9449 DPoP or RFC 8705 mTLS · minutes
      ▼
  GitHub · Jira · AWS · Postgres · internal API
```

```
credential_bindings(binding_id, agent_id|agent_version_id, resource_kind,
                    resource_selector, max_scope[], max_ttl_seconds,
                    requires_approval, environments[])

credential_leases(lease_id, instance_id, session_id, task_id, binding_id,
                  granted_scope[], audience, issued_at, expires_at,
                  proof_method ∈ dpop|mtls|none, revoked_at, revoked_reason)
```

Every lease is joined to the action it was issued for. "Which credential did this action use,
and what else did that credential do?" becomes one query — a question no current tool in the
competitive set can answer.

**SOURCE-BACKED** `[B-69]` HashiCorp Vault already supports SPIFFE authentication and dynamic
secrets, and cloud workload-identity federation `[B-70]` already issues short-lived cloud
credentials from an OIDC assertion. **DESIGN DECISION:** we **broker** against these rather
than becoming a secrets manager. We are the policy decision point and the evidence layer; the
secret material stays where the customer already keeps it. This also keeps us out of the "not
a secrets manager" non-goal.

### 5.2 Why this is the highest-value control

**INFERENCE.** Against threat model AP-1, it is the only Grade A intervention available. It
converts "the agent found a token that could delete production" into "the agent held a
five-minute credential scoped to one staging resource, bound to a proof key, and the deletion
call returned 403 with an audit record naming the instance." That is a sentence a CISO can act
on, and no amount of prompt filtering produces it.

**OPEN (Q-N):** does credential brokering belong in the MVP, or does it extend the sales cycle
past the point where the wedge works? It requires the customer to move a credential, which is
a much larger ask than a read-only collector. Current recommendation: **not in MVP; first item
in V1**, with the MVP ledger used to *prove the exposure exists* in that specific customer.

---

## 6. The action authorization model

### 6.1 Request

```
AuthorizationRequest {
  subject:    { human, agent, agent_version, instance, session, task, delegation_chain[] }
  capability: { kind, id, version, risk_class, write, irreversible }
  resource:   { kind, identifier, environment, data_classes[], owner_org_unit }
  context:    { time, taint, network_posture, device_posture, prior_decisions_in_session,
                credential_lease?, enforcement_grade_available }
  arguments:  { digest, parsed_facets }        -- facets, never raw content
}
```

`parsed_facets` is the structured extract the argument rules in `design/06` already produce —
SQL verbs and tables, repository names, path roots, target host. **DESIGN DECISION:** policy
evaluates facets, never raw arguments. Raw arguments never enter the policy engine, never
enter the control plane, and never enter a log line.

### 6.2 Decisions

```
ALLOW · ANNOTATE · MASK · TOKENIZE · ROUTE_INTERNAL
REQUIRE_APPROVAL · STEP_UP_AUTH · RATE_LIMIT · QUARANTINE · DENY
```

Each returns a stable `reason_code`, the `policy_version` that produced it, and the
`enforcement_grade` at which it was applied. **A decision without a grade is not a decision** —
it is a suggestion, and the UI must not display it as protection.

### 6.3 Model — hybrid, and each part earns its place

| Part | Used for | Why |
|---|---|---|
| **RBAC** | Console access, who may administer | Solved; matches how customers think |
| **ReBAC** | Reachability: human → org unit → environment → resource; agent → owner → grant | **SOURCE-BACKED** `[B-71]` OpenFGA documents agents as first-class principals with `can_act_on_behalf_of`. Role explosion is real at agent scale. |
| **ABAC** | The decision itself: taint, environment, data class, risk, time | Contextual conditions cannot be pre-materialised as relationships |
| **Capability-based** | What a delegated child may do | Attenuation is natural in capabilities and awkward in ACLs `[B-72]` |
| **Risk-adaptive** | Elevating a decision, never granting one | See §7 |

**DESIGN DECISION:** risk may only make a decision **stricter**. A low risk score never
converts a `DENY` into an `ALLOW`. **INFERENCE:** the inverse design — score-based
permissiveness — is unauditable, and a CISO will reject it the moment they understand it.

---

## 7. Policy language

**DESIGN DECISION: adopt Cedar as the evaluation engine. Do not invent a policy language. Do
not make administrators write policy by hand.**

Evidence:

- **SOURCE-BACKED** `[B-73]` Cedar's native shape is `principal / action / resource /
  context` — an exact match for §6.1, which means no impedance layer.
- **SOURCE-BACKED** `[B-74]` Cedar ships analysis tooling that compiles policies to SMT and
  has machine-checked correctness proofs in Lean. Policy **simulation** ("does this change
  deny anything that is allowed today?") becomes a solver query rather than a replay harness.
  For a product whose value is that its decisions are defensible, that property is worth more
  than expressiveness.
- **SOURCE-BACKED** `[B-75]` Rego is more general and correspondingly harder to verify and
  bound. We do not need general.

**Architecture:**

```
Admin UI (structured editor, plain language)
   ↓ compile
Cedar policy set  ──signed──▶  policy bundle  ──▶  data-plane PDP
   ↓ analyse
Simulation + diff against last 30 days of real actions, before activation
```

Administrators author in a structured editor. Cedar is the compilation target and the audit
artefact — visible, exportable, diffable, but not the authoring surface. **INFERENCE:**
requiring a security admin to learn a policy language is a deployment blocker in exactly the
accounts we most want.

Lifecycle, all first-class:

```
policy → policy_version → simulation → approval → activation(effective_from)
       → binding(org_unit | environment | agent | capability)
       → exception(scope, reason, expires_at, approver)
       → break_glass(actor, reason, ttl ≤ 60 min, auto-revert, alarm to two channels)
       → rollback(to_version, reason)
```

**DESIGN DECISION:** every exception and every break-glass grant has a mandatory expiry and a
mandatory reason. Permanent exceptions are not representable in the schema. **INFERENCE:**
every governance product that allowed them became a list of permanent exceptions.

---

## 8. Risk — categorical first, scored only where a score is needed

**DESIGN DECISION.** Most decisions do not need a number.

**Categorical (drives enforcement):**

| Signal | Values |
|---|---|
| `capability.risk_class` | low · medium · high · critical |
| `write` / `irreversible` | boolean |
| `resource.data_class` | public · internal · confidential · restricted |
| `environment` | dev · staging · prod |
| `session.taint` | clean · tainted · tainted_with_secrets |
| `identity_assurance` | attested · managed · unmanaged |
| `agent.trust_tier` | untrusted · standard · elevated · privileged |

Policy is written over these. They are explainable in one sentence to an auditor, which a
weighted score is not.

**Scored (drives triage and review priority only):**

```
review_priority = f(behavioural deviation from this agent version's baseline,
                    declared-vs-observed capability delta,
                    recent policy violations, credential exposure events,
                    capability-mix novelty)
```

This score orders a queue. **It never gates an action.** **INFERENCE:** conflating the two is
the most common failure in this category — the score becomes both the control and the thing
nobody can explain, and the first false positive destroys trust in it.

---

## 9. Agent lifecycle

```
discover → register → assess → approve → deploy → observe
              ↑                              │
              │        ┌─────────────────────┼──────────────┐
              │        ▼                     ▼              ▼
              └──── revalidate           restrict       quarantine
                        │                                   │
                        └──────────── retire ◀──────────────┘
```

| Stage | Trigger | Gate |
|---|---|---|
| discover | Unregistered agent observed in telemetry or endpoint scan | None — discovery is passive and must never block work |
| register | Human claims ownership | Owner + purpose mandatory |
| assess | Automatic | Composition extracted, capabilities enumerated, risk classed |
| approve | Human | Version-scoped, expiring, with the declared capability set visible |
| deploy | — | Instances may start |
| observe | Continuous | Declared vs observed reconciliation |
| restrict | Policy or drift | Capability set narrowed, agent keeps running |
| quarantine | Incident | All capability grants void within one cache TTL (≤ 5 s) |
| revalidate | Version change or approval expiry | Back to assess |
| retire | Human | Grants revoked, evidence retained for the retention period |

**Is registration mandatory before an agent may act?**

**DESIGN DECISION: mandatory for Grade A paths, advisory elsewhere, and never mandatory for
discovery.** An unregistered agent cannot obtain a brokered credential or pass the capability
gateway — that is enforceable and it is the correct default. It *can* still run on a laptop
using a credential we do not control, and pretending otherwise would contradict the bypass
table. **INFERENCE:** the failure mode to avoid is a registration requirement that developers
route around, which converts a governance product into shadow AI's best recruiter. Discovery
must always be free.

---

## 10. Revocation

| Mechanism | Latency target | Basis |
|---|---|---|
| Quarantine agent / server | ≤ 5 s | Existing `06` cache TTL; keep |
| Revoke credential lease | Immediate at broker; ≤ lease TTL downstream | Short TTL is the control, not a revocation list |
| Revoke grant | ≤ 1 bundle refresh | Bundle push |
| Kill session on IdP signal | ≤ 5 s after receipt | **SOURCE-BACKED** `[B-67]` CAEP/SSF 1.0 Final: consume `session-revoked`, `credential-change`, `risk-level-change` |
| Retire agent version | Immediate for new instances; running instances drain | Avoids breaking in-flight work |

**INFERENCE:** short credential TTL is a *stronger* revocation story than a revocation list,
because it degrades gracefully under partition. A five-minute credential in a network-isolated
environment expires on its own; a revocation list does not arrive.

---

## 11. What this changes in the existing documents

| Doc | Change | Decision ID |
|---|---|---|
| `02-identity-and-onboarding.md` | Add `agent_versions`, `agent_instances`, `sessions`, `tasks`, `delegations`; human root rule | D-12 |
| `03-data-model.md` | New tables §3, §4, §5; `enforcement_grade` on every decision row | D-13 |
| `04-authorization-and-dashboards.md` | Cedar as PDP; decision set expanded; grade on every displayed number | D-14 |
| `06-mcp-gateway.md` | Token vault becomes one backend of the credential broker | D-15 |
| `07-data-protection.md` | Policy sees facets, never raw arguments — make explicit | D-16 |
