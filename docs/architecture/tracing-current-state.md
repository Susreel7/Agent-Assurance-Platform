# Tracing current state

**Audit date:** 2026-09-16  
**Scope:** all first-party application code, contracts, migrations, tests, deployment
configuration and SDK source under this repository. Generated bundles, dependency
directories and caches were excluded.

This is a repository audit, not a target design. The target design is in
[`agent-observability-plan.md`](agent-observability-plan.md).

## Executive finding

The repository already contains a substantial observability foundation, but it contains
**two independent execution-recording systems**:

1. The control-plane `operations` domain stores agent runs and bounded run steps in the
   main PostgreSQL database.
2. The Observe product accepts OTLP traces, durably stages envelopes and payloads,
   normalizes spans into ClickHouse, and exposes trace/session queries through a
   control-plane BFF.

These systems overlap but are not one product model. The first drives the useful
waterfall, observed LangGraph topology, governance reconciliation and tool/MCP rollups.
The second drives OTLP traces, sessions, payload references, metrics and live tail.
The SDK emits only to the second path. There is no durable, enforced relationship among
an operations `run_id`, an OTLP `trace_id`, and an Observe `session_id`.

The current Observe screen is therefore a thin span explorer, not an answer to:
“What did this agent actually do?”

## Repository architecture

The current suite architecture supersedes the old monolith description still present in
parts of `README.md` and older project-state decisions.

```text
Agent application
  ├─ aap-trace Python/TypeScript SDK ─ OTLP ─┐
  ├─ standard OTel instrumentation ──────────┤
  └─ operations run reporter, if custom ─────┼──────────────┐
                                             v              v
Edge collector (optional)              Observe ingest   API operations
  ├─ capture transform                    │              PostgreSQL
  ├─ durable spool                        ├─ object store
  └─ retry/quarantine                     └─ manifest PostgreSQL
                                             │
                                             v
                                        Observe worker
                                             │
                           ┌─────────────────┼─────────────────┐
                           v                 v                 v
                      ClickHouse       payload objects   live stream rows
                           │                                   │
                           └──────── Observe query ────────────┘
                                        │ internal token
                                        v
                              control-plane Observe BFF
                                        │
                                        v
                                   React console
```

### Independently deployed services

- `services/api`: FastAPI assurance/control plane and BFFs.
- `services/gateway`: Go OpenAI-compatible model router.
- `services/collector`: optional Python OTLP edge collector.
- `services/observe`: Observe ingest, worker and query entrypoints.
- `services/prompt`: prompt/rule/skill/context workspace.
- `services/evaluate`: datasets, evaluators, scores and annotation.
- `services/web`: one React/Vite console.

This topology is defined by `docker-compose.yml` and ADR
`docs/adr/0002-runtime-suite-architecture.md`. Service boundaries use versioned HTTP and
OTLP. Services do not import one another or read one another’s tables.

## Frontend

### Stack and shell

- React 18, TypeScript, Vite 5 and React Router 6.
- TanStack Query for server state.
- Tailwind and repository-owned CSS tokens/components; no UI component framework.
- Cytoscape is the only graph library.
- The console always calls live APIs. Generated OpenAPI types are exposed through
  `Wire<...>` aliases.
- Runtime products are entitlement gated through `GET /v1/modules`.

Primary files:

- `services/web/src/main.tsx`
- `services/web/src/App.tsx`
- `services/web/src/components/Shell.tsx`
- `services/web/src/components/Rail.tsx`
- `services/web/src/features/suite/ModuleGate.tsx`
- `services/web/src/api/suiteQueries.ts`
- `services/web/src/api/schema.d.ts`

### Existing operational and Observe screens

The console has two separate navigation surfaces for execution data:

- `/runs` and `/runs/:runId` use the control-plane operations domain.
- `/observe`, `/observe/traces/:traceId`, `/observe/sessions`,
  `/observe/sessions/:sessionId` and `/observe/live` use Observe.

`RunDetailScreen.tsx` has a useful CSS waterfall. It shows nesting, duration, self time,
model, tokens, cost and error classification. It is backed by `run_steps`.

`ObserveTraceDetailScreen.tsx` displays:

- a three-column span table;
- a second panel containing an indented text list of parent links.

It does not display the timestamps, latency composition, token/cost fields, payloads or
events already present in parts of the backend. It has no selectable graph node,
inspector, timeline or real-time lifecycle.

### Current graph implementations

There are three distinct graph concepts:

1. `features/graph/GraphCanvas.tsx`: declared/observed estate dependencies and blast
   radius.
2. `features/operations/ObservedGraphCanvas.tsx`: aggregated LangGraph-like topology
   derived from operations `node` steps across many runs.
