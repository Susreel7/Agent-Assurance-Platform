# Data paths

Four stores, four jobs. None of them is a substitute for another.

## PostgreSQL — durable metadata

The control plane keeps relational state here: accounts, members, agents, versions, policy, evidence, grants, and the action ledger.

The action ledger (`agent_actions`) is content-free and append-only. A row records that an action happened, which harness produced it, which human root it hangs from, and an enforcement grade. It does not record the prompt, the completion, a raw command line, or a raw tool argument. Monthly partitions make retention a `DROP TABLE` rather than a delete across the whole history.

Observe also uses PostgreSQL for durable metadata and its outbox. Redis is never the only copy of a fact that must survive a restart.

No extension beyond `pgcrypto` is required, so the same schema runs on RDS, Azure Database for PostgreSQL, and Cloud SQL.

## ClickHouse — high-volume traces

Hot observations, events, and edges live in ClickHouse. This is the analytical path: time-range scans over a long-running agent, not the system of record for who is allowed to do what.

The control plane does not query ClickHouse for an authorization decision. Observe projects a bounded, content-free summary back to the Operations domain when the control plane needs a count.

## Redis — ephemeral propagation

Redis holds streams, queues, cache, and limit state. A lost Redis is a delay, not a lost ledger. Anything that must be true after a restart is written to PostgreSQL or object storage first.

## Protected content

Large payloads, when capture is enabled, go to object storage encrypted with a key injected from a secret manager. The local default is a filesystem path. BYOC points that provider at the customer's bucket. The key is not in this repository.

Evidence and the action ledger stay content-free even when capture is on. Capture is a separate path with a separate key, so a reviewer can inspect the ledger without being handed the prompt.

## What a query is allowed to mean

| Question | Store |
|---|---|
| Who is this member, and which grants do they hold? | PostgreSQL |
| What did this agent do, at which enforcement grade? | PostgreSQL ledger |
| What does the trace of this run look like over time? | ClickHouse, via Observe |
| Is this request still inside its rate limit? | Redis |
| What was the body of a captured payload? | Object storage, separate authorization |
