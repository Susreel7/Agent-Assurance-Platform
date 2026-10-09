# 08 · Activity graph, scale and cost accounting

Sketch: `diagrams/09-telemetry-and-scale.excalidraw`

> **Amended 2026-09-22.**
>
> **D-16** — Kafka and ClickHouse leave the MVP. The MVP uses **Postgres with time
> partitioning**. ClickHouse arrives when a real customer's volume requires it, and the
> event envelope is designed to be ClickHouse-compatible from day one so the move is an
> ingest change rather than a redesign. Throughput targets below are design aspirations
> with no customer behind them; only ~15–31% of enterprises run any runtime AI control at
> all today `[B-14]`, so the first customer will not be near them.
>
> **D-08** — the **canonical action event** is now defined in
> [`15-capability-governance.md`](15-capability-governance.md) §9 and **supersedes the event
> shapes in this document**. One envelope, `aap.action.v1`, covers every capability kind.
> The additions that matter: a mandatory `enforcement_grade`, the full identity chain
> (version, instance, session, task, delegation), `credential.lease_id`, `session_taint`,
> `prev_event_hash` for tamper evidence, and `downstream_mutation_ref` for the SDLC join.
>
> **AP-9** — evidence suppression is an attack. The existing rule that denies are never shed
> under backpressure is kept, and extended: events are hash-chained per collector so a gap
> is **detectable**, and a missing heartbeat from an enrolled collector is itself an alert.
>
> The cost-accounting content in this document is unchanged and moves to V2.

## The number we design against

| Dimension | Sustained | Burst | Per day |
|---|---|---|---|
| Governed model requests | 100k / 30 min ≈ **56/s** | 560/s | 4.8M |
| Tool calls (~4 per request) | 220/s | 2 200/s | 19M |
| Events | ~280/s | **~3 000/s** | ~25M |
| Compressed event size | ~350 B | — | ~9 GB/day raw, ~1 GB/day after rollup |

25M events/day × 400 days ≈ 10B rows. That is comfortable for a three-node ClickHouse cluster
and impossible for Postgres, which is the whole reason for the split in
[03-data-model.md](03-data-model.md).

## Write path

```
gateway  ──▶ bounded ring buffer (in-process)
         ──▶ collector: batch 1 000 / 200 ms, compress, sign
         ──▶ Kafka / Redpanda, partition by account_id, key = session_id
         ──▶ consumers (independent offsets):
                 a  raw insert into ClickHouse
                 b  rollup aggregation
                 c  risk scoring + alerting
                 d  graph projection
```

Rules:

- **Telemetry never blocks or fails a decision.** Buffer full → spool to disk → still full →
  shed, in a fixed order: sample the `allow` path down, keep **every** `deny`, `approval` and
  DLP finding. Shedding increments a counter that is itself reported, so we never quietly lose
  visibility.
- **At-least-once with `event_id`.** Deduplication is ClickHouse's job
  (`ReplacingMergeTree(ingest_version)`), not the producer's.
- **Ordering only within a session.** Global ordering is not needed and would cap throughput.
- One slow consumer must not stall the others — separate consumer groups, separate offsets.
- Queue retention long enough (72 h) to replay after a bad deploy of a consumer.

## Rollups

Dashboards never touch `ai_events`. Every console query hits a rollup.

```sql
CREATE MATERIALIZED VIEW usage_1h_mv TO usage_1h AS
SELECT
  account_id,
  toStartOfHour(occurred_at)            AS bucket,
  environment, org_path, member_id, agent_kind,
  model_alias, server_slug, tool_name, decision, reason_code,
  count()                               AS events,
  sumIf(1, kind='model.request')        AS requests,
  sum(tokens_in)                        AS tokens_in,
  sum(tokens_out)                       AS tokens_out,
  sum(cost_micros)                      AS cost_micros,
  quantilesTDigestState(0.5,0.95,0.99)(latency_ms) AS latency_state,
  uniqState(member_id)                  AS actors_state,
  sumIf(1, decision='deny')             AS denials
FROM ai_events
GROUP BY account_id, bucket, environment, org_path, member_id, agent_kind,
         model_alias, server_slug, tool_name, decision, reason_code;
```

Three grains: `usage_1m` (live tail, 48 h TTL), `usage_1h` (the workhorse, 90 days),
`usage_1d` (trends and invoices, 400 days+). A manager view is a prefix match on `org_path`
over `usage_1h`, which is an index scan over a few thousand rows.

### Cardinality discipline

The thing that actually kills systems like this.

| Allowed as a dimension | Never a dimension |
|---|---|
| member, agent kind, alias, server, tool, decision, reason code, environment, org_path | prompt text, request id, argument values, free-form model strings, IP addresses, session id (except in the 1m grain) |

