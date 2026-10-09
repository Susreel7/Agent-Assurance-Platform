# Design 3 — Model routing and data residency (detection vs prevention)

## Problem

Enterprises set model selection to **`auto`** so the SDK or an internal router chooses models. For agents touching **production** data, engagement terms require processing in specific regions/jurisdictions. **`run_steps.model` records what was used after the fact** — essential for drift detection, useless for blocking a non-compliant request mid-flight.

The customer asks: how can data be **prevented** from reaching a model hosted outside the permitted country, and how do we even know where a model runs?

## Decision (with rationale)

1. **Split responsibilities:**
   - **Control plane (existing FastAPI + Postgres):** catalogue, policy compilation, evaluation API, `policy_decisions` audit trail, post-hoc drift from `run_steps`.
   - **Data plane (`services/llm-gateway/`):** optional sidecar HTTP(S) proxy on the **request path** for LLM/MCP egress; calls control plane evaluate; **fail-closed** for production workloads when binding cannot be proved.

   Rationale: AGENTS.md one service applies to governance DB/API; D-001 already contemplates Go for ingest/security surface. Gateway shares no DB — stateless except cached catalogue slice.

2. **Unknown model = deny** when `lifecycle_state ∈ {staging, production}` and engagement/residency binding is strict; **allow with finding** in dev unless org policy says otherwise.

3. **Reuse engagement cross-border ladder** (`CrossBorderTransfer`, D-021) — do not invent parallel residency enums. Model catalogue adds **hosting geography**; cross-border rules decide if a region in another jurisdiction is allowed given engagement stance.

4. **Catalogue is reference data** (`org_id IS NULL` shipped rows + tenant overrides), not a live vendor API call on critical path.

## Detection vs prevention

| Layer | When | Mechanism | Outcome |
|-------|------|-----------|---------|
| Detection | After run | `run_steps.model` vs allowed set from descriptor + engagement + catalogue | Finding `model-not-allowed`; posture score |
| Detection | After run | No `policy_decision` within Δt of llm step | Finding `gateway-bypass-suspected` |
| Prevention | Before request | Gateway `POST /v1/forward/chat/completions` | 403 + `policy_decisions` row |
| Prevention | Tool/MCP egress | Gateway route rules per host | 403 deny |

**Fail-closed default (production):**

If any of: unknown model id, unknown region, catalogue row expired, policy evaluator error → **DENY** (HTTP 403), outcome recorded, agent run step may show `refused` if SDK handles it.

**Fail-open exception (dev only):** org setting `AAP_GATEWAY_DEV_PERMISSIVE=true` forbidden in `byoc`/`airgap` production namespaces — enforced in `Settings` like dev auth bypass.

**Latency budget:**

| Segment | Target |
|---------|--------|
| Gateway local catalogue lookup (cached) | ≤2 ms |
| Policy evaluate (in-process call to compiled rules, not full HTTP round-trip in same pod) | ≤5 ms |
| Total added p99 | ≤15 ms excluding provider RTT |

Implementation: gateway embeds **compiled policy bundle** refreshed on policy publish webhook/long poll; HTTP evaluate only on cache miss.

## Model catalogue

### Table `model_catalog_entries`

| Column | Type | Notes |
|--------|------|-------|
| `id` | uuid PK | |
| `org_id` | uuid NULL | NULL = global reference |
| `provider` | text | `anthropic`, `openai`, `azure-openai`, … |
| `model_id` | text | provider-native id |
| `display_name` | text | optional |
| `hosting_mode` | enum | `vendor_api`, `cloud_managed`, `self_hosted` |
| `primary_region` | text | e.g. `eu-west-1`, `us-east-1`, `global` |
| `jurisdiction` | text | ISO country or `EU`, `US`, `GB` |
| `cross_border_ok` | boolean | false if always cross-border from EU |
| `data_processing_terms` | enum | `zero_retention`, `30_day`, `provider_default`, `unknown` |
| `source` | text | `vendor_doc`, `operator_assertion`, `customer_override` |
| `source_url` | text | optional, ≤512 |
| `valid_from` | date | |
| `valid_to` | date NULL | NULL = current |
| `digest` | text | sha256 canonical row |

Unique: `(COALESCE(org_id, '00000000-0000-0000-0000-000000000000'), provider, model_id, valid_from)`.

### Table `model_catalog_aliases`

Maps router strings (e.g. `claude-sonnet-latest`, `auto`) → canonical entry id. **Auto alias resolves to sentinel `UNRESOLVED_AUTO`** — gateway must expand using request context or deny.

### Maintenance

| Source | Who updates | Frequency |
|--------|-------------|-----------|
| Shipped seed | Platform release | Quarterly |
| Vendor docs | Operator manual PR | Ad hoc |
| Customer override | Admin API | Per tenant |
| Observed novel model | Detection creates **draft** row `source=observed`, `valid_to=yesterday` until approved | — |

**Unknown model workflow:**

