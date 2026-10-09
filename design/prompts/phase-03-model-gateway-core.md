# Phase 3 — Model gateway core

> **HISTORICAL — DO NOT EXECUTE.** The gateway is excluded from the ledger MVP and already
> has implementation prior art. This prompt also contradicts D-070: Cursor model traffic is
> not Grade-A mediation and Cursor prompt DLP is not supportable.

> Paste this whole file as the only prompt of a fresh session.

## Objective

Put every model request from Cursor, Claude Code, Codex CLI and Gemini CLI through our gateway,
attributed to a real person, policy-checked, residency-constrained, token- and cost-accounted,
with under 12 ms of added p95 latency. After this phase the product can honestly say "we know
and control which model received what, from whom".

## Prerequisite

Phase 2's gate: roles, scoped grants and the visibility function are live and tested.

## Read first

- `design/05-model-gateway.md` — all of it, especially the per-client table and the residency section
- `design/01-deployment-and-tenancy.md` — control plane vs data plane, and the bundle contract
- `design/03-data-model.md` §C and §E
- `design/diagrams/05-model-request-lifecycle.excalidraw`, `06-clients-and-model-catalogue.excalidraw`

## Scope

**In:** the four wire surfaces; platform-key authentication to `service_identities`; the endpoint
registry with residency attestation; alias resolution with hard-constraint filtering; provider
adapters for Azure Foundry, Bedrock, Vertex, OpenAI, Anthropic and a local OpenAI-compatible
runtime; policy evaluation from a cached signed bundle; token and cost accounting; the event
envelope; the per-client onboarding screens and `POST /v1/preflight`.

**Out:** discovery of new models and weighted split/failover (P4), DLP beyond the existing
secret scanner (P6), ClickHouse (P7 — in this phase events go to the queue and a single Postgres
table behind a flag, with the envelope already final).

## Database (revision 0029, 0031)

```
0029  model_providers, model_endpoints (region, zone, deployment_sku, deployment_ref,
      residency_class, attested_at, attested_by, evidence_ref, max_data_class, health),
      model_aliases, alias_targets, model_prices
      backfill: model_deployments → model_endpoints with residency_class='global_unpinned';
                model_routes → alias_targets; nothing above data class 'internal' may route
                to an unattested endpoint after this migration
0031  policies extended with kind; policy_bindings; policy_bundles (from router_config_snapshots)
```

## Gateway surfaces (must all work, day one)

| Surface | Path |
|---|---|
| OpenAI chat completions | `POST /openai/v1/chat/completions` (streaming + non-streaming) |
| OpenAI responses | `POST /openai/v1/responses` — required by Codex CLI; `chat` is deprecated there |
| OpenAI models | `GET /openai/v1/models` — returns only the caller's permitted aliases |
| OpenAI embeddings | `POST /openai/v1/embeddings` |
| Anthropic messages | `POST /anthropic/v1/messages` (streaming + non-streaming) |
| Gemini | `POST /gemini/v1beta/models/{model}:generateContent` and `:streamGenerateContent` |

Fidelity requirements, each with a test: byte-incremental streaming (never buffer a full
completion); tool/function calling round-trips unchanged; `n`, `stop`, `seed`, `response_format`,
`max_tokens`, system prompts and multimodal parts pass through; provider errors translate into the
caller's dialect with the provider's status preserved; `Retry-After` and rate-limit headers are
propagated honestly.

Remember the Cursor caveat: the base-URL override currently carries *all* OpenAI-family traffic
including built-in model picks. Our OpenAI surface must therefore be complete and fast, and
`GET /v1/models` must present aliases the editor can actually select.

## Request path (the nine steps)

Implement in the order in `design/05`, with these hard rules:

- **No database call on the request path.** Everything comes from the in-process bundle cache
  (5 s TTL plus an invalidation channel). If a lookup is missing from the bundle, that is a
  bundle-compilation bug, not a reason to query Postgres.
- **No upstream call before authentication succeeds.** Not even a model list.
- **Filter before score.** Hard constraints (residency, max data class, provider deny, budget
  state, breaker) remove candidates; they are never weighed against preferences. Empty candidate
  set → deny naming the constraint that emptied it.
- **Credentials only from the local vault**, resolved by reference, never accepted from a client
  header and never logged.
- **Deny and approval responses carry reason codes** identical to what the console and audit show.

Latency budget to measure and report in the phase summary: authenticate < 1 ms, resolve < 1 ms,
policy < 1 ms, select < 2 ms, emit (async) < 0.1 ms, total added p95 < 12 ms with inspection off.

## Residency attestation

- `POST /v1/registry/endpoints/{id}/attest` reads the endpoint's configuration from the
  provider's control plane (Azure deployment properties including SKU; Bedrock inference-profile
  description; Vertex endpoint location; OpenAI account residency setting), stores the raw
  response as evidence, and sets `residency_class`, `region`, `zone`, `attested_at`.
- A weekly job re-attests. An attestation older than 30 days degrades to `unverified` and the
  endpoint stops serving data classes above `internal`.