3. `features/observe/ObserveTraceDetailScreen.tsx`: one trace’s parent links rendered as
   text.

Cytoscape already supplies zoom, pan and layouts and should be reused. The existing
canvases only implement pointer selection (or no selection); they do not provide graph
keyboard navigation, subtree collapse, path highlighting or execution-follow mode.

### Frontend gaps

- Observe defaults to traces rather than the session/execution workspace.
- Project selection is in `localStorage`, not the URL. Shared trace links depend on the
  recipient’s previously selected project.
- Observe search facets and payload-reference endpoints are not consumed.
- Trace and session lists have only minimal filtering.
- Session lists do not paginate in the screen even though the hook accepts an offset.
- Live tail renders raw JSON lines and does not reconnect with a durable cursor.
- There is no right-hand contextual inspector.
- There is no expandable, searchable, permission-aware prompt/output viewer.
- There are no frontend unit or end-to-end tests for Observe.
- `DataTable` sortable headers are not implemented as keyboard-operable buttons.

## Control-plane backend

`services/api` is a FastAPI service using SQLAlchemy 2, Pydantic v2 and PostgreSQL.
Domains are explicitly registered in `app/api/v1/router.py`. The relevant domains are:

- `registry`: organizations, agents and append-only agent versions;
- `workload_identity`: projects and revocable project/agent-scoped credentials;
- `operations`: agent runs, run steps and tool/MCP rollups;
- `observe`: authenticated human-facing BFF over Observe query;
- `composition`: declared-versus-observed tools, skills and subagents;
- `evidence`: immutable, bounded assurance evidence, never execution content;
- `modules`: licensed product capabilities.

### Existing conceptual entities

| Requested concept | Current repository representation | Current limitation |
|---|---|---|
| Organization | `organizations` in control-plane PostgreSQL | Complete tenant root |
| Project | `projects` in `workload_identity` | Not directly bound to a set of agents |
| Environment | lifecycle enum/string on several rows | No first-class project environment entity |
| User | JWT `Principal`; SDK `user_id` attribute | No user directory table or invocation identity model |
| Agent | `agents` | Organization scoped, not project scoped |
| Agent Version | append-only `agent_versions` | No enforced execution link from Observe |
| Session | Observe `session_metadata` and span `session_id` | Thin rollup; no actor/source/status model |
| Trace | OTLP trace ID and Observe `trace_metadata` | Not explicitly an Agent Execution |
| Span | Observe ClickHouse `spans` | Generic normalized kind, limited typed fields |
| Event | OTLP events are parsed; normalized live events are stored | Source span events are not queryable as first-class events |
| Node Execution | operations `run_steps(kind=node)` | Separate from Observe |
| LLM Generation | operations `llm` step or Observe `inference` span | Split model and no full typed inspector contract |
| Tool Execution | operations step/rollup or Observe `tool` span | Split model |
| SDK Execution | no explicit kind | Missing |
| Agent Transition | inferred from consecutive operations nodes | No explicit transition edge |
| State Transition | not modeled | Missing |
| Error | outcome/error classification | Not a first-class observation/event |
| Retry | operation attempt/retry count | No explicit retry link/reason observation |
| Evaluation | Evaluate scores linked by trace identifiers | Not part of execution graph |
| Artifact | Prompt artifacts and payload objects | No unified execution artifact reference |

### Operations path

`services/api/app/db/models/operations.py` defines:

- `AgentRun`: one invocation with version, environment, totals, outcome and optional
  `trace_id`;
- `RunStep`: one bounded node/LLM/tool/MCP/retrieval/guardrail/handoff/subagent step;
- `ToolUsageDaily`: content-free daily aggregation.

`POST /v1/operations/runs` accepts a workload credential with `ingest:runs`. Read routes
provide runs, run detail, cost, tools, MCP servers, runtime frameworks and an observed
agent graph.

Strengths:

- bounded content-free schema;
- replay-safe run and step updates;
- append-only terminal records;
- self-time and critical-path calculations;
- composition/governance consumers already depend on these records.

Limitations:

- the tracing SDK does not report this contract;
- the default local runtime credential does not include `ingest:runs`;
- parent sequence expresses a tree but not conditional graph edges;
- explicit SDK/state/evaluation/error/retry observations do not exist;
- the optional text `trace_id` is the only link to Observe.

## Observe backend

### Ingest

Observe accepts standard OTLP/HTTP traces at `POST /v1/traces`:

- protobuf or JSON;
- optional gzip;
- W3C trace context;
- 16 MiB compressed / 64 MiB uncompressed limits;
- 10,000 spans per request;
- partial-success responses;
- workload-token introspection with organization/project/optional-agent binding.

The edge collector is optional. It:

