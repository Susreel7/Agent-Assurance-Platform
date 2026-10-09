# 07 · Data protection — secrets and PII

Sketch: `diagrams/08-data-protection.excalidraw`

> **Amended 2026-09-22.**
>
> **D-16** — the six-layer detector stack leaves the MVP. Data protection becomes **one
> pluggable interface** with a small, high-precision rule set. Multimodal input, images,
> audio, video, OCR, embeddings and vector-store inspection are explicitly **later**, not
> now, and must not be claimed as supported.
>
> **D-11** — this pipeline **cannot** be presented as an egress control for Cursor. Content
> reaches Cursor's backend before it reaches us `[B-41]`.
>
> **D-16 (policy boundary)** — the policy engine evaluates **argument facets**, never raw
> content. Raw arguments never enter the policy engine, the control plane, or a log line.
> See [`15-capability-governance.md`](15-capability-governance.md) §9.
>
> **What is not being attempted.** This is not a prompt-injection defence. A 2026 formal
> result argues perfect prevention is unachievable at the model layer `[B-11]`, and adaptive
> attacks achieve **>90% success** against deployed commercial detectors that report near-0%
> under static evaluation `[B-12]`. The enforceable controls are capability reduction,
> session taint and credential scoping — see [`13-threat-model.md`](13-threat-model.md) §7 —
> not better detection.
>
> The rule below — *measure the false-positive rate before a rule may block* — is kept
> exactly as written. It is one of the best decisions in this folder.

Answering, precisely: *if a user passes PII in a prompt, what happens?*

## Pipeline

```
request body (prompt, messages, tool arguments, attachments)
   ↓  normalise: decode JSON, unescape, decompress, flatten nested strings
   ↓  DETECT     layered, cheapest first, with early exit for clean short payloads
   ↓  CLASSIFY   findings → data classes, with confidence
   ↓  DECIDE     (class × destination × subject × environment) → action
   ↓  TRANSFORM  mask / tokenize / truncate, or stop here for block
   ↓  DISPATCH   to the chosen endpoint
   ↓  INSPECT    scan the response
   ↓  RESTORE    detokenise inside the boundary
   ↓  RECORD     finding kinds, classes, counts, digests, decision — never the values
```

The inspector is an **in-process library**, not a network hop. A sidecar adds a round trip to
every request on the hot path and the p95 budget does not survive it.

## Detection layers

| Layer | Finds | Cost | Notes |
|---|---|---|---|
| 1 · Literal and prefix | `sk-`, `sk-ant-`, `ghp_`, `gho_`, `AKIA`, `ASIA`, `xoxb-`, `xapp-`, `AIza`, `-----BEGIN * PRIVATE KEY`, `eyJ` JWTs, `Bearer ` | ~free | Aho–Corasick over one pass |
| 2 · Structural + checksum | credit cards (Luhn), IBAN, NI/SSN, Aadhaar/PAN, VAT, UUID-shaped record ids | low | Checksum before reporting — this is where naive regex DLP generates its noise |
| 3 · Entropy | base64/hex runs above a length and entropy threshold, context-filtered (a git SHA is not a secret) | low | The only way to catch unknown credential formats |
| 4 · Named entity | person, address, phone, email, org, date of birth | medium | Model-based; runs only when layers 1–3 or the route suggest it, and is time-boxed |
| 5 · Schema-aware | values matching known sensitive column/table names from the customer's data catalogue | low | Very high precision when the catalogue exists — ask for it in onboarding |
| 6 · Code-aware | secrets in diffs and `.env`, connection strings, private keys, hard-coded tokens, proprietary markers | medium | The dominant case for coding agents |

Two implementation rules learned the hard way:

- **Scan the raw bytes *and* the JSON-decoded values.** `sk-\u0070roj-…` is not caught by a raw
  scan, and a raw-only scanner is trivially bypassed. (The current gateway had exactly this
  hole; keep the regression test.)
- **Scan every string, at any depth**, including tool arguments, tool results, system prompts,
  file attachments and base64 blobs we can cheaply decode. Attachments over a size cap are
  policy decisions, not silent passes.

## Classes and the action matrix

Classes: `secret_material` · `customer_pii` · `employee_pii` · `health` · `financial` ·
`regulated_record` · `source_code` · `internal_doc` · `public`.

Actions: `allow` · `annotate` · `mask` · `tokenize` · `route_internal` · `require_approval` ·
`block`.

Default matrix — per account, per destination residency class, editable, and this is the table
a CISO will read first:

| Class | `region_pinned` internal | `zone_pinned` external | `global_unpinned` external |
|---|---|---|---|
| `secret_material` | block | block | block |
| `customer_pii` | tokenize | route_internal | block |
| `health` / `regulated_record` | tokenize | block | block |
| `financial` | tokenize | require_approval | block |
| `employee_pii` | tokenize | tokenize | block |
| `source_code` | allow | allow | require_approval |
| `internal_doc` | allow | allow | annotate |
| `public` | allow | allow | allow |

Rules about the matrix itself:

- **Never tokenise a credential.** A reversible credential is still a credential. `secret_material`
  is block or mask, always.
- **New rules ship in `annotate` first.** A rule may not be allowed to block until it has run
  in annotate mode on the customer's own traffic and its false-positive rate is measured and
  displayed. A DLP product that blocks working prompts on day one gets switched off in week one.
- Low-confidence findings can be configured to `annotate` while high-confidence ones block, so
  precision and safety are tuned independently.

## Reversible tokenisation

For classes where the model needs to reason about the entity but must not receive the value.

```
prompt in        "summarise churn risk for John Smith, account 4471-2288"
to provider      "summarise churn risk for <PERSON_1>, account <ACCOUNT_1>"
provider out     "<PERSON_1> is high risk because account <ACCOUNT_1> has …"
to developer     "John Smith is high risk because account 4471-2288 has …"
recorded         classes [customer_pii], counts {person:1, account:1}, action tokenize, policy DATA-004
```

Implementation:

- `token = <TYPE>_<n>`, stable **within a session** so multi-turn reasoning holds together, and
  different across sessions so tokens are not a cross-session identifier.
- Vault row: `token → AEAD(value)` under a per-account key from the customer's KMS, with the
  session id as associated data. TTL in hours, then unrecoverable.
- Detokenisation happens in the data plane on the response path, before the client sees
  anything, including in streaming responses — which means the streaming path needs a small
  rolling window so a token split across chunks is still replaced.
- The control plane never receives the map. Not even for support.
- Format-preserving tokens (an account number that still looks like an account number) are
  available where the model needs the shape; they are a separate, opt-in operator because FPE
  needs its own key management and is easy to get wrong.

Explicit non-goal: tokenising an entire codebase. For `source_code` the control is the
destination (`route_internal` or `require_approval`), not transformation.

## Response-side inspection

The direction most products forget, and the one that matters for exfiltration.

| Check | Action |
|---|---|
| Secret in the completion (a model echoing a key, or a tool result carrying one) | Redact and raise an incident — the secret has now been in two places |
| PII in a completion that had none in the prompt | Flag: the model or a tool retrieved it |
| Tool result containing a secret, followed by an outbound model call | The exfiltration shape — block the second call and open a case |
| Instruction-like text inside fetched content (`ignore previous`, `run this`) | Annotate the event as suspected injection, raise the session's risk, require approval for the next write |

## What is stored, and what never is

| Stored | Never stored |
|---|---|
| Finding kinds, classes, counts, offsets-by-length (not offsets into text we keep) | The detected values |
| Digest of the payload, plus a local reference | The payload, in the control plane |
| A one-way fingerprint of a blocked secret (for "same secret, again") | The secret, in any form, anywhere |
| Decision, policy id, reason code, confidence | Anything that would let a vendor engineer reconstruct a prompt |

## Signals this produces

| Alert | Condition | Severity |
|---|---|---|
| `credential_attempt` | any `secret_material` block | always an incident, never a metric |
| `repeat_offender` | same member, same class, N times in a window | medium |
| `novel_destination` | a class reaching a provider it never has for this account | high |
| `exfil_shape` | secret in tool output then an outbound model call | critical |
| `prompt_hygiene` | oversized context, whole-repo paste, prod connection string | low, coaching |
| `tokenisation_failure` | detokenise miss on the response path | high — the developer got a token instead of a value, and will lose trust fast |

Every alert names the member, the agent, the policy, the reason code and the evidence, and
offers the one-click actions: revoke, restrict, require approval, open a case.

## Stated limits — in the product, not only here

Put this on the DLP screen, in this tone:

> Detection reduces risk. It does not prove that nothing sensitive was sent. Names, addresses,
> paraphrased secrets and novel formats are missed by every detector, including ours. For the
> classes you cannot afford to leak, set the destination — route them to a model you control —
> rather than relying on redaction confidence.

A security engineer who reads that trusts the rest of the product more, not less. A customer
who discovers the limitation after an incident does not.