1. Gateway sees model string `M` not in alias map.
2. Production → **DENY** `reason_code=model_unknown`.
3. Insert `findings` + admin notification.
4. Operator adds catalogue row; policy bundle refresh.

**Auto-router is the hard case:** descriptor must declare `composition.model_policy.selection_mode`. If `auto`, allowed set = **allowlist patterns** + catalogue expansion at evaluate time, not a single pin. If allowlist empty and mode=auto → **DENY** in production (open question).

## Binding policy to agents

### Inputs to evaluation (extended `EvaluationRequest`)

```python
class EvaluationRequest(BaseModel):
    ...
    model_provider: str | None
    model_id: str | None
    model_role: str | None = "primary"
    selection_mode: ModelSelectionMode | None
    lifecycle_state: LifecycleState | None
    data_classes: list[str]
    requested_region: str | None      # from catalogue or request header
    effective_region: str | None      # output
    engagement_id: UUID | None
```

### Resolution order (deterministic)

1. Load **engagement** (if agent linked to engagement via `engagement_agents`): `permitted_regions`, `prohibited_regions`, `cross_border_transfer`, `permitted_data_classes`.
2. Load **agent version descriptor**: `data.residency`, `models[]`, `composition.model_policy`.
3. Intersect regions: `engagement.permitted_regions` ∩ descriptor `data.residency.permitted_regions` unless engagement empty (use descriptor).
4. Map requested model → catalogue entry → `primary_region`, `jurisdiction`.
5. If region not in permitted set → `REROUTE` if same jurisdiction alternative exists (`policy.service._pick_reroute_region`), else `DENY`.
6. Apply **cross-border ladder:** if processing would occur in jurisdiction `J` outside home region set:
   - engagement `cross_border_transfer=prohibited` → DENY
   - `permitted_with_safeguards` → require descriptor `data.residency.basis` ∈ allowed safeguard bases (enum list)
   - `permitted_with_consent` → require lawful_basis on request for special categories (existing policy check)
7. Write **`policy_decisions`** row (immutable):

| Column | Use |
|--------|-----|
| `outcome` | allow / deny / reroute |
| `rule_id` | e.g. `residency.customer_pii`, `model.allowlist` |
| `requested_region` | from catalogue |
| `effective_region` | after reroute |
| `data_classes` | from request |
| `agent_id`, `agent_version_id`, `engagement_id` | binding |
| `subject_ref` | optional run_id or request id |
| `evidence_event_id` | link when also recorded as evidence |

Postgres enum `policy_decision_outcome` already includes `reroute` — ensure gateway respects `effective_region` on allow path.

### Compiled allow-set (for gateway hot path)

```python
class CompiledModelPolicy(BaseModel):
    agent_version_id: UUID
    engagement_id: UUID | None
    selection_mode: ModelSelectionMode
    allowed_entry_ids: frozenset[UUID]   # catalogue ids
    allowed_patterns: tuple[str, ...]    # glob on provider/model_id
    permitted_regions: frozenset[str]
    cross_border_rung: CrossBorderTransfer
    compiled_at: datetime
    policy_version_id: UUID
    rules_digest: str
```

Built in `policy.service` on publish and on agent version publish event; pushed to gateway object store or config map (airgap: file bundle signed offline).

## Egress gateway / proxy

### Placement

```
┌──────────────┐     ┌─────────────────┐     ┌──────────────────┐
│ LangGraph    │────▶│ llm-gateway     │────▶│ Provider API     │
│ / Cursor SDK │     │ (sidecar/DMZ)   │     │ (Anthropic, etc) │
└──────────────┘     └────────┬────────┘     └──────────────────┘
                              │
                              ▼
                     Control plane API
                     (catalogue, policy compile,
                      policy_decisions ingest)
```

- **Kubernetes:** `Deployment` with `proxy` container + agent container; `HTTP_PROXY` env for SDK.
- **SaaS:** we host gateway per tenant VPC connector (future) — v1 document BYOC pattern only.
- **Airgap:** gateway runs inside customer enclave; catalogue and policy bundles imported via signed files (same as licensing); **no egress to vendor cloud for governance**.

### Inspection

| Request property | Source |
|------------------|--------|
| Model id | JSON body `model` or Azure/OpenAI deployment header |
| Provider | Host header map |
| Data classes | Header `X-AAP-Data-Classes: customer_pii,claims` (SDK contract) |
| Agent identity | mTLS client cert or `X-AAP-Agent-Urn` + signed token (Q-012 machine identity) |
| Engagement | Resolved from agent pin |

### Failure behaviour

| Condition | HTTP | `policy_decisions.outcome` |
|-----------|------|----------------------------|
| Unknown model, production | 403 | deny |
| Region not permitted, reroute possible | 307/internal rewrite | reroute |
| Region not permitted, no reroute | 403 | deny |
| Evaluator down | 503 | none (request not forwarded) — **fail closed** |
| Dev + permissive flag | 200 | allow with warning header |

