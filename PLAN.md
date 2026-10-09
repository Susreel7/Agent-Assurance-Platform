# Agent Execution Observability delivery plan

**Status:** Phases 1–12 implemented; Phase 13 final certification in progress.  
**Detailed architecture:** [`docs/architecture/agent-observability-plan.md`](docs/architecture/agent-observability-plan.md)  
**Repository audit:** [`docs/architecture/tracing-current-state.md`](docs/architecture/tracing-current-state.md)

## Goal

Redesign Observe so one execution immediately explains what an agent did: invocation
context, version, graph path, nodes, generations, tools, SDKs, state, retries, errors,
cost, latency, content references and evidence.

Add a first-class User Activity lens so authorized users can see, per observed user:
agent invocations, Claude/other model calls, Cursor/other SDK operations, tool calls and
each MCP server/tool call, with sessions, latency, tokens, cost, retries and errors.

## Repository-backed direction

The repository has two tracing paths today. The implementation will not create a third.

- Observe/OTLP becomes the canonical detailed Agent Execution plane.
- The existing PostgreSQL operations model remains a bounded, content-free governance
  projection produced reliably from Observe.
- The common execution root supports agent executions and direct instrumented user
  activity; every observation preserves initiating user and effective actor when known.
- `execution_id` becomes the product root while preserving OTel `trace_id` and W3C
  propagation for distributed and A2A workflows.
- PostgreSQL owns metadata/durability, ClickHouse owns hot observations/events/edges,
  object storage owns encrypted content, and Redis remains non-durable.
- The current React/TanStack Query/Cytoscape stack is reused.

## Delivery order

- [x] Phase 1 — audit, architecture and target data model
- [x] Phase 2 — canonical ingest, execution/event/edge storage and content boundary
- [x] Phase 3 — first-class LangGraph Agent/Node/State instrumentation
- [x] Phase 4 — LLM, Tool, SDK, HTTP/database and generic instrumentation
- [x] Phase 5 — sessions, observed users, actor correlation and operations projection
- [x] Phase 6 — session-centric execution workspace and live execution graph
- [x] Phase 7 — type-aware inspector and protected large-content viewer
- [x] Phase 8 — trace/session timeline and critical-path analysis
- [x] Phase 9 — typed SSE lifecycle updates and reconnect
- [x] Phase 10 — execution/user metrics, analytics and sampling
- [x] Phase 11 — MCP and A2A propagation/linking
- [x] Phase 12 — enterprise privacy, RBAC, retention and isolation hardening
- [ ] Phase 13 — Docker scripts, deterministic demo and final certification

## Rules for every phase

1. One phase is in progress at a time.
2. Use additive, hand-written migrations; never edit applied revisions.
3. Preserve existing OTLP and operations APIs through compatibility aliases/projections.
4. Do not add a dependency without explicit approval.
5. Never persist secrets or reconstruct hidden chain-of-thought.
6. Large content is encrypted object data and lazy loaded, never part of default trace
   responses.
7. Run service tests, contract checks, Docker and the FOSS Remediation demo before
   completing a phase.
8. Update the mandatory project-state sections after each phase.

## Implemented storage foundation

Phase 2 is the first implementation slice:

1. repair the Observe freshness and payload-access contract gaps;
2. freeze the Agent Execution semantic attribute and API contracts;
3. add Observe PostgreSQL migration 003;
4. add versioned ClickHouse migrations for executions, events and edges;
5. add observed-user identity/attribution fields and per-user query dimensions;
6. add OTLP lifecycle/log ingest;
7. split/redact/encrypt content before the first durable write;
8. add a durable content-free operations projection outbox;
9. verify with real PostgreSQL, ClickHouse, object storage and the current console.

This storage foundation now feeds the execution workspace, live stream, protected
inspector, timeline, analytics, sampling, MCP/A2A links, and retention controls delivered
in Phases 3–12.

## Approved direction

Confirmed on 2026-09-16:

- Observe is canonical; Operations is a durable content-free projection.
- Keep the existing `aap-trace` / `aap_trace` SDK identity.
- Playwright is approved as a web development dependency for browser certification.

No additional dependency may be introduced without separate approval.

User-level counts are valid only for instrumented/controlled paths. The product must
show coverage as complete/partial/unknown and must not imply it can observe arbitrary
activity inside third-party desktop/SaaS clients that expose no telemetry.

## Required final documentation

The following are phase deliverables, not placeholders created before their
implementations exist:

- `docs/tracing/architecture.md`
- `docs/tracing/data-model.md`
- `docs/tracing/instrumentation.md`
- `docs/tracing/langgraph.md`
- `docs/tracing/mcp.md`
- `docs/tracing/sdk.md`
- `docs/tracing/privacy.md`
- `docs/tracing/local-development.md`
- `docs/docker-development.md`

## Completion rule

Do not claim completion until the full checklist in
`docs/architecture/agent-observability-plan.md` passes against a clean Docker rebuild and
a realistic FOSS Remediation Agent execution.
