# Phase 7 — Activity pipeline, rollups and the AI activity graph

> **HISTORICAL — DO NOT EXECUTE.** It would create a second activity pipeline beside the
> existing Observe/ClickHouse system and contradict D-16. The MVP ledger is partitioned
> Postgres through F1/M3.

> Paste this whole file as the only prompt of a fresh session.

## Objective

Store every AI action at enterprise volume and answer questions about it in under 300 ms:
100k governed requests per 30 minutes sustained, ~3 000 events/s at peak, ~25M events/day, with
rollups that dashboards actually read, sketches instead of exact scans, and a graph that answers
"which agents could reach our customer database".

## Prerequisite

Phase 3 (events are being emitted with the final envelope) and Phase 2 (visibility, since every
read is scoped).

## Read first

- `design/08-activity-and-scale.md` — all of it
- `design/03-data-model.md` §F
- `design/diagrams/09-telemetry-and-scale.excalidraw`

## Scope

**In:** the collector with buffering, spooling and ordered shedding; the queue; four independent
consumers; ClickHouse schema with partitioning and TTL; three rollup grains with t-digest and
HyperLogLog states; the graph projection; the payload store with digest addressing; retention and
legal hold; moving every dashboard onto `/v1/insights/*`; the live tail.

**Out:** alerting and forecasting (P8), new dashboards (P8 extends; this phase moves the existing
ones onto rollups without changing their contracts).

## Infrastructure

Add to the data plane: Redpanda (or Kafka) and ClickHouse. Both must come up in
`docker-compose.yml` for local work and be Helm-charted in P9. Retention on the queue: 72 hours,
so a bad consumer deploy can be replayed rather than mourned.

## Event envelope