Streaming: gateway must not buffer full completion; policy decision taken **before** streaming starts. Mid-stream provider redirect undetectable — see failure modes.

### MCP egress

Optional v2: gateway as MCP HTTP forwarder with tool allowlist from descriptor `tools[]` + `references.mcp_servers`. v1 scope: LLM provider hosts only.

## Deployment modes

| Mode | Catalogue | Gateway | Telemetry |
|------|-----------|---------|-----------|
| **saas** | Global seed + tenant overrides | Customer choice: shared or dedicated | Standard |
| **byoc** | Customer admin; optional import from signed bundle | Deployed in customer VPC | Opt-in metadata only |
| **airgap** | Imported signed `catalogue.bundle` | Required for enforcement; offline updates | None |

Settings (`app/config.py`):

- `AAP_LLM_GATEWAY_ENABLED: bool`
- `AAP_LLM_GATEWAY_UPSTREAM_*` per provider
- `AAP_MODEL_CATALOGUE_BUNDLE_PATH` for airgap

Never phone-home for catalogue updates on request path.

## Evidence trail

Blocked routing → dual write:

1. `policy_decisions` row (already immutable trigger).
2. `evidence_events` kind `POLICY_DECISION` (or existing kind mapping in `control_mappings`) with digest of decision payload, ≤512 bytes text fields.

Console: **Policy → Decisions** list (existing router) filtered by agent; export for auditors.

Run ingest correlation: when `run_steps` reports llm step with model `M`, lookup decision within `[started_at - 5s, started_at + 1s]` matching `subject_ref=run_id:seq`. Missing → finding.

## Failure modes (honest)

| Failure | Reality | What product does |
|---------|---------|-------------------|
| **Direct provider bypass** | Agent uses API key without proxy | Detect via missing decision + model drift finding; network controls out of scope |
| **Streaming already started** | Cannot un-send tokens | Pre-stream evaluation only; incident response if post-hoc drift |
| **Provider sub-region routing** | Azure/OpenAI may route internally | Catalogue `primary_region` is **best effort**; mark `confidence=operator_assertion`; recommend contractual DPA + private endpoints |
| **Auto model resolves late** | Router picks at provider | Allowlist patterns + deny unknown; require descriptor allowlist non-empty |
| **Stale catalogue** | New model day-one | Unknown model deny + fast-path admin approve |
| **Special category without header** | SDK omits data classes | Default to **most restrictive** engagement class set (pessimistic `MaterialityContext` pattern) |
| **Gateway latency** | Adds hop | Co-locate sidecar; compiled policies |
| **False reroute** | Wrong region substitute | Log `effective_region`; human review in decisions UI |

### Is full enforcement unworkable?

**Partially.** Without network or SDK mandates, **deterministic blocking of every byte** is not achievable. The product delivers:

- Enforceable path when gateway is deployed and SDK configured (fail-closed).
- Strong detection and audit when not.
- Customer must accept gateway deployment as compliance control (like a web proxy for exfil).

Reshape expectation: **"compliance-grade when in-path; otherwise continuous audit"** — not silent guarantee.

## API surface (control plane)

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/v1/model-catalogue/entries` | List/search |
| POST | `/v1/model-catalogue/entries` | Admin create override |
| POST | `/v1/policies/evaluate` | existing; extended fields |
| GET | `/v1/policies/decisions` | existing list |
| GET | `/v1/agents/{id}/model-policy/compiled` | Gateway fetch bundle |
| POST | `/v1/internal/policy-decisions` | Gateway ingest (machine auth Q-012) |

Gateway OpenAPI separate repo path `services/llm-gateway/openapi.yaml`.

## Console surface

- **Agent → Model policy** section: selection mode, allowlist, pinned model, link to catalogue entries.
- **Engagement → Terms** overlay: permitted regions vs model regions diagram (simple table v1).
- **Policy → Decisions**: filter deny/reroute; export CSV.
- **Finding detail** for `gateway-bypass-suspected` with remediation steps.

## Out of scope (v1)

- Full MCP traffic proxy.
- Cryptographic attestation of provider region.
- Automatic vendor catalogue scraping (legal/ToS risk).
- Replacing customer network firewalls.

---

## Open questions

### Q-D3-01 — Production `auto` without allowlist

| Option | Recommendation |
|--------|----------------|
| Deny until allowlist populated | **Recommended** — fail closed |
| Allow with daily review finding | Weaker compliance story |

### Q-D3-02 — Gateway implementation language

| Option | Recommendation |
|--------|----------------|
| Go sidecar (D-001) | **Recommended** for streaming proxy |
| Python | Faster to ship; acceptable for v0 prototype only |

### Q-D3-03 — Data class headers mandatory in production

| Option | Recommendation |
|--------|----------------|
| Required header on gateway | **Recommended** via SDK contract |
| Infer from agent descriptor classes only | Pessimistic union — may over-block |
