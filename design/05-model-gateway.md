# 05 · Model gateway

Sketches: `diagrams/05-model-request-lifecycle.excalidraw`, `diagrams/06-clients-and-model-catalogue.excalidraw`

> **Amended 2026-09-22.** Two decisions change this document materially.
>
> **D-08** — the model request is no longer the primary unit of governance. It is one
> `capability` kind among many; see [`15-capability-governance.md`](15-capability-governance.md).
> This surface is still needed for attribution and for clients we can genuinely mediate — it
> is no longer the centre of the product.
>
> **D-11** — the Cursor claims below were wrong and are corrected in place.
>
> **This component is not in the MVP.** See [`17-research-conclusions.md`](17-research-conclusions.md) §7.

## What each client actually lets us control

Researched against current vendor documentation, September 2026. This table decides the
product, so keep it up to date and cite it in customer conversations. Grades are the
enforcement grades defined in [`12-strategic-thesis.md`](12-strategic-thesis.md) §5.

### Cursor — corrected (D-11)

**FACT.** Cursor's own documentation states: *"Even if you use your API key, your requests
will still go through our backend! That's where we do our final prompt building."* `[B-41]`

Three consequences the previous version of this document got wrong:

1. **Topology.** With *Override OpenAI Base URL*, the caller reaching our gateway is
   **Cursor's cloud**, not the developer's machine. The path is
   `developer → Cursor cloud → our gateway → provider`. Our data plane must therefore be
   **reachable from the public internet** for Cursor, which contradicts the
   outbound-only-egress promise in [`01-deployment-and-tenancy.md`](01-deployment-and-tenancy.md).
2. **Data protection.** The prompt and the code have **already left the enterprise** before
   our inspector sees them. Presenting [`07-data-protection.md`](07-data-protection.md) as a
   Cursor egress control is not a supportable claim. For Cursor, the data-protection control
   is Cursor's own privacy mode and contract, which we **verify and evidence** rather than
   duplicate.
3. **Coverage.** Composer, Auto routing and Cloud Agents never traverse our gateway at all.

| Lever | Mechanism | Grade |
|---|---|---|
| **MCP mediation** | Enterprise MCP allowlist set to permit only our gateway URL pattern. Precedence **replaces**, does not merge, over user `permissions.json` `[B-42]`. Cursor is a **direct** MCP client, so these calls do not pass through Cursor's backend `[B-43]`. | **A** |
| **Hooks** | `beforeShellExecution`, `beforeMCPExecution`, `preToolUse`, `afterFileEdit`; exit 2 denies. **Default is fail-open — `failClosed: true` must be set** `[B-33]`. Enterprise > Team > Project > User. | **B** |
| Model allow/deny | Team Settings → Models; Admin API `PUT /teams/model-access/configuration` `[B-39]` | **C** |
| Stop personal keys | Team Settings → disable BYOK (dashboard only) `[B-42]` | **C** |
| Forced privacy mode, run mode, sandbox | Enterprise dashboard; MDM `AllowedTeamId` blocks personal accounts `[B-42]` | **C** |
| Usage visibility | Admin API `filtered-usage-events` (hourly aggregates), Analytics API, AI Code Tracking API (Enterprise, Alpha) `[B-39]` | **D** |
| Model traffic via base-URL override | Works, but see above | **D** — *not* A |
| Composer / Auto internal routing | — | **E** |

**What we sell for Cursor:** Grade A tool mediation, Grade B hook interposition, Grade C
configuration attestation, Grade D usage reconciliation. **Not** prompt DLP, and **not**
model-traffic routing by default — a second cloud hop costs latency and buys a control we
cannot honestly assert.

**If a customer still wants base-URL routing** (for cost attribution rather than security),
it remains supported, and the caveat stands: the override carries **all** OpenAI-family
traffic with no carve-out, so our endpoint must be a complete, well-behaved OpenAI-compatible
surface — chat completions *and* responses, streaming, tool calls, vision payloads. A slow or
partial implementation makes the whole editor feel broken and the developer turns us off.

### Claude Code

