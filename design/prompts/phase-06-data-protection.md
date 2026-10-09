# Phase 6 — Data protection: secrets, PII, tokenisation

> **HISTORICAL — DO NOT EXECUTE.** D-16 removed the six-layer DLP stack from the MVP.
> Data protection is a later pluggable interface with measured false-positive gates; it is
> not a prompt-injection solution.

> Paste this whole file as the only prompt of a fresh session.

## Objective

Make "what happens if a developer pastes customer PII or an API key into a prompt" a designed,
measured, explainable behaviour — with an action matrix per data class and destination, reversible
tokenisation that never leaves the customer boundary, response-side scanning, and a false-positive
rate we measure before any rule is allowed to block.

## Prerequisite

Phase 3 (model gateway) and ideally Phase 5 (MCP gateway), because the inspector is called from
both paths through one interface.

## Read first

- `design/07-data-protection.md` — all of it, including "Stated limits"
- `design/05-model-gateway.md` — step 4 and step 7 of the lifecycle
- `design/diagrams/08-data-protection.excalidraw`

## Scope

**In:** the six detection layers; data classes with confidence; the action matrix; annotate mode
with measured false-positive rates; masking; reversible tokenisation with a KMS-backed vault
including the streaming path; response-side scanning; incidents and alerts; the DLP screens.

**Out:** anomaly detection over history (P8), the graph (P7). This phase is about the request
path.

## Database (revision 0038)

```
0038  dlp_rules (kind, pattern_ref, class, confidence_default, mode annotate|enforce,
                 fp_rate_measured, measured_over, enabled_at)
      dlp_actions (class, destination_residency, action, requires_approval)  -- the matrix
      dlp_findings_daily (small Postgres rollup for the tuning screen)
      token_vault (token, ciphertext, session_id, class, kms_key_ref, expires_at)
      incidents (kind, severity, member_id, agent_id, policy_id, evidence_ref, state, assignee)
```

`token_vault` lives in the **data plane** database. It must not be reachable from the control
plane, and no API returns a plaintext value from it — detokenisation happens in the response path
only.

## The inspector

An **in-process library**, not a sidecar. A network hop per request breaks the p95 budget.

Interface used identically by the model gateway and the MCP gateway:

```go
type Finding struct { Kind, Class string; Confidence float32; Start, Len int; Fingerprint string }
type Verdict  struct { Action string; Findings []Finding; Transformed []byte; Reason string }

func Inspect(ctx, payload []byte, dest Destination, subj Subject) Verdict
```

Normalisation before detection: decode JSON and scan **both** raw bytes and decoded string values
at any depth (a raw-only scan is bypassed by `sk-\u0070roj-…` — keep the existing regression
test), unescape, decompress where cheap, and walk tool arguments, tool results, system prompts and
attachments. Attachments over the size cap are a policy decision, never a silent pass.

Layers, cheapest first, with early exit on a clean short payload:

1. Aho–Corasick over literals and prefixes: `sk-`, `sk-ant-`, `ghp_`, `gho_`, `AKIA`, `ASIA`,
   `xoxb-`, `xapp-`, `AIza`, `-----BEGIN`, `eyJ`, `Bearer `.
2. Structural with checksums: Luhn, IBAN, SSN/NI, PAN/Aadhaar, VAT. **Checksum before reporting** —
   this is where naive DLP generates the noise that gets it switched off.
3. Entropy: base64/hex runs over length and entropy thresholds, context-filtered so a git SHA is
   not a secret.
4. Named entities: person, address, phone, DOB. Time-boxed, and only when layers 1–3 or the route
   warrant it.
5. Schema-aware: values matching sensitive column and table names from the customer's catalogue —
   the highest-precision layer when the catalogue exists, so ask for it during onboarding.
6. Code-aware: secrets in diffs and `.env`, connection strings, private keys, proprietary markers.

Performance target: p95 under 8 ms on a 32 KB payload, benchmarked and reported. Compiled
patterns cached per policy version; regexes hoisted, never compiled per request.

## The action matrix

Classes: `secret_material` · `customer_pii` · `employee_pii` · `health` · `financial` ·
`regulated_record` · `source_code` · `internal_doc` · `public`.
Actions: `allow` · `annotate` · `mask` · `tokenize` · `route_internal` · `require_approval` ·
`block`.

Seed the defaults from the table in `design/07`, keyed by `(class, destination residency class)`,
editable per account. Two rules enforced in code:

- **`secret_material` can only be `block` or `mask`.** The API refuses to store `tokenize` for it;
  a reversible credential is still a credential.
