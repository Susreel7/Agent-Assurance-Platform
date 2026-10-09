# M3 — Action ingest (`aap.action.v1`)

> Paste this whole file as the only prompt of a fresh session.
> Prerequisite: F1 schema, M1 identity chain. This is the **critical path**. If three
> vendors cannot land in one envelope, stop — the capability abstraction is wrong.

## Objective

Land agent activity from Claude Code and Cursor into the `agent_actions` table as
`aap.action.v1`, with **no customer content stored**, and with `enforcement_grade`
mandatory. After this session an investigator can list actions even if the UI is still
Observe's execution list.

## Read first

- `design/15-capability-governance.md` §9 (envelope) and §3 (kinds)
- `design/12-strategic-thesis.md` §5 (grades)
- `design/05-model-gateway.md` honest Cursor section (D-11 / D-070)
- `design/13-threat-model.md` AP-1
- Existing Observe ingest / OTLP if present (`services/observe-*`, `operations`)
- Claude Code OTLP docs mentally as `[B-34]`; Cursor Admin API `[B-39]` — do not claim
  prompt bodies from Cursor.

## Scope

**In:**

1. `POST /v1/actions/ingest` (authenticated by Platform Key / instance credential).
   Validates envelope, fills `received_at`, hashes `event_hash`, links `prev_event_hash`
   per collector, claims `agent_action_receipts` and inserts into `agent_actions` in one
   transaction. Idempotent on `(org_id, event_id)` even if a retry changes its timestamp.
2. **Claude Code collector:** accept OTLP or the hook JSON we will emit in M4. Map
   `Bash` / `Read` / HTTP-ish tools onto `shell.exec` / `fs.read` / `net.http`. Grade **B**
   when a hook decision is present, **D** when only logs/OTLP arrived.
3. **Cursor collector:** Admin API usage pull **and/or** hook events. Model traffic is
   grade **D** at best. MCP tool events may be grade **A** if they came through our
   gateway — they will not in MVP, so do not mark them A. Cursor prompts **must not**
   appear in any column.
4. Copilot: if the metrics/audit API is a day's work, include a **D**-grade usage
   mapper. If it is more, stub the adapter and record the gap as grade E coverage — do
   not block Claude + Cursor.
5. Map unknown tools to a bounded capability identifier and
   `enforcement_grade=unknown` (query-time E).
6. Add typed `GET /v1/agent-actions` and `GET /v1/agent-actions/{id}` endpoints. The
   control-plane API owns the ledger table. Observe may link to or call this API, but the
   independent Observe service must not read the control-plane table directly.
7. Keep existing Observe execution telemetry untouched. Link by trace/session/source IDs;
   do not dual-write into its ClickHouse schema in the MVP.

**Out:** blocking, Cedar, MCP gateway, DLP, ClickHouse, Kafka. No `curl` of provider
APIs using a user's long-lived token stored in our DB.

## Grade assignment rules (do not improvise)

| How we saw it | Grade |
|---|---|
| In-path proxy we operate | A |
| Hook result with veto capability (even if outcome was allow) | B |
| Vendor policy attested, not in path | C |
| Usage/audit API after the fact | D |
| Missing collector / unknown client | E / unknown |

Cursor chat completions: **D**. Never A.

## Privacy

`arguments.digest` + allow-listed bounded facets only (`binary`, destination host class,
HTTP method, normalized path **class/prefix**, `sql_verbs`). Never store a full command,
URL query string, arbitrary HTTP header, environment value or absolute credential path.
A test greps ingested rows for typical secret patterns and fails the suite if a raw token
lands.

## Invariants

| Name | Assertion |
|---|---|
| `inv_ingest_idempotent` | Same `event_id` twice → one row |
| `inv_ingest_requires_human` | Envelope without human is 422 |
| `inv_ingest_requires_grade` | Missing grade is 422, not default-A |
| `inv_no_payload_persisted` | Request bodies with a `prompt` field are dropped; row has no prompt |
| `inv_cross_org_ingest` | Key from org A cannot write org B |
| `inv_hash_chain` | Second event from same collector stores `prev_event_hash` of the first |
| `inv_unknown_is_e` | Unknown grade is counted and rendered as E, never protected |
| `inv_observe_boundary` | Observe service does not import API models or query `agent_actions` |

## Gate

- [ ] Fixture: Claude Code Bash event and Cursor Admin usage event both queryable as
      actions.
- [ ] Cursor fixture containing a prompt string does not persist that string.
- [ ] `GET /v1/agent-actions` shows both with grades (even if the chip is in
      JSON only until M5).
- [ ] `PROJECT_STATE.md` updated.

## Do not

- Do not stand up a model gateway "to make ingest easier".
- Do not parse full shell grammar. Facets: binary, flags, hosts, paths.
- Do not call this "prevention". It is evidence.
- Do not persist the raw vendor event after normalization.