| Lever | Mechanism |
|---|---|
| Route traffic | `ANTHROPIC_BASE_URL` (+ `ANTHROPIC_BEDROCK_BASE_URL` / `_VERTEX_BASE_URL` / `_FOUNDRY_BASE_URL`), credential via `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_API_KEY` / `apiKeyHelper` |
| Model allowlist | managed settings `availableModels` — also checked at `/v1/messages`, so a patched client cannot bypass it |
| Tool control | `permissions.allow` / `ask` / `deny`, `allowManagedPermissionRulesOnly: true`, `disableBypassPermissionsMode: "disable"` |
| MCP control | `allowedMcpServers`, `allowManagedMcpServersOnly` |
| Delivery | managed settings via MDM, a managed settings file, server-managed settings, or a self-hosted gateway config |

Note for the rollout guide: a *delivered* base URL, proxy or OTLP endpoint can require the
developer to approve it in a dialog. Plan the comms; a silent config that then prompts looks
like malware to a cautious engineer.

### Codex CLI

```toml
# ~/.codex/config.toml            (user level — a repo cannot override provider keys)
model = "aap-balanced"
model_provider = "aap"

[model_providers.aap]
name = "AI Control Plane"
base_url = "https://ai-gw.internal.acme.com/openai/v1"
env_key = "AAP_PLATFORM_KEY"
wire_api = "responses"          # "chat" is deprecated and being removed
```

So the gateway **must** implement the Responses API, not only chat completions. That is a
phase-3 requirement, not a later nicety.

### Gemini CLI

`GOOGLE_GEMINI_BASE_URL` (or `GOOGLE_VERTEX_BASE_URL` for Vertex auth) is honoured through the
genai SDK's http options. HTTPS is required for non-localhost, and the behaviour has moved
between releases — pin a minimum version in the rollout guide and verify it in the preflight.
Org-side controls are thin here; treat the gateway plus MDM as the only real enforcement.

### The honest summary for a customer — revised (D-09)

The previous version of this sentence read: *"Inside the editor we can configure; at the
gateway we can enforce."* That framing is binary and it is wrong in both directions. It
overstates what a gateway achieves for Cursor, and it understates what a blocking
`PreToolUse` hook achieves for Claude Code — a hook returning exit 2 genuinely prevents the
tool call `[B-31]`, which is more than configuration.

The replacement:

> Every control we ship carries a grade. **A** we mediate — it cannot happen without us.
> **B** we interpose in the agent's decision loop and can veto, on hardware you administer.
> **C** your vendor enforces and we verify the setting is still there. **D** we learn about
> it afterwards. **E** we cannot see it, and we will tell you how much of it there is.
>
> We will never show you a number without telling you which of those it came from.

| Client | Model traffic | Tool calls | Config | Usage |
|---|---|---|---|---|
| Claude Code | **A** `[B-32]` | **A** MCP + **B** hooks `[B-31]` | **C** managed settings | **D** OTLP `[B-34]` |
| Cursor | **D** | **A** MCP `[B-43]` + **B** hooks `[B-33]` | **C** dashboard `[B-42]` | **D** Admin API `[B-39]` |
| Copilot | **E** — no in-app redirect `[B-35]` | **C** MCP policy `[B-36]` | **C** AI Controls | **D** metrics API `[B-40]` |
| Codex CLI | **A** `openai_base_url` `[B-76]` | **B** `tool_decision` | **E** no vendor MDM | **D** OTEL |
| Gemini CLI | **A** base URL | **B** sandbox `[B-108]` | **C** system settings | **D** |
| CI agents | **A** | **A** | **A** — customer infrastructure | **A** |
| In-house agents | **A** | **A** | **A** | **A** |

## Gateway surfaces

One service, four wire formats, one internal request model.

| Surface | Path | Used by |
|---|---|---|
| OpenAI chat completions | `POST /openai/v1/chat/completions` | Cursor, most SDKs, LangChain |
| OpenAI responses | `POST /openai/v1/responses` | Codex CLI, newer SDKs |
| OpenAI models | `GET /openai/v1/models` | model pickers — returns **only** the caller's permitted aliases |
| Anthropic messages | `POST /anthropic/v1/messages` | Claude Code |
| Gemini | `POST /gemini/v1beta/models/{model}:generateContent` (+ `:streamGenerateContent`) | Gemini CLI |
| Embeddings | `POST /openai/v1/embeddings` | RAG pipelines |
| Health / preflight | `GET /healthz`, `POST /v1/preflight` | onboarding, monitoring |