Beyond top-N per bucket the tail folds into `other`, and the exact answer remains available in
raw events for the retention window. `org_path` is bounded by the org tree, which is why the
tree has to be real rather than free-form tags.

## Algorithms, and why each one

| Algorithm | Used for | Why not the obvious thing |
|---|---|---|
| t-digest (`quantilesTDigestState`) | p50/p95/p99 latency per bucket | Mergeable across buckets; you cannot average percentiles |
| HyperLogLog (`uniqState`) | active people per org unit per period | `count(distinct)` over a billion rows does not fit a dashboard |
| count-min sketch | top-K tools/models under fixed memory | Exact top-K needs the full key space |
| EWMA + MAD | per-subject anomaly baselines | Robust to the outliers that are exactly what we are looking for |
| Closure table | hierarchy reads | Recursive CTEs per request will not hold p95 |
| Token bucket in Redis | per-subject rate limits | One round trip, bounded memory, no hot-row contention |
| Bloom filter over secret fingerprints | "this secret again" without storing secrets | Set membership without the set |
| Aho–Corasick | literal/prefix DLP scan | One pass for hundreds of patterns |
| Reservoir sampling | payload retention under a quota | Unbiased sample when we cannot keep everything |

## Cost and token accounting

1. Tokens come from the provider response. When a provider omits usage we estimate with a
   tokeniser and set `tokens_measured = 0`; **every** surface that shows that number says
   "estimated".
2. `cost_micros` is computed **at ingest** from the effective-dated `model_prices` row for
   `occurred_at`, as integers. Stored, not recomputed on read, so a price change cannot rewrite
   history behind an operator's back.
3. A price correction runs a bounded recompute that writes a new `ingest_version` with a
   reason, and the affected reports show a "restated" marker.
4. Enforcement budgets live in Redis (decrement on dispatch, cheap) and reconcile hourly
   against ClickHouse (authoritative). Divergence over a threshold is an alert, because it
   usually means events are being dropped.
5. Attribution: cost lands on the member's **primary** org unit, so subtree sums do not
   double-count matrixed people. Shared agents and CI identities attribute to the org unit of
   the service identity, with the triggering member recorded as a second dimension so both
   questions ("what did this team spend" and "who caused it") are answerable.
6. Reconciliation against the provider invoice is a first-class report: our sum, their invoice,
   the delta, and the requests we could not attribute. Within 1% is the phase-8 gate.

## The activity graph

Not a nicety — it is the answer to every question a security team actually asks.

```sql
CREATE TABLE graph_edges (
  account_id UUID,
  from_kind LowCardinality(String), from_id String,   -- member | agent | session | model | server | tool | resource | provider
  to_kind   LowCardinality(String), to_id   String,
  edge      LowCardinality(String),                   -- uses | invokes | reaches | sends_to | reads | writes
  first_seen DateTime, last_seen DateTime,
  call_count UInt64,
  data_classes Array(LowCardinality(String)),
  max_risk UInt16,
  environment LowCardinality(String)
) ENGINE = ReplacingMergeTree(last_seen)
ORDER BY (account_id, from_kind, from_id, to_kind, to_id, edge);
```

Projected from the same stream that writes raw events, so the graph cannot disagree with the
evidence. Queries are bounded traversals (depth ≤ 4) with the supporting events attached — a
security engineer will not act on an edge they cannot expand into the calls that created it.

This is the moat described in the strategy: over time the graph learns who uses which agent,
which model, which MCP server, which resource, and with which data classes. Then
"what would happen if this MCP server were compromised" becomes a reachability query rather
than a workshop.

## Retention

| Tier | Window | Contents |
|---|---|---|
| Live (1m rollup) | 48 h | Live tail, incident response |
| Hot (raw + 1h) | 30 days | Drill-down, investigations |
| Cold (object storage) | 400 days | Audit, invoices, trend |
| Audit (Postgres, hash-chained) | Forever | Who changed the rules |
| Payload bodies (customer store) | Hours to 7 days, per account | Investigation only, reveal is audited |
| Legal hold | Indefinite, per subject | Excluded from every TTL, and the exclusion is itself audited |

## Load shedding and failure modes

| Failure | Behaviour | Visible as |
|---|---|---|
| Queue unavailable | Spool to disk; keep enforcing | banner: telemetry delayed |
| ClickHouse unavailable | Queue grows; dashboards serve last-known with a freshness timestamp | "as of 14:02" on every tile |
| Bundle expired | Fail closed for regulated classes, allow-and-record for the rest | global banner, alert both planes |
| Redis (budgets/limits) unavailable | Rate limits fail open, budgets fail open, both recorded as degraded | degraded badge on cost views |
| Inspector timeout | Treat as a finding of the configured severity (default: block for regulated destinations) | event reason `inspect_timeout` |

Every one of these is a declared, tested behaviour. "Unknown" is not an acceptable answer for
what a security control does when its dependency is down.