- **A rule may not block until it has been measured.** New rules are created in `annotate` mode;
  `mode='enforce'` is refused until `fp_rate_measured` exists over at least a configured volume,
  and the UI shows the rate next to the toggle.

## Reversible tokenisation

- Token form `<TYPE>_<n>`; stable within a session, distinct across sessions.
- Vault row: AEAD ciphertext under a per-account KMS key, session id as associated data, TTL in
  hours, then unrecoverable.
- Detokenise on the response path inside the boundary, **including streamed responses** — keep a
  small rolling window so a token split across chunks is still replaced. This needs its own test;
  getting it wrong shows a developer `<PERSON_1>` and destroys trust in one sitting.
- Optional format-preserving tokens as a separate opt-in operator with their own key handling.
- Never tokenise a whole codebase: for `source_code` the control is the destination.

## Response-side inspection

| Check | Action |
|---|---|
| Secret in the completion | Redact, raise `credential_attempt` incident |
| PII in a completion that had none in the prompt | Flag — the model or a tool retrieved it |
| Secret in a tool result, then an outbound model call | Block the second call, open a `critical` incident |
| Instruction-like text inside fetched content | Annotate as suspected injection, raise session risk, require approval for the next write |

## Frontend

- **Data protection** overview: findings by class and action over time, top classes, top
  destinations, the block/annotate mix.
- **Rules**: each rule with its mode, measured FP rate, sample count, last change, and a toggle
  that is disabled with an explanation until the rate exists.
- **Matrix editor**: class × destination grid, with the `secret_material` cells locked and a
  tooltip saying why.
- **Incidents**: queue with severity, member, agent, policy, evidence, assignee, state, and the
  one-click actions (revoke, restrict, require approval, close with a reason).
- **Member-facing explanation**: when a request is blocked, the developer sees the class, the
  policy, and the named alternative — in the client error *and* in "My AI".
- **Limits statement** on the DLP screen, in the product's own voice, as drafted in `design/07`.

## Invariants to add

| Name | Assertion |
|---|---|
| `inv_json_escape_not_bypassable` | A JSON-escaped secret is detected (regression test, keep forever) |
| `inv_secret_never_tokenised` | `secret_material` cannot be configured as `tokenize` |
| `inv_no_enforce_without_measurement` | A rule cannot enter `enforce` without a measured FP rate |
| `inv_token_map_local_only` | No control-plane endpoint can read `token_vault` |
| `inv_detokenise_streaming` | A token split across stream chunks is still restored |
| `inv_findings_store_no_values` | No stored row contains a detected value |
| `inv_inspect_timeout_fails_safe` | An inspector timeout applies the configured severity, default block for regulated destinations |

## Test plan

1. Corpus test: a labelled fixture corpus (synthetic secrets, real-shaped PII, code with and
   without credentials, clean prompts) with asserted precision and recall per layer, and a
   published FP rate per rule.
2. Bypass suite: JSON escapes, unicode homoglyphs, base64 wrapping, chunk splitting across
   messages, zero-width characters, nested tool arguments, gzip'd attachments.
3. Round-trip test: the worked example in `design/07` — the provider receives tokens, the
   developer receives values, the event stores neither.
4. Streaming round trip: token straddling a chunk boundary, and a long completion with 50 tokens.
5. Matrix test: every `(class, destination)` pair produces the configured action, and the reason
   reaches the client.
6. Incident test: the exfiltration shape (secret in tool output, then an outbound call) produces a
   `critical` incident and blocks the second call.
7. Benchmark: p95 inspection time on 1 KB, 32 KB and 256 KB payloads, reported in the summary.

## Acceptance criteria (the gate)

- [ ] Every rule has a measured false-positive rate on real traffic before it can block.
- [ ] A tokenised round trip returns real values to the developer and never to the provider, including in streams.
- [ ] `secret_material` is impossible to configure as reversible.
- [ ] The bypass suite passes in full.
- [ ] p95 inspection under 8 ms at 32 KB, reported.
- [ ] A blocked developer sees the class, the policy and a named alternative, in the client and the console.
- [ ] The stated-limits text is live on the DLP screen.

## Deliverables

Revision 0038; the inspector library with six layers; the action matrix with its locks; the token
vault with streaming detokenisation; response-side checks; incidents; DLP overview, rules, matrix
and incident screens; member-facing explanations; seven invariant tests; the labelled corpus and
its published metrics; updated `PROJECT_STATE.md`.

## Do not

- Do not ship a rule in enforce mode because it "obviously" works. The corpus decides.
- Do not store a detected value anywhere, including logs, traces and error messages.
- Do not put the inspector behind a network call.
- Do not claim, anywhere in the product, that detection guarantees nothing sensitive was sent.