Requirements that are easy to skip and expensive to retrofit: streaming must be
byte-incremental (never buffer a whole completion), tool/function calling round-trips
unchanged, `n`/`stop`/`seed`/`response_format` pass through, provider error shapes are
translated into the caller's dialect, and `Retry-After` and rate-limit headers are honest.

## Request lifecycle

Nine steps, all in the data plane. Budget: **p95 under 12 ms** added, excluding inspection and
provider time.

1. **Terminate** — parse into the internal model; reject payloads over the account's cap.
2. **Authenticate** — platform key → `service_identity` → `acts_for_member`, agent, project,
   environment, scopes. No key, no upstream call — ever, not even a model list.
3. **Resolve** — member, org units, effective policy, budget state, rate state, all from the
   in-process cache of the last signed bundle (5 s TTL, explicit invalidation channel). Zero
   database calls on the request path.
4. **Inspect input** — secrets, PII, source code; classify; act (see [07](07-data-protection.md)).
5. **Select** — resolve the requested alias or the mode default; **filter** endpoints by hard
   constraints; **score**; **pick**.
6. **Dispatch** — provider adapter, credential from the local vault, retry within the failover
   group, circuit breaker per endpoint.
7. **Inspect output** — secret and PII scan, detokenise inside the boundary, injection and
   exfiltration heuristics.
8. **Account** — tokens from the provider (or estimated, flagged), `cost_micros` from the
   effective-dated price book, atomic budget decrement.
9. **Emit** — one `ai_event`; the body goes to the local payload store by digest.

Deny returns `403` with a reason code, the policy id, the class detected and a named
alternative. Approval returns `409` with an approval id and a single-use resume token; on
retry, policy is re-evaluated because state may have changed.

## Residency — what "which zone is it in" can honestly mean

This is the question that exposed the weakness in the original plan, so it is answered
precisely.

**A model name carries no location.** Processing location is a property of the endpoint you
call and how it was provisioned:

| Provider | What pins the location | What does not |
|---|---|---|
| Azure Foundry / Azure OpenAI | Deployment SKU: `Standard` / `ProvisionedManaged` → the deployment's region only; `DataZoneStandard` → within the US, EU or APAC data zone | `GlobalStandard` — may process in **any** Azure region, regardless of where the resource lives |
| AWS Bedrock | Direct in-region endpoint (`bedrock.eu-central-1.amazonaws.com`), or a **geographic** inference profile (`eu.`) → within that geography; SCPs must allow exactly the destination regions | A **global** inference profile — routes worldwide (and is ~10% cheaper, which is why somebody will have enabled it) |
| Vertex AI | A regional endpoint / location | The global endpoint, which may route elsewhere |
| OpenAI direct | Account-level residency configuration / tier | The model name, and the assumption that "EU customer" implies EU processing |
| Self-hosted (vLLM, Ollama) | The host you run it on | nothing — this is the only case that is trivially provable |

Therefore:

- Residency lives on `model_endpoints`: `region`, `zone`, `deployment_sku`, `deployment_ref`,
  `residency_class ∈ {region_pinned, zone_pinned, global_unpinned}`, `evidence_ref`,
  `attested_at`, `attested_by`.
- Policy filters on `residency_class` and `zone`. `residency: eu_zone_or_stricter` accepts
  `zone_pinned(EU)` and `region_pinned(eu-*)` and rejects everything else.
- An endpoint whose configuration we cannot read is `global_unpinned` and is **unusable** for
  any data class above `internal`.
- An attestation job re-verifies weekly: read the deployment's SKU and region from the
  provider's control API (Azure deployment properties, Bedrock inference-profile description,
  Vertex endpoint location), store the raw response as evidence, and age out an attestation
  after 30 days so a stale claim degrades to `unverified` instead of quietly persisting.
- The console shows **attested** (with evidence and date) or **unverified**. We never render an
  inferred region as if it were proof, and we never use latency as evidence for anything but
  a warning.

What we cannot do, said out loud in the product: prove at runtime which datacentre served a
given token. What we can do: guarantee which endpoint we called, prove how that endpoint is
configured, and refuse to call anything else. For most auditors that is the answer they
actually need, provided we do not overstate it.

## Making a new model available without an engineer