- accepts the same OTLP trace format;
- applies an allowlisted content transform;
- atomically spools before acknowledgement;
- retries forwarding with backoff;
- quarantines poison envelopes.

The ingest service writes the original envelope to object storage and commits a
tenant-scoped manifest before acknowledging. The manifest digest makes envelope replay
safe.

### Worker and durability

The worker:

1. claims manifests using `FOR UPDATE SKIP LOCKED`;
2. loads and decompresses the durable envelope;
3. parses OTLP spans and events;
4. normalizes each span;
5. enforces span identity and terminal-upgrade rules;
6. stores captured payload fields separately;
7. writes normalized spans and trace index rows to ClickHouse;
8. recomputes trace metadata;
9. emits a Postgres `stream_events` row;
10. marks the manifest complete only after analytics writes succeed.

Redis is only a wake signal. The worker currently polls PostgreSQL; the published Redis
wake is not consumed.

### Storage

Observe PostgreSQL owns:

- `ingest_manifests`;
- `payload_refs`;
- `quarantine_records`;
- `span_idempotency`;
- `trace_metadata`;
- `stream_events`;
- `session_metadata`.

ClickHouse owns:

- `observe.spans`;
- `observe.trace_index`.

Large envelopes and content payloads use the configured object store. Implementations
exist for local storage and cloud backends.

Current ClickHouse span columns include tenant identity, trace hierarchy, session,
service, agent, normalized kind, status, model/tool, timestamps, duration, input/output
tokens, cost, tags and bounded search text. They do not include most requested
agent-execution, graph, actor, SDK, MCP, repository, deployment or typed model-call
fields.

### Current normalized kinds

`workflow`, `agent`, `plan`, `inference`, `tool`, `mcp_tool`, `retrieval`, `embedding`,
`memory`, `guardrail`, `handoff`, `http`, `unknown`.

This does not satisfy the requested explicit observation taxonomy. In particular:

- LangGraph nodes often map to `workflow`, not `node`;
- `workflow` and `handoff` operation names emitted by the SDK can map to `unknown`;
- there is no `sdk`, `database`, `state_transition`, `event`, `evaluation`, `error` or
  `retry` type;
- parsed OTLP events are not persisted as queryable source events.

### Query and BFF APIs

Observe query currently exposes:

- `GET /v1/traces`
- `GET /v1/traces/{trace_id}`
- `GET /v1/traces/{trace_id}/graph`
- `GET /v1/traces/{trace_id}/payload-refs`
- `GET /v1/sessions`
- `GET /v1/sessions/{session_id}`
- `GET /v1/sessions/{session_id}/traces`
- `GET /v1/search/facets`
- `GET /v1/metrics/aggregate`
- `GET /v1/metrics/timeseries`
- `GET /v1/freshness`
- `GET /v1/live-tail`

The control-plane BFF exposes project-scoped equivalents under
`/v1/observe/projects/{project_id}` and enforces human authentication and Observe read
entitlement.

Verified contract gaps:

- BFF freshness field names do not match the query service response.
- The BFF does not proxy metrics time series.
- payload references contain signed URLs, but there is no matching authorized payload
  download/decrypt endpoint.
- trace detail omits start/end time, token and cost fields that ClickHouse already holds.
- trace graph returns nodes with parent IDs but no explicit typed edges.

### Real time

`/v1/live-tail` uses SSE over PostgreSQL `stream_events`. The query service polls and
sends heartbeats. Events are created after a completed span envelope has been normalized.

This cannot show a long-running node changing from queued to running because standard
OTLP span processors export a span after it ends. The SDK batch delay and worker poll add
further latency. Live execution therefore needs lifecycle events in addition to terminal
spans.

## SDK and integration layer

### Python

The `aap-trace` package provides context managers for trace, run, workflow, agent,
generation, tool, retrieval and handoff spans, a generic decorator, W3C propagation,
batch OTLP export, capture helpers, streaming metrics and score submission.

Actual integration status:

- OpenAI: client wrapper; non-streaming works, streaming span lifetime is incorrect.
- Anthropic: client wrapper with the same streaming lifetime problem.
- LangChain: callback handler for LLM and tool calls; content policy is inconsistently
  applied.
- LangGraph: manual node/tool wrappers and a checkpoint event helper only.
- CrewAI: manual wrappers only.
- LlamaIndex: placeholder, not a complete integration.
- ASGI: context extraction only; no HTTP server span.
- MCP: absent.
- OpenAI Agents SDK: absent.
- A2A: absent.
- Java: absent.

### TypeScript

The TypeScript package supplies OTLP export, W3C/async context, a smaller set of span
helpers, streaming wrappers and scores.

Its integration modules are not exported through the package entrypoint. The LangChain
callback ends spans immediately, and OpenAI/Anthropic streaming has the same lifetime
problem as Python.