Already fixed in Phase 3 — do not change it here; extend only by adding nullable columns.
Keep `gen_ai.*` naming alignment with the OpenTelemetry GenAI conventions where a field maps
cleanly (`gen_ai.operation.name`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`,
`gen_ai.usage.output_tokens`), noting in a comment that those conventions are still in
development and pinning the revision we translated from. Our storage schema is ours; the export
mapping is where the convention applies.

## Write path

```
gateway ring buffer (bounded, in-process)
   → collector: batch 1 000 or 200 ms, compress, sign
   → queue, partition by account_id, key session_id
   → consumers, independent offsets:
       a raw insert (batched, ≥ 10k rows or 1 s)
       b rollup aggregation
       c risk scoring
       d graph projection
```

Non-negotiables:

- Telemetry never blocks or fails a decision. Buffer full → disk spool → still full → shed in a
  fixed order: sample `allow` down, **keep every** `deny`, `approval` and DLP finding. Shedding
  increments a reported counter; silent loss of visibility is the one failure a security product
  cannot have.
- At-least-once with `event_id`; dedup is ClickHouse's job via `ReplacingMergeTree(ingest_version)`.
- Ordering only within a session.
- One slow consumer stalls nothing else.

## Storage and rollups

`ai_events` exactly as in `design/03` §F: day partitions, `ORDER BY (account_id, occurred_at,
event_id)`, ZSTD, `LowCardinality` on every enumerable column, TTL 30 days hot → cold volume →
400 days delete, plus a legal-hold exclusion.

Three grains via materialised views:

| Table | Grain | TTL | Used by |
|---|---|---|---|
| `usage_1m` | minute | 48 h | live tail, incident response |
| `usage_1h` | hour | 90 d | every dashboard |
| `usage_1d` | day | 400 d+ | trends, invoices, reconciliation |

Each carries `quantilesTDigestState` for latency, `uniqState` for actors, counts, tokens,
`cost_micros`, and denial counts by reason code.

**Cardinality discipline is a review gate.** Allowed dimensions: member, agent kind, alias,
server, tool, decision, reason code, environment, `org_path`. Never: prompt text, request id,
argument values, IPs, session id outside the 1m grain. Beyond top-N per bucket, fold the tail into
`other`; the exact answer stays in raw events for the retention window.

## Read path

- Every console query hits a rollup. Add a test that fails if any `/v1/insights/*` handler
  references `ai_events`.
- `scope` is intersected with `visible_paths(caller)` from Phase 2 before the query is built.
- Manager views are `org_path` prefix scans.
- Drill-down to raw events requires a narrow window plus one subject, and the read is audited.
- Every aggregate response carries `freshness_at`, and the UI displays it.

## The graph

`graph_edges` as specified, projected from the same stream that writes raw events so the graph can
never disagree with the evidence. Bounded traversals (depth ≤ 4) with supporting events attached.

Ship these five as buttons, not a query language:

1. Which agents reached the production database MCP in the last 30 days?
2. Which external providers received `source_code` from this business unit?
3. If this member is compromised, what can their agents reach today?
4. Which MCP servers can touch `customer_pii`, and who holds a grant?
5. Which tools were called with arguments matching a protected resource pattern?

## Payload store

Content-addressed by digest in the customer's object store (S3/Azure Blob/MinIO), encrypted with
the customer's key, TTL from `accounts.retention_profile`. `ai_events.payload_ref` holds the
digest and location. Reading one requires `payload:reveal` plus an approval (Phase 2 machinery) and
writes an audit row naming the approver. The control plane never proxies a payload.

## Invariants to add

| Name | Assertion |
|---|---|
| `inv_telemetry_never_blocks` | With the queue down, requests still succeed and denials still enforce |
| `inv_denials_never_shed` | Under maximum shedding, every `deny` event still arrives |
| `inv_dashboards_never_scan_raw` | No insights handler references `ai_events` |
| `inv_event_dedup` | The same `event_id` delivered twice yields one row |
| `inv_cardinality_bounded` | Rollup dimension sets are enumerable; a new free-form dimension fails the test |
| `inv_payload_requires_approval` | A payload read without a live approval is refused and audited |
| `inv_legal_hold_survives_ttl` | A held subject's events are not deleted by TTL |

## Test plan

1. Load test: 3 000 events/s for 30 minutes into a local cluster; report ingest lag, CPU, disk
   growth and dashboard p95 during load.
2. Chaos: kill the queue, then ClickHouse, then Redis mid-load; assert the declared behaviour of
   each from the failure-modes table, and that no request failed because of telemetry.
3. Shedding: drive the buffer past capacity; assert allow-sampling engaged, every deny arrived, and
   the shed counter is reported.
4. Rollup correctness: for a fixture day, assert rollup sums equal raw sums exactly, and that
   t-digest p95 is within tolerance of the exact value.
5. Prefix query: 2 000 org units, 20 000 members; a manager subtree query under 300 ms p95.
6. Graph: each of the five questions returns the expected subgraph on a seeded fixture, with
   supporting events attached.
7. Migration: existing Postgres activity tables continue to serve reads while the new path runs;
   numbers match side by side for seven days before cutover.

## Acceptance criteria (the gate)

- [ ] 3 000 events/s sustained for 30 minutes with ingest lag under 10 s.
- [ ] Dashboard p95 under 300 ms during that load, from rollups only.
- [ ] Rollup sums equal raw sums for a fixture day.
- [ ] Under maximum shedding, no `deny` event is lost, and shedding is visible.
- [ ] All five graph questions answerable from the UI with evidence attached.
- [ ] Payload reads require an approval and are audited.
- [ ] Every dashboard reads `/v1/insights/*` and shows `freshness_at`.

## Deliverables

Collector with spool and shedding; queue and four consumers; ClickHouse schema, three rollups and
retention; graph projection and the five queries; payload store; `/v1/insights/*` completed; live
tail with a bounded buffer; dashboards moved over; compose and Helm additions; seven invariant
tests; a load-test report committed under `docs/perf/`; updated `PROJECT_STATE.md`.

## Do not

- Do not let a dashboard query raw events "just this once".
- Do not add a free-form dimension to a rollup. Cardinality is how these systems die.
- Do not make telemetry synchronous to "guarantee" delivery. Enforcement is the guarantee;
  telemetry is best-effort with a counted, visible loss path.
- Do not change the event envelope. Extend with nullable columns only.