Hourly job per provider, per account:

| Provider | Discovery call |
|---|---|
| Azure Foundry | list deployments on the resource (+ model catalogue for capability metadata) |
| Bedrock | `ListFoundationModels`, `ListInferenceProfiles` |
| Vertex | publisher model list for the configured locations |
| OpenAI / Anthropic | `GET /v1/models` (+ the documented capability table for context and modality) |
| Local | the runtime's `/v1/models` |

Discovery writes `model_candidates` with `change ∈ {new, changed, withdrawn}` and the raw
response. **Nothing is auto-enabled.** The console shows a diff; an admin sets the residency
class, max data class and cost ceiling and approves it into an alias target. Withdrawal is
the same flow in reverse, with a deprecation window: the alias keeps serving from the
remaining targets and the console warns which members were using the one going away.

Alias lifecycle is `draft → approved → deprecated → retired`. Clients only ever name an
alias, so a provider change is invisible to them. The four published aliases stay stable
across the whole customer base:

| Alias | Intent |
|---|---|
| `aap-fast` | cheap, high throughput, short context |
| `aap-balanced` | the default |
| `aap-deep` | reasoning-heavy, expensive, rate limited |
| `aap-internal-secure` | self-hosted / region-pinned only; the destination for sensitive classes |

## Routing rules an admin writes

```yaml
# policy kind: model     bound to org_unit=ide-users, environment=prod
mode_default: balanced              # cost | balanced | quality | residency_strict
allow_member_override: true         # a member may name an alias that satisfies the constraints

split:
  aap-balanced: 70
  aap-deep: 20
  aap-internal-secure: 10

hard_constraints:                   # filters — never traded off against weights
  residency: eu_zone_or_stricter
  max_data_class: internal
  providers_denied: [unknown, consumer_tier]
  require_tool_support: true

budget:
  monthly_usd: 12000
  soft_at_pct: 80                   # warn the manager, not the developer
  on_exhaustion: degrade            # degrade | approval | block
  degrade_to: aap-fast

on_data_class:
  customer_pii: route_internal      # overrides the split entirely
  secret_material: block
```

Router algorithm, in order, and the order matters:

1. **Filter.** Remove every endpoint failing a hard constraint, the data-class rule, budget
   state or a tripped breaker. If the set is empty → deny with the specific constraint that
   emptied it (not "no capacity").
2. **Score.** Rolling per-endpoint quality proxy (success rate, p95 latency, error classes)
   and live price. `cost` mode sorts by price, `quality` by the quality proxy, `balanced` by a
   normalised weighted sum, `residency_strict` by strictest residency first.
3. **Pick.** Weighted choice within the surviving set, with a deterministic tie-break hashed
   on `(session_id, alias)` so a conversation stays on one endpoint — switching mid-thread
   produces visibly inconsistent behaviour and support tickets.
4. **Report.** Actual split vs target is a metric, so drift is visible rather than discovered
   in the invoice.
5. **Degrade.** Budget exhaustion and breaker trips walk a declared ladder; the reason is on
   the response header and the event, so a developer whose model got cheaper knows why.

## Cost and tokens

`cost_micros = Σ(tokens × effective price per 1k) / 1000`, integer arithmetic, price resolved
by `occurred_at` against `model_prices`, computed at ingest and stored. If a provider does not
return usage, we estimate from a tokeniser and set `tokens_measured = 0`; every surface that
shows that number says "estimated". A price correction runs a recompute job over a window and
writes a new `ingest_version` with a reason, so history is restated deliberately and visibly,
never silently.

## Preflight — the feature that decides whether onboarding succeeds

`POST /v1/preflight` with `{ client, environment, key_id }` runs, in order, and returns a
checklist with a fix link for each failure:

1. platform key valid, not revoked, correct scopes, correct environment;
2. the caller's aliases resolve to at least one healthy endpoint;
3. residency attestation present and fresh for each of those endpoints;
4. a live 8-token completion through the full path, with the measured added latency;
5. MCP grants present, and `tools/list` returns a non-zero count (with the reason when zero);
6. telemetry arrived — the event for step 4 is queryable.

"It shows zero tools" and "it says unauthorised" must never be something a user debugs by
reading logs. The preflight names the missing step and links straight to the screen that
fixes it.