### Performance behavior

Core export uses OpenTelemetry batch span processors and does not synchronously wait for
Observe. Collector spooling and retries tolerate backend outages. This is a sound base.

Missing performance controls include:

- explicit bounded drop behavior/metrics when SDK queues fill;
- live lifecycle event batching;
- sampling configuration exposed as a product policy;
- tail sampling;
- integration overhead/load tests;
- automatic instrumentation bootstrap.

## Privacy and security

### Existing controls

- workload credentials are scoped and revocable;
- tenant/project identity is stamped from credential introspection;
- queries include organization and project filters;
- module entitlements gate human access;
- full payloads are separated from ClickHouse/evidence;
- project capture mode, retention and encryption key reference exist;
- object keys are tenant scoped;
- evidence cannot hold prompts, completions or tool arguments.

### Gaps

- SDK redaction only recognizes simple email and North American phone patterns.
- API keys, passwords, authorization headers, cookies and private keys are not
  comprehensively detected.
- `full` capture can place raw content on span attributes before the edge transform.
- collector capture is environment configured while Observe capture is project
  configured; the stricter edge choice wins silently.
- query service trusts one internal token for all tenants.
- raw payload access has no completed authorization/audit path.
- control-plane RBAC is still an open question.
- the deployed control-plane database role bypasses PostgreSQL RLS, recorded as Q-015.

No design should claim production-grade sensitive-content access until these are closed.

## Logging and platform observability

Services use Python standard-library logging, generally with module loggers. The
collector exposes Prometheus metrics. Observe ingest, worker and query mainly expose
health/readiness and logs; they do not expose a complete internal metrics set for
manifest lag, ClickHouse write latency, SSE clients, payload failures or dropped
telemetry.

Platform self-telemetry is separate from customer execution telemetry and is disabled in
local Compose.

## Docker and environment configuration

`docker-compose.yml` runs PostgreSQL, Redis, ClickHouse, migrations, seed, API, API
worker, three Observe processes, Prompt, two Evaluate processes, Router, collector and
web.

The current script folder contains Windows `aap-*.cmd` wrappers. It does not contain the
requested `dev-up`, `dev-down`, `dev-rebuild`, `dev-reset`, `logs` and `status` shell and
PowerShell pairs.

Other deployment findings:

- local Compose uses source mounts and reload servers;
- the gateway can be healthy without a signed model-routing snapshot;
- the collector needs a bootstrapped runtime workload bearer;
- `.env.example` documents core platform settings but not the complete Observe capture,
  query and SDK policy surface;
- `README.md` still describes the pre-suite “one service, one database” architecture;
- the Makefile bootstrap still requires `openssl`, despite a Python bootstrap utility
  existing for Windows.

## Current tests

Strong coverage exists for:

- operations run/step behavior against PostgreSQL;
- workload credential parsing, scope checks and integration;
- OTLP parsing, limits, capture helpers and collector spool/forward behavior;
- core SDK nesting, capture, propagation and streaming helpers;
- Go Router race tests;
- OpenAPI path/type build checks.

Missing or shallow coverage:

- real Observe worker + PostgreSQL + ClickHouse + query end to end;
- Observe BFF integration and cross-tenant tests;
- persisted source OTLP events;
- live lifecycle and SSE reconnect;
- LangGraph automatic instrumentation;
- all vendor integrations;
- MCP propagation and de-duplication;
- A2A links;
- large payload retrieval/expiry/legal hold;
- trace graph/timeline UI;
- frontend keyboard and end-to-end flows.

## Constraints that the redesign must preserve

1. Evidence remains content free and bounded.
2. Every service owns its schema and migrations.
3. The API BFF, not the browser, owns cross-service credentials.
4. PostgreSQL is metadata/durability; ClickHouse is hot analytical telemetry; object
   storage is large content; Redis is never the durable copy.
5. The same images must support SaaS, BYOC and air-gapped deployments.
6. No new dependency may be added without approval.
7. Applied migrations are immutable.
8. API changes regenerate OpenAPI and the typed client.
9. Human paths enforce tenant plus module capability; workload paths enforce tenant,
   project, module, scope and optional agent binding.
10. Unsupported telemetry is retained as `unknown`; it is never guessed or discarded.

## Audit conclusion

The repository does not need a third tracing stack. It needs one canonical
**Agent Execution** model over the existing Observe pipeline, an explicit compatibility
projection into operations/governance, and a session-centric execution workspace in the
console.

The implementation plan must first repair current contract holes, then evolve storage
and SDK semantics additively. Replacing OTLP, ClickHouse, the durable manifest queue or
Cytoscape would discard working infrastructure without addressing the actual problem.
