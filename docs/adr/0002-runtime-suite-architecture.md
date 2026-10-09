# ADR 0002 — Independently deployable runtime suite

**Status:** accepted  
**Date:** 2026-09-15  
**Supersedes:** D-002 for suite topology; D-044 for routing enforcement

## Context

The control plane began as one FastAPI service and one PostgreSQL database. That remains
appropriate for assurance workflows, but it cannot simultaneously be:

- a low-latency streaming model gateway;
- a high-volume OTLP ingest and analytical trace store;
- independently licensable Router, Observe, Prompt and Evaluate products; and
- independently placeable in SaaS, BYOC and air-gapped networks.

LiteLLM's adapter and routing hot path, and Langfuse's split web/worker/ClickHouse design,
show that these workloads have different failure, scale and persistence boundaries.

## Decision

The first suite release has four commercial modules:

1. **Router** — a stateless Go gateway with an OpenAI-compatible surface and certified
   OpenAI/OpenAI-compatible, Azure OpenAI, Anthropic, Bedrock and Gemini/Vertex adapters.
2. **Observe** — edge collection, durable OTLP ingest, normalization, ClickHouse query,
   sessions, scores, graphs and live monitoring.
3. **Prompt** — immutable prompt/system/context artifacts, runtime retrieval and playground.
4. **Evaluate** — datasets, experiments, evaluators, automations and annotation queues.

Each module has its own image, API/health contract, data owner and license claim. One web
console discovers entitlements and routes requests to enabled modules through a same-origin
edge proxy.

The existing FastAPI application remains the assurance and shared control plane. Services
communicate through versioned contracts and do not import each other's code or query each
other's tables.

The economical initial deployment uses:

- one PostgreSQL cluster with service-owned schemas;
- one ClickHouse node for hot trace analytics;
- one Redis deployment for ephemeral queues, cache, rate limits and live tail;
- one object store for durable raw ingest and encrypted payloads.

Redis is never the sole durable copy. OTLP batches are acknowledged only after object
storage and an ingest manifest are durable. Kafka is not introduced until measured load
or recovery behavior requires it.

The gateway never calls the control plane per model request. It atomically activates
validated, signed configuration snapshots and continues with the last-known-good snapshot
during a control-plane outage.

## Data handling

Evidence remains content-free. Prompts, model messages, retrieval documents and tool
arguments/results are encrypted in a customer-controlled object store. Trace rows contain
only authorized previews, digests, metadata and object references. Payload reads are
tenant-scoped and audited.

## Performance contract

The Router release target is at most 10 ms p95 and 25 ms p99 measured gateway overhead at
1,000 requests per second and 500 concurrent streams against a mock upstream with warm
caches, routing and global limits enabled. Cold-cache, degraded dependency, large-prompt
and real-provider measurements are reported separately.

Observe is certified for 10 million spans per day and 30 days of hot trace metadata.

## Licensing behavior

A signed license declares modules and limits. Services enforce their own entitlement;
the UI manifest is convenience, not authorization. Expiry preserves evidence reads and
existing inference during a grace period, but blocks new configuration and credential
creation. Ingest remains available so a contract dispute cannot create an audit gap.

## Consequences

- Operations and deployment are more complex than the original monolith.
- Service contracts, version skew, backup/restore and degraded dependencies require tests.
- Router and Observe can scale and fail independently of assurance workflows.
- Customers can purchase and place only the modules in their agreement.
- The original domain-layer rules continue inside `services/api`; cross-service boundaries
  are API/event boundaries instead.