- The console renders **attested** with evidence and date, or **unverified**. Never an inferred
  region presented as proof. Latency is not evidence.
- `GlobalStandard` Azure deployments and Bedrock *global* inference profiles are recorded as
  `global_unpinned` even when the resource sits in the right region, because that is the truth.

## Policy (model kind) — minimum viable set for this phase

```yaml
allowed_aliases: [...]          denied_providers: [...]
residency: region_pinned | eu_zone_or_stricter | any
max_data_class: public | internal | confidential
budget: { monthly_usd, soft_at_pct, on_exhaustion: degrade|approval|block, degrade_to }
on_data_class: { secret_material: block, customer_pii: route_internal }
```

Bundle compilation, signing, publication and cache invalidation are part of this phase, because
the request path depends on them. Bundle expiry behaviour: fail closed for regulated classes,
allow-and-record for the rest, with a global banner both sides.

## Accounting

`cost_micros` computed at ingest from the effective-dated price row for `occurred_at`, integer
arithmetic, stored. Provider-reported tokens preferred; estimated tokens set `tokens_measured=0`
and every surface that displays them says "estimated". Budget decrement in Redis on dispatch.

## Frontend

- **Model routing** screen: providers, endpoints with residency badges and attestation age,
  aliases with their targets, health and breaker state.
- **Endpoint detail**: evidence viewer (the raw provider response that justifies the residency
  claim), attest-now, enable/disable, max data class.
- **Connect a client**: pick client + environment → issue a scoped platform key → show the exact
  config block (Cursor override, `ANTHROPIC_BASE_URL`, `~/.codex/config.toml`,
  `GOOGLE_GEMINI_BASE_URL`) → run preflight → show a green checklist or the failing step with a
  fix link. Also emit the MDM bundle for the org-side controls (Cursor Admin API payload, Claude
  Code managed settings JSON).
- **My requests**: a member's own recent requests with alias, endpoint region, decision, tokens,
  cost, latency.

## Invariants to add

| Name | Assertion |
|---|---|
| `inv_no_upstream_without_auth` | An unauthenticated or revoked key never produces an upstream connection (assert on a spy transport) |
| `inv_no_db_on_request_path` | The request path opens no database connection (assert with a poisoned pool) |
| `inv_hard_constraints_not_weighable` | An endpoint failing residency is never selected, at any weight |
| `inv_unattested_blocks_regulated` | `residency_class='global_unpinned'` cannot receive a class above internal |
| `inv_cost_is_integer` | No float appears in any cost path |
| `inv_stream_not_buffered` | First byte to the client precedes the provider's last byte |
| `inv_credential_never_echoed` | No log line, error body or event contains an upstream credential |

## Test plan

1. Adapter conformance suite per provider, recorded fixtures: non-streaming, streaming, tool
   calls, multimodal, error shapes, rate limits.
2. Real-client smoke: Cursor with the base-URL override, Claude Code with `ANTHROPIC_BASE_URL`,
   Codex with `wire_api = "responses"`, Gemini CLI with `GOOGLE_GEMINI_BASE_URL`. Each must
   complete a real task and appear attributed to the right member. Record the versions used.
3. Latency benchmark with inspection off, 1 000 requests, report p50/p95/p99 added latency.
4. Residency: attest an Azure `Standard` deployment (expect `region_pinned`), a
   `DataZoneStandard` (expect `zone_pinned`), a `GlobalStandard` (expect `global_unpinned`); a
   Bedrock geographic profile (`zone_pinned`) and a global profile (`global_unpinned`).
5. Budget: exhaust a budget and assert the declared behaviour, including the header and event reason.
6. Bundle: publish, invalidate, expire; assert fail-closed for regulated and allow-and-record otherwise.

## Acceptance criteria (the gate)

- [ ] All four clients route through the gateway and every request is attributed to a member, agent, project and environment.
- [ ] p95 added latency under 12 ms with inspection off, measured and reported.
- [ ] Streaming is byte-incremental on all three streaming surfaces.
- [ ] Residency classes are attested from provider evidence, and unattested endpoints cannot serve regulated classes.
- [ ] Token and cost numbers appear per request, integer, with estimated ones marked.
- [ ] Preflight passes for a new member in under three minutes from a standing start.

## Deliverables

Revisions 0029, 0031; the four surfaces; six provider adapters; bundle compiler, signer and
cache; attestation job and evidence viewer; accounting; event envelope (final shape);
model-routing and connect-a-client screens; preflight; seven invariant tests; a
`docs/rollout/clients.md` with pinned client versions; updated `PROJECT_STATE.md`.

## Do not

- Do not implement weighted split or failover here — P4 owns them, and mixing them in makes the
  latency and correctness work impossible to isolate.
- Do not add a "pass-through, no policy" mode as an escape hatch. It will become the default.
- Do not let the gateway read Postgres. Ever.
- Do not claim a region we have not attested, in the UI, the API or a demo.
