# Agent Execution Observability Architecture

The primary observable object is an **agent execution**, identified by
`aap.execution.id`. LLM generations, tools, SDK operations, retrievals, network calls,
state changes, evaluations, retries, and errors are typed children of that execution.

## Data flow

```text
Agent / framework integration
  -> aap-trace SDK and OpenTelemetry
  -> OTLP/HTTP collector (sampling, buffering, outage tolerance)
  -> Observe ingest (workload identity, limits, first-write sanitization)
  -> encrypted tenant object store + durable manifest
  -> Observe worker
       -> ClickHouse spans/events/edges
       -> PostgreSQL execution/session indexes and links
       -> content-free Operations projection
  -> Observe query service
  -> authenticated control-plane BFF
  -> execution/session console
```

PostgreSQL owns execution, session, actor, payload-reference, policy, and outbox
metadata. ClickHouse owns high-volume span/event analytics. Large content is encrypted
in object storage and represented by references. Redis is a wake-up channel, never the
source of truth.

## Execution understanding

An execution detail response combines:

- the execution aggregate and invocation context;
- a typed parent/child observation tree;
- state-transition and event records;
- timeline and critical-path analysis;
- incoming/outgoing replay, MCP, parent, and A2A relationships;
- lazy, audited payload references.

The console renders this as graph, accessible tree, timeline, inspector, and raw-event
surfaces. Stable `?span=` and `?event=` deep links preserve selection.

## Reliability and trust boundaries

- SDK export is asynchronous and fail-open for the observed application.
- The collector applies deterministic head sampling and policy-driven tail preservation.
- Ingest authenticates scoped, revocable workload credentials.
- Sanitization occurs before the first durable envelope write.
- Tenant IDs are derived from verified identity, not trusted from the browser.
- PostgreSQL row-level security fails closed without transaction-local tenant context.
- Full payload access and legal-hold changes require explicit OIDC permissions and are
  audited.

The frozen decisions and phased implementation plan are in
`docs/architecture/agent-observability-plan.md`.
