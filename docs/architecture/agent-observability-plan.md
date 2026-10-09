# Agent Execution Observability architecture and implementation plan

**Status:** Phases 1–12 implemented; Phase 13 final certification in progress  
**Created:** 2026-09-16  
**Companion audit:** [`tracing-current-state.md`](tracing-current-state.md)

## Product objective

The primary object is an **Agent Execution**, not an LLM request and not a bag of logs.
The second first-class lens is **User Activity**: who initiated or performed operations,
including direct SDK/model/tool activity that is not nested under an agent.

Opening one execution must answer:

1. who invoked it and from where;
2. which project, environment, agent and immutable agent version ran;
3. which graph nodes executed, in what order and in which parallel branches;
4. which transitions, loops, retries, checkpoints and approvals occurred;
5. which models, tools, SDKs, MCP servers, databases and external APIs were called;
6. what inputs and outputs were available under the viewer’s content policy;
7. how long and how much each operation cost;
8. what failed, what was retried and what ultimately determined the result;
9. which execution evidence and artifacts support the record.
10. how many agent, model, SDK, tool and per-MCP-tool calls each user made.

The implementation optimizes for **execution understanding**, not event volume.

## Architectural decisions

### 1. Observe becomes the canonical execution plane

The existing OTLP/Observe path becomes the canonical source of detailed execution truth.
It already has the correct high-volume storage split, durable ingest, object storage,
tenant-scoped machine identity and an analytical query plane.

The control-plane `operations` tables remain the content-free governance and estate
projection used by assurance, composition, cost and tool/MCP rollups. SDKs will not
dual-write independently. Observe will produce the operations projection through a
durable outbox and an idempotent internal API.

This removes conflicting measurements while preserving existing governance consumers.

### 2. Execution, Agent Execution and OTel Trace are correlated but not conflated

An OpenTelemetry distributed trace can contain multiple agent invocations, especially
for A2A and service-to-service workflows. Forcing “one OTel trace equals one agent” would
break normal W3C propagation.

The storage/query root is `Execution`, with `execution_type=agent|user_activity|workflow`.
`AgentExecution` is the primary specialization. A direct instrumented Cursor SDK, Claude
API or tool workflow without an agent root becomes a `user_activity` execution rather
than disappearing or being mislabeled as an agent.

The product therefore introduces:

- `execution_id`: stable primary product identity for one agent invocation;
- `trace_id`: OpenTelemetry distributed trace identity;
- `root_span_id`: root `AGENT` span for this execution;
- `parent_execution_id`: optional caller execution;
- `parent_trace_id`: optional cross-trace parent when a trust boundary starts a new
  trace.
- `initiating_user_id`: user on whose behalf the execution began;
- `effective_actor_id` and `effective_actor_type`: user, agent or service performing a
  specific operation.

For the common case, one trace contains one root execution and the distinction is
invisible. The UI always opens an Agent Execution workspace, even when raw telemetry
contains a wider distributed trace.

### 3. One typed observation model, stored according to behavior

`Observation` is the query/API projection shared by interval spans and point events. It
is not a new generic database blob.

- interval work is stored in ClickHouse spans;
- point lifecycle/events are stored in ClickHouse events;
- branch/retry/A2A relationships are stored as explicit edges;
- execution/session identity and ingest state are stored in Observe PostgreSQL;
- large or sensitive content is stored as encrypted object payloads;
- assurance evidence stores only bounded digests, classifications and decisions.

### 4. OTLP remains the preferred transport

The SDK builds on OpenTelemetry and exports OTLP. Proprietary APIs are compatibility
adapters, not the primary path.

- `POST /v1/traces`: existing OTLP trace export;
- `POST /v1/logs`: OTLP log/lifecycle export to support live starts and events;
- `POST /v1/spans` and `POST /v1/events`: optional **batch** JSON compatibility
  endpoints, never one network request per operation.

### 5. Live state requires lifecycle events

Terminal spans alone cannot show `QUEUED → RUNNING → SUCCESS`. OpenTelemetry span
export normally happens when the span ends.

The SDK will therefore emit small, content-free lifecycle events through OTLP logs:

- `execution.started`;
- `node.queued`;
- `observation.started`;
- `observation.updated`;
- `observation.completed`;
- `observation.failed`;
- `execution.completed`.

Terminal spans remain authoritative for final timing and attributes. A reducer reconciles
out-of-order lifecycle events and terminal spans.

### 6. Content and metadata are separate at the first durable boundary

The current direct-ingest path can durably store a raw OTLP envelope before worker
capture. That is not sufficient for the stated security requirement.

Before any new execution payload is durably stored:

1. parse the envelope;
2. identify content fields;
3. always remove secrets and credentials;
4. apply project PII/content policy;
5. write permitted full content as encrypted objects;
6. replace content attributes with typed payload references, counts and hashes;
7. durably store only the sanitized telemetry envelope.

The edge collector performs the same policy earlier when used. Observe ingest is the
defense-in-depth boundary for direct SDK traffic.

### 7. Reuse Cytoscape and the existing console stack

The repository already ships Cytoscape, TanStack Query, React Router and a CSS waterfall.
The redesign reuses them. No second graph library or UI kit is justified.

Any new dependency, including browser-test tooling, requires explicit approval under
`AGENTS.md`.

## Target topology

```text
Application / agent runtime
  │
  ├─ NexaGuard Agent SDK
  │    ├─ manual typed APIs/decorators
  │    ├─ framework integrations
  │    ├─ W3C trace + baggage propagation
  │    ├─ asynchronous traces
  │    └─ low-latency lifecycle logs
  │
  └─ standard OpenTelemetry instrumentation
            │
            v
Optional edge collector
  ├─ tenant/project policy cache
  ├─ mandatory secret scrubbing
  ├─ sampling
  ├─ bounded local spool
  └─ retry and quarantine
            │ OTLP traces + logs
            v
Observe ingest
  ├─ workload auth and agent binding
  ├─ limits and idempotency
  ├─ content split/encryption/redaction
  ├─ durable sanitized envelope + manifest
  └─ fast acknowledgement
            │
            v
Observe worker
  ├─ canonical normalization
  ├─ execution/session reducer
  ├─ typed spans, events and graph edges
  ├─ trace integrity and critical path
  ├─ stream event/outbox
  └─ content-free operations projection
            │
      ┌─────┼───────────────┬────────────────┐
      v     v               v                v
Observe PG  ClickHouse      Object store     Operations API
metadata    hot analytics   encrypted data   governance projection
      └─────┬───────────────┘
            v
Observe query
            │ internal service identity
            v
Control-plane Observe BFF
  ├─ human auth and RBAC
  ├─ module entitlement
  ├─ project scope
  ├─ content-access audit
  └─ bounded typed responses
            │ REST + SSE
            v
Agent Execution workspace
```

No Kafka or new durable broker is introduced. PostgreSQL manifests/outboxes remain the
durability mechanism, and Redis remains optional wake/cache state.

## Target conceptual model

### Control-plane identity and catalog

| Entity | Owner | Important fields |
|---|---|---|
| Organization | control plane | id, name, tenancy, policy |
| Project | control plane `workload_identity` | id, org, name, capture/retention policy |
| Project Environment | control plane | id, project, name, type, region, runtime policy |
| Agent | registry | id, org, URN, display name, lifecycle |
| Agent Version | registry | immutable id, descriptor digest, semver, commit/source |
| Project Agent Binding | control plane | project, environment, agent, deployed version |
| Console User | OIDC principal initially | issuer, subject, org binding, roles/scopes |
| Observed User | Observe | tenant/project user key, identity bindings, optional display/team data |

`project_environments` and `project_agent_bindings` are additive control-plane concepts.
They remove the current ambiguity between organization-scoped agents and project-scoped
telemetry.

### Observe metadata

| Entity | Purpose |
|---|---|
| Invocation Actor | privacy-scoped user/service identity snapshot used for analytics |
| Session | user/workflow grouping across executions |
| User Activity Execution | direct instrumented user-to-model/SDK/tool work |
| Agent Execution | one agent invocation, the product root |
| Trace Link | same-trace or cross-trace A2A/MCP/service relationship |
| Payload Reference | encrypted/lazy content metadata |
| Projection Outbox | durable content-free operations projection |

An observed user is not automatically a provisioned console account. It can be an end
user of an agent, developer using an instrumented SDK, CLI user or authenticated
application user. `user_identity_bindings` can associate OIDC subject, application user
ID and an approved directory identity without using email as the primary key.

An invocation actor can represent an observed user, service, scheduled job, CLI,
webhook, agent, MCP client or A2A caller. Every operation preserves both the initiating
user and effective actor where available. The default user identity is a tenant-keyed
pseudonym. Email/display/team fields are retained only when project policy permits.

### Analytical telemetry

| Entity | Store | Purpose |
|---|---|---|
| Observation Span | ClickHouse | duration-bearing operation |
| Observation Event | ClickHouse | point lifecycle/log/state/checkpoint/error event |
| Execution Edge | ClickHouse | parent, transition, branch, retry, link and A2A edge |
| Execution Index | ClickHouse | filterable trace/execution summary |
| Session Index | ClickHouse | session-level metrics and filters |

### Artifact references

Do not create another prompt/artifact repository. An execution observation references:

- Prompt artifact revision and label from Prompt;
- dataset/evaluator/score from Evaluate;
- repository, branch and commit;
- file/API/data-source identifiers under field policy;
- payload objects for large inputs/outputs.

## Execution schema

An execution summary contains at least:

```text
organization_id
project_id
environment_id
execution_id
execution_type
trace_id
root_span_id
parent_execution_id
parent_trace_id
session_id
agent_id (required for agent executions)
agent_version_id (required when known for agent executions)
agent_name
agent_version
initiating_user_id
effective_actor_id / effective_actor_type
user_session_id
start_time / end_time / duration_ms / queue_time_ms
status
trigger_type
source / application / client / request_id
repository / branch / commit_sha
deployment / region / runtime
framework / framework_version
node_count / generation_count / tool_count / sdk_count
retry_count / error_count
input_tokens / output_tokens / cached_tokens / reasoning_tokens
total_cost_micros
capture_level / content_availability
is_live / is_partial / is_malformed / has_cycle / has_late_data
tags
```

Money remains integer millionths of USD. Provider currency/conversion metadata is
retained when applicable.

Statuses:

`queued`, `running`, `waiting`, `succeeded`, `failed`, `timed_out`, `cancelled`,
`refused`, `partial`, `unknown`.

`waiting` includes human approval and external resume points, with a typed wait reason.

## Explicit observation taxonomy

Storage uses lower-case enum values; UI labels are uppercase/title case.

Minimum types:

- `agent`
- `node`
- `generation`
- `tool`
- `sdk`
- `retrieval`
- `chain`
- `http`
- `database`
- `state_transition`
- `event`
- `evaluation`
- `error`
- `retry`

Additional first-class types required by this product:

- `user_activity`
- `mcp`
- `a2a`
- `checkpoint`
- `human_approval`
- `guardrail`
- `memory`
- `embedding`
- `unknown`

OpenTelemetry `SpanKind` (`internal`, `client`, `server`, `producer`, `consumer`) remains
a separate transport/runtime dimension. It is never used as the product observation
type.

Every observation API object contains:

```text
id
parent_id
execution_id
trace_id
type
name
sequence
start_time
end_time
duration_ms
self_duration_ms
status
attempt
input_ref
output_ref
metadata
bounded_attributes
error_summary
events_count
child_count
links
```

Type-specific fields are typed sub-objects, not an unbounded attributes map.

### Agent and node

- agent/version/project/environment identity;
- graph name/version;
- node key/name/path;
- subgraph identity;
- input/output state references;
- checkpoint/thread IDs;
- transition/branch labels;
- loop iteration and attempt;
- interrupt/approval state.

### LLM generation

- provider, model, model version, endpoint/deployment;
- provider request/response IDs;
- temperature, max tokens and supported model parameters;
- input, output, cached and provider-exposed reasoning tokens;
- time to first token and total latency;
- finish reasons, cache status and cost;
- prompt artifact/version;
- system/developer/user/tool message payload references;
- tool definitions and tool calls;
- provider-exposed reasoning summary only.

The SDK and backend must never infer, reconstruct or label hidden chain-of-thought.

### Tool and MCP

- tool name/type;
- caller agent and parent node;
- arguments/result payload references;
- duration/status;
- server/endpoint;
- declared permissions and observed operation;
- MCP server/client/version, method, resource or prompt;
- de-duplication key when client and server sides are both instrumented.

### SDK

- SDK name/version;
- operation;
- arguments/result references;
- request/response IDs;
- affected repository/file/terminal operation metadata;
- errors and duration.

SDK examples include Cursor SDK operations, repository operations, terminal commands,
filesystem changes and test execution. Secret-bearing command/environment content is
never persisted.

### HTTP and database

- HTTP method, route template, peer service, status and network latency;
- database system, operation and normalized target;
- no URL credentials, authorization headers, cookies, query literals or raw SQL by
  default.

### State, retry, error and evaluation

- state transition: from/to, branch condition, transition reason and state references;
- retry: target observation, attempt, reason, backoff and final disposition;
- error: class/category, safe message, stack payload reference if allowed;
- evaluation: evaluator/version, score, verdict and linked Evaluate record.

## Semantic attribute contract

Continue standard OpenTelemetry GenAI attributes and add an `aap.*` semantic layer,
matching the retained SDK identity:

```text
aap.execution.id
aap.execution.parent_id
aap.observation.type
aap.observation.sequence
aap.project.id
aap.environment.id
aap.agent.version_id
aap.actor.id
aap.actor.type
aap.user.id
aap.user.session_id
aap.user.team
aap.user.activity_source
aap.execution.type
aap.trigger.type
aap.graph.name
aap.graph.version
aap.graph.node.id
aap.graph.node.path
aap.graph.branch
aap.graph.iteration
aap.state.from
aap.state.to
aap.retry.attempt
aap.sdk.name
aap.sdk.version
aap.sdk.operation
aap.mcp.server
aap.mcp.method
aap.a2a.caller_agent_id
aap.a2a.callee_agent_id
aap.content.capture_level
aap.payload.input_ref
aap.payload.output_ref
```

The contract will define cardinality and byte limits for each field. Unsupported source
conventions map to `unknown` while preserving source name and bounded attributes.

## LangGraph first-class integration

The current function wrapper is insufficient. The integration will use LangGraph/
LangChain runtime callback metadata and streaming hooks to capture:

- graph and subgraph invocation;
- node queue/start/end/error;
- stable node ID/path and graph step;
- input/output state payload references;
- branch triggers and destination;
- loops and iteration counters;
- retry policy attempts;
- checkpoints and thread IDs;
- interrupts and resumptions;
- human approval requested/accepted/rejected;
- nested tool and LLM calls under the active node;
- subgraphs under the correct parent execution.

The adapter must support synchronous, asynchronous and streaming graph execution and
must preserve context across thread/task boundaries.

Version-specific adapters are isolated behind one compatibility layer. Integration tests
pin supported LangGraph versions and use a real small graph, not mocked callbacks.

## Auto-instrumentation plan

The public distribution and import remain `aap-trace` / `aap_trace`.

Public APIs:

```python
start_agent()
start_node()
start_generation()
start_tool()
start_sdk_call()
start_retrieval()
record_event()
record_state_transition()
record_error()
record_retry()
end_span()
set_user()
start_user_activity()
```

Decorators/context managers:

```python
@observe_agent("foss-remediation")
@observe_node("analysis")
@observe_tool("cursor_sdk")
@observe_generation(provider="anthropic", model="claude")
```

Framework middleware should set user context automatically from approved authenticated
request claims. Manual `set_user()` is used for CLIs, jobs and unsupported frameworks.
User email is not accepted as the canonical ID and is not exported unless policy permits.

Automatic integrations are delivered incrementally:

1. LangGraph and LangChain;
2. OpenAI and Anthropic, including stream lifetime;
3. OpenAI Agents SDK;
4. CrewAI and LlamaIndex after replacing placeholders;
5. HTTP client/server;
6. supported database clients;
7. MCP client/server;
8. generic SDK wrapper and decorators;
9. Java OpenTelemetry semantic helper after the Python path is certified.

No integration may monkey-patch globally without an uninstall/restore path and duplicate
instrumentation guard.

Configuration retains the existing AAP names:

```text
AAP_OTEL_ENDPOINT
AAP_API_KEY
AAP_PROJECT_ID
AAP_ENVIRONMENT
AAP_CAPTURE_LEVEL
AAP_SAMPLE_RATE
AAP_AUTO_INSTRUMENT
```

## LLM and streaming correctness

Generation spans remain open until a stream is consumed, cancelled or errors. Wrappers
must capture:

- first-byte/time-to-first-token;
- chunk count;
- usage from final chunks;
- cancellation and consumer abandonment;
- finish reason;
- provider request IDs;
- cache and reasoning token counters when exposed.

System/developer/user messages and tool definitions become payload references. The main
trace response contains counts, character/token sizes and short redacted previews only.

## MCP and A2A

### MCP

Client and server instrumentation propagate W3C context on transports that support
headers. For transports without headers, a namespaced metadata field carries the context
only where the protocol permits it.

Both sides may emit spans. De-duplication uses a stable operation/correlation ID:

- keep both spans when they represent client and server latency;
- render them as one expandable call pair;
- never collapse distinct retries;
- use span links when parentage cannot cross transport boundaries.

Capture server, method, tool/resource/prompt identity, latency and safe result metadata.

### A2A

Agent A emits an `a2a` invocation observation. Agent B emits its own `agent` execution.

- same distributed trace: link by parent span and `parent_execution_id`;
- new trace at a boundary: use a span link plus `parent_trace_id`;
- always preserve session and propagated correlation subject to trust policy;
- prevent an untrusted caller from asserting another organization/project.

The graph can cross to the child execution without loading its entire subtree until the
user expands it.

## Session model

A session groups related executions and retries. It contains:

- session ID and optional external conversation ID;
- observed user, initiating actor, source and application;
- project/environment;
- first/last activity;
- status derived from member executions;
- agents and versions involved;
- trace, span and error counts;
- total duration, tokens and cost;
- tags;
- replay lineage.

Session replay never means silently reusing secret or expired payloads. Replay creates a
new execution linked to the source and requires explicit confirmation of prompt/artifact
versions and model route.

## User activity observability

### Attribution model

Every execution and observation can carry:

- `user_id`: stable tenant/project-scoped observed user;
- `user_session_id`: source application session;
- `initiating_user_id`: original human behind an agent/A2A chain;
- `effective_actor_type`: user, agent, service, scheduler or unknown;
- `effective_actor_id`: the actor that performed this operation;
- source application/client, team and environment when policy permits;
- `on_behalf_of` lineage through agent and A2A calls.

User IDs from untrusted browser headers are not accepted directly. A trusted,
workload-authenticated application or verified server middleware asserts runtime user
context. Ingestion binds it to the credential’s organization/project and records the
assertion source.

### What is counted per user

- agent invocations and sessions;
- calls to providers/models such as Claude and OpenAI;
- Cursor SDK and other SDK operations by operation name;
- tool calls, errors, denial and duration;
- MCP calls by server **and by individual MCP tool**;
- retrieval, HTTP and database operations;
- input/output/cached/reasoning tokens when exposed;
- cost, latency, retries, failures and cache hits;
- environments, applications and agents involved.

Aggregates support total, daily/hourly series, p50/p90/p95/p99 latency, success/error
rate and distinct sessions/executions. Every aggregate links back to the authorized
underlying executions.

### Coverage boundary

NexaGuard can observe activity when at least one controlled integration emits it:

- an application using `aap-trace`;
- automatic framework/provider instrumentation;
- requests routed through the NexaGuard gateway;
- an instrumented MCP client or server;
- an instrumented SDK wrapper;
- an approved enterprise HTTP/database instrumentation path.

It cannot observe arbitrary actions inside Cursor, Claude Desktop or another SaaS/
desktop product when that product exposes no telemetry and traffic does not pass through
an instrumented or controlled boundary. The product will show a coverage indicator
(`complete`, `partial`, `unknown`) instead of implying invisible activity was counted.
Screen capture, keystroke logging and covert employee monitoring are out of scope.

### User privacy and access

- pseudonymous tenant-keyed IDs are the default;
- raw external IDs, email, display name and team are separate policy-controlled fields;
- user-level analytics require a dedicated RBAC capability;
- sensitive payload access remains independently controlled;
- all user-detail access and exports are audited;
- retention and deletion can remove identity enrichment while preserving permitted
  aggregate assurance records;
- UI labels the telemetry source and coverage so counts are not presented as universal.

## Storage changes

### Observe PostgreSQL migration 003

Planned additive tables:

- `agent_executions`;
- `observed_users`;
- `user_identity_bindings`;
- `invocation_actors`;
- expanded `session_metadata`;
- `execution_links`;
- `payload_access_audit`;
- `projection_outbox`;
- `content_policy_revisions`.

Existing `trace_metadata` remains readable during migration and is backfilled into
`agent_executions`. Applied migrations `001` and `002` are not edited.

### Control-plane Alembic 0017

Planned:

- `project_environments`;
- `project_agent_bindings`;
- optional current deployed agent version;
- composite tenant-safe keys and RLS;
- indexes supporting agent/project/environment resolution.

This migration is hand-written. It does not place telemetry or content in the control
plane.

### ClickHouse schema migration

Before schema expansion, Observe gains numbered ClickHouse migrations and a migration
ledger. Planned additive structures:

- expanded `spans` typed columns or a compatibility `observations_v2` table;
- `events`;
- `execution_edges`;
- `execution_index`;
- `session_index`.
- `user_activity_daily` materialized aggregation or equivalent measured query path.

The exact choice between expanding `spans` and `observations_v2` is made after a
representative migration benchmark. Query compatibility views keep existing endpoints
working while backfill runs.

Indexes target actual filters: project/time, execution, session, agent/version,
environment, status, observation type, model/provider, tool, SDK, MCP server, error,
latency, cost and tags.

### Object storage

Object storage owns:

- prompt/message content;
- tool/SDK arguments and results;
- state snapshots and diffs;
- error stacks;
- large event bodies;
- exported raw JSON;
- optional replay artifacts.

Each reference records digest, media type, compressed/uncompressed size, encryption key,
policy revision, redaction state, retention deadline, legal hold and availability.

## Privacy and data protection

Canonical capture configuration:

- `OFF`: no content or raw-content hash; only counts and structural metadata;
- `METADATA_ONLY`: sizes/counts and an optional tenant-keyed content digest;
- `FULL_CONTENT`: approved content stored encrypted outside analytical tables.

The existing modes migrate as:

- `none` → `OFF`;
- `digest` → `METADATA_ONLY` with digest enabled;
- `redacted` → `FULL_CONTENT` with mandatory PII redaction;
- `full` → `FULL_CONTENT` with project policy.

Secret/credential detection is mandatory in every mode, including full content. It
recognizes authorization headers, API-key patterns, private keys, passwords, cookies,
connection strings, cloud credentials and configured enterprise patterns.

Defense in depth:

1. SDK removes obvious secrets before export.
2. Edge collector applies estate policy before egress.
3. Observe ingest applies authoritative project policy before durability.
4. Query/BFF applies field masking and access control.
5. Full payload access is audited.

Raw sensitive payload access requires a dedicated capability distinct from Observe read.
Preview is redacted. Download/fullscreen/raw JSON actions honor the same capability.

## Query and API design

### Ingest service

- retain OTLP `POST /v1/traces`;
- add OTLP `POST /v1/logs`;
- add bounded batch compatibility `POST /v1/spans`;
- add bounded batch compatibility `POST /v1/events`;
- return partial success without exposing sensitive parse details;
- enforce credential rate/concurrency limits.

### Observe query service

Add:

- `GET /v1/executions`
- `GET /v1/executions/{execution_id}`
- `GET /v1/executions/{execution_id}/tree`
- `GET /v1/executions/{execution_id}/timeline`
- `GET /v1/executions/{execution_id}/observations`
- `GET /v1/executions/{execution_id}/events`
- `GET /v1/executions/{execution_id}/links`
- `GET /v1/executions/{execution_id}/payloads`
- `GET /v1/payloads/{payload_id}`
- session detail/timeline/metrics/replay lineage;
- agent architecture and execution analytics;
- `GET /v1/users`;
- `GET /v1/users/{user_id}`;
- `GET /v1/users/{user_id}/executions`;
- `GET /v1/users/{user_id}/models`;
- `GET /v1/users/{user_id}/tools`;
- `GET /v1/users/{user_id}/mcp-tools`;
- `GET /v1/users/{user_id}/sdk-operations`;
- typed live stream filters.

Existing trace routes remain compatibility aliases.

List APIs use cursor pagination for high-cardinality time series. Offset pagination
remains temporarily for existing clients.

### Control-plane BFF

Human APIs remain project scoped:

```text
/v1/observe/projects/{project_id}/executions
/v1/observe/projects/{project_id}/traces/{trace_id}
/v1/observe/projects/{project_id}/sessions
/v1/observe/projects/{project_id}/metrics
```

The BFF validates organization/project/module/capability and injects internal service
identity. It never returns internal tokens or raw object-store keys.

### Stable console URLs

Canonical shareable URLs include project scope:

```text
/observe/projects/:projectId/sessions/:sessionId
/observe/projects/:projectId/traces/:executionId
/observe/projects/:projectId/traces/:executionId?span=:observationId
/observe/projects/:projectId/users/:userId
/agents/:agentId
/agents/:agentId/runs
/tools/:toolId
```

The requested short `/sessions/:id` and `/traces/:id` routes can be convenience redirects,
but cannot be the only canonical URLs: trace IDs are tenant/project scoped and the
current localStorage project selection makes shared links ambiguous.

## Trace UI information architecture

### Main workspace

Desktop layout:

```text
┌────────────────────────────────────────────────────────────────────────┐
│ Breadcrumb · global search · filters · share/compare/replay controls   │
├──────────────┬─────────────────────────────────────┬───────────────────┤
│ Sessions /   │ Graph | Tree | Timeline             │ Context inspector │
│ executions   │                                     │ object-specific   │
│              │ exact executed path                 │ tabs              │
├──────────────┴─────────────────────────────────────┴───────────────────┤
│ Selected observation summary / inputs / outputs / prompt / metadata    │
├────────────────────────────────────────────────────────────────────────┤
│ Events | Logs | JSON | Evidence                                        │
└────────────────────────────────────────────────────────────────────────┘
```

All panels collapse. Width/visibility preferences persist per user. Below the desktop
breakpoint, the inspector becomes a drawer and the left list becomes a slide-over.

### Execution header

Always visible:

- agent name, execution ID and status;
- duration and queue time;
- node/generation/tool/SDK/retry/error counts;
- token totals and cost;
- actor, environment and agent version;
- session, started/finished, commit and deployment;
- live/freshness/content-policy indicators.

Unknown metrics display “not reported”, never zero.

### Graph

Reuse Cytoscape with a trace-specific adapter.

Required interactions:

- zoom, pan, fit and reset;
- expand/collapse node and subtree;
- group child calls inside an agent/node;
- focus selected node;
- follow live execution;
- highlight critical, failed and retry paths;
- search;
- filter by type/status;
- branch and loop labels;
- lazy expansion of subgraphs and A2A executions;
- URL-synchronized selection.

Visual state:

- queued: neutral dashed;
- running: restrained accent with activity indicator;
- success: green state marker;
- failed/timed out/refused: red or warning marker;
- skipped/cancelled: muted;
- retry: explicit loop/edge badge;
- waiting/approval: pause state.

Color is not the only signal; icon, label and border pattern carry status.

### Tree and timeline

Tree view is the accessible, deterministic alternative to the graph. It supports arrow
navigation, Enter to select and Space to expand.

Timeline is a CSS/canvas-free waterfall initially:

- shared horizontal scale;
- nested rows;
- parallel spans;
- queue/network/LLM/tool/SDK segments;
- critical path;
- zoomed range;
- open/running bars;
- clock-skew warning;
- late-arrival marker.

### Inspector

Common tabs:

- Overview
- Inputs & Outputs
- Events
- Errors
- Metadata

Type-specific tabs:

- Agent: nodes, metrics, models, tools and evidence.
- Node: framework, input/output state, children, transitions and checkpoints.
- Generation: provider/model, prompts/messages, parameters, tokens, latency, cost,
  tool calls and response.
- Tool/MCP: arguments/result, server, endpoint, permissions and caller.
- SDK: SDK/version, operation, arguments/result and affected resources.
- Retrieval: query, source, documents/chunks and timing.
- Evaluation: evaluator, score, verdict and linked experiment.

### Large text/content viewer

The default is a small redacted preview plus token/character/byte count.

Expanded modes:

- preview;
- expanded inline;
- fullscreen.

Features:

- line numbers;
- search and match count;
- copy;
- download;
- diff against prompt/artifact version or comparison execution;
- raw JSON toggle;
- content availability/retention notice.

No syntax-highlighting dependency is required for the first version; structured JSON and
line rendering can use existing browser capabilities. A dependency can be proposed later
with measured need.

### Session page

The session page contains:

- actor and invocation source;
- duration and active/terminal status;
- agents and environments;
- aggregate token/cost/error metrics;
- chronological execution list;
- cross-trace timeline;
- retries, evaluation runs and replay lineage;
- session tags and related artifacts.

### Static agent architecture

Do not overload the current `/graph` estate dependency page.

The Agent page gains a dedicated Architecture view composed from:

- registered descriptor and version;
- graph nodes/subgraphs;
- models and routes;
- tools and SDKs;
- MCP servers;
- other agents/A2A edges;
- data sources;
- observed frequency/failure overlays.

The live execution graph remains trace scoped and shows only the path actually taken.

### Analytics

Simple, bounded views:

- invocations by user/actor, agent, team, project and environment;
- sessions/runs;
- success/error rate;
- duration/cost/token percentiles;
- model/provider usage and failure;
- tool/SDK/MCP usage and failure;
- cache hit rate;
- ingest/export health.

Charts remain sparse and operational. Tables and ranked lists are preferred where they
answer the question more directly.

### Users

Observe gains a Users list and user detail page.

Users list:

- user/pseudonym and approved team/application metadata;
- sessions and agent invocations;
- model, SDK, tool and MCP-tool call counts;
- tokens, cost, success/error rate and last activity;
- filters by project, environment, team, source, agent, model, SDK and MCP server/tool.

User detail:

- activity summary and telemetry coverage;
- session/execution timeline;
- agents invoked;
- Claude/other model calls with tokens/cost/latency;
- Cursor/other SDK calls by operation;
- tools and MCP servers with one row per MCP tool;
- errors, retries and denied operations;
- deep links to each execution and selected observation.

The user page is an observability/audit view, not an employee productivity score. It
does not rank users by opaque “performance” or infer intent.

## Scenario coverage

The design and tests must cover these distinct behaviors:

| Scenario | Required representation |
|---|---|
| Simple one-node agent | one execution root with child operations |
| Direct user-to-Claude call | user activity execution with generation child |
| Direct Cursor SDK workflow | user activity execution with SDK/tool children |
| User invokes agent | initiating user retained through all nested operations |
| Service invokes agent for user | user and effective service actor both retained |
| Same user across approved identity aliases | one observed user through explicit bindings |
| Unknown/unpermitted user identity | pseudonymous or unknown user; activity still counted safely |
| MCP usage analytics | calls grouped by user, server and individual tool |
| Partial instrumentation | source coverage marked partial; missing activity not inferred |
| Sequential graph | deterministic ordered edges and timeline |
| Parallel branches | simultaneous bars and branch fan-out/fan-in |
| Conditional branch | chosen edge highlighted, unchosen edge optionally shown as skipped |
| Loop | repeated node with iteration number, not an accidental cycle error |
| Framework retry | retry observation and edge with attempt/backoff |
| Provider retry | child generation attempts under one logical generation |
| Subgraph | collapsible group with stable path |
| Multi-agent workflow | separate agent execution roots linked in one workspace |
| Cross-trace A2A | lazy child execution link with propagated context |
| Human approval | waiting state, request and decision events |
| Interrupt/resume | same execution or explicit resumed execution lineage |
| Checkpoint | checkpoint event and safe state reference |
| Streaming LLM | open generation, TTFT, chunks, cancellation/final usage |
| Tool-calling LLM | generation tool call linked to actual tool execution |
| MCP both sides traced | client/server pair without false duplicate |
| SDK calling nested tools | SDK parent with filesystem/git/test children |
| HTTP/database calls | safe metadata, no credentials/query literals |
| Retrieval | source/chunk metadata with lazy content |
| Evaluation fail then retry | evaluation edge, failed path, retry and final success |
| Guardrail refusal | refused status distinct from execution error |
| Cancellation/timeout | terminal state and incomplete-child handling |
| Unhandled exception | safe error summary and optional protected stack |
| Multiple roots | malformed warning; all roots still queryable |
| Parent arrives late | child retained and graph repaired later |
| Conflicting duplicate | quarantine surfaced without corrupting execution |
| Clock skew | original timestamps retained with warning |
| Late terminal update | open observation replaced by valid terminal version |
| Telemetry outage | agent continues; queue/spool status observable |
| SDK queue overflow | bounded drop metric/event, no agent blockage |
| Content OFF | no preview/hash; metadata remains useful |
| Metadata only | sizes/counts and allowed digest only |
| Full content | encrypted lazy payload with mandatory secret scrub |
| Payload expired | metadata and digest remain; content states expired |
| Legal hold | content retained and access audited |
| Unauthorized payload viewer | metadata visible if permitted; content denied |
| Unknown framework/type | preserved as unknown with source convention |
| No provider cost/tokens | “not reported”, never fabricated zero |
| Reasoning tokens/summary | stored only when provider explicitly returns them |
| Hidden chain-of-thought | never requested, reconstructed or synthesized |
| Session with retries | related executions and replay lineage |
| Very large trace | paginated/lazy graph and timeline, declared truncation |
| Very large payload | metadata first, streamed/ranged content on demand |
| Live reconnect | SSE resumes from `Last-Event-ID` without duplicate states |
| Air-gapped deployment | no required external network or SaaS callback |

## Accessibility

- `Ctrl/Cmd+K`: global search.
- `Ctrl/Cmd+P`: project/execution switcher.
- Escape: close inspector/fullscreen and clear graph focus.
- Arrow keys: move tree/list/graph focus.
- Enter: open/select.
- Space: expand/collapse.
- Every icon-only control has an accessible label and tooltip.
- Graph status has text/icon equivalents.
- Focus never becomes trapped in Cytoscape; an accessible tree is always available.
- Resize/collapse controls are keyboard operable.

## Performance and reliability

### SDK

- bounded asynchronous queues;
- batch trace export;
- lower-latency batch for lifecycle events;
- configurable head sampling;
- explicit dropped-item counters;
- exporter failures never fail the agent call;
- `force_flush` only at process/serverless lifecycle boundaries;
- stream wrappers do not buffer complete responses.

### Collector/ingest

- disk spool with quota and backpressure policy;
- exponential retry and poison quarantine;
- per-credential request/concurrency limits;
- content split before durable storage;
- trace-aware tail sampling after a bounded completion window;
- keep errors, retries, high latency and explicit debug traces;
- deterministic decisions shared across traces/logs for one execution.

### Query/UI

- cursor pagination;
- bounded default time ranges;
- lazy child/payload/event loading;
- viewport rendering for large trees/timelines;
- graph node budget and collapsed groups;
- SSE with cursor resume and backoff;
- stale/freshness indicators;
- no aggressive polling.

Initial performance budgets:

- SDK p95 synchronous instrumentation overhead: under 2 ms per operation excluding
  serialization/export thread;
- no network wait on the agent request path;
- ingest acknowledgement p95 under 100 ms after durable local/object-store write in the
  local reference stack;
- live lifecycle visible p95 under 1 second on a healthy local stack;
- execution summary p95 under 500 ms for 30-day project windows;
- user activity summary p95 under 500 ms for the default 30-day window;
- first trace workspace render under 2 seconds for 5,000 observations, with graph
  initially grouped.

Budgets are certified with measured load tests, not assumed.

## Compatibility and migration

1. Keep current OTLP trace ingest compatible.
2. Add new semantic attributes; do not reinterpret existing fields silently.
3. Map existing normalized kinds to the new taxonomy at query time during backfill:
   `inference → generation`, `workflow → chain` unless explicit LangGraph node metadata
   makes it `node`.
4. Preserve old Observe trace routes as aliases.
5. Preserve operations read APIs and direct ingest while the projection is compared.
6. Run dual-read/compare dashboards before making the projection authoritative.
7. Never edit applied Observe or Alembic migrations.
8. Regenerate OpenAPI and TypeScript clients with each BFF contract change.
9. Update stale README, contract and project-state statements in the same architecture
   slice.

## Phased delivery plan

Security, tenant isolation, content safety and tests are gates in every phase. Phase 12
is additional hardening, not the first time security is considered.

### Phase 1 — repository audit, architecture and data model

Deliverables:

- this plan;
- current-state audit;
- root `PLAN.md`;
- recorded architecture decision and current project state.

Exit gate:

- no production code changed;
- existing and target boundaries are explicit;
- known contract defects and approval gates are named.

### Phase 2 — canonical ingestion and storage

Work:

- repair freshness and payload-access contract holes;
- define semantic attribute and API schemas;
- add Observe PostgreSQL migration 003;
- add versioned ClickHouse migrations;
- add execution, event, edge and index storage;
- add observed-user identity, attribution and per-user query dimensions;
- add OTLP logs/lifecycle ingest;
- move content split/secret scrub to the first durable boundary;
- add operations projection outbox but do not switch consumers yet.

Tests:

- migration upgrade from current data and fresh database;
- real PostgreSQL + ClickHouse worker/query integration;
- idempotency, late parent, conflict, cycle and malformed traces;
- content OFF/metadata/full, redaction and large payload;
- tenant isolation and auth/scope limits.

### Phase 3 — LangGraph and Agent/Node/State tracing

Work:

- implement first-class LangGraph callback/stream integration;
- emit execution/node/transition/checkpoint/interrupt/approval semantics;
- build the deterministic FOSS Remediation demo graph;
- project content-free summaries to operations and compare totals.

Tests:

- sync/async/streaming graph;
- conditional branch, parallel fan-out, loop, retry, checkpoint, subgraph and interrupt;
- exact parentage and state-reference policy;
- demo trace visible through query API.

### Phase 4 — LLM, tool, SDK and generic instrumentation

Work:

- fix OpenAI/Anthropic stream span lifetime;
- complete LangChain and OpenAI Agents adapters;
- add typed SDK/tool APIs and Cursor-style SDK operations;
- add HTTP/database safe instrumentation;
- replace placeholders only when certified.

Tests:

- vendor-shaped fixtures and optional real integration tests;
- stream consume/cancel/error;
- tool-calling model linkage;
- prompt/message parameter/token/cost capture;
- no hidden reasoning and no credential leakage.

### Phase 5 — sessions, actor context and correlation

Work:

- expand session model;
- observed users, identity bindings, invocation/effective actor/source/privacy fields;
- direct `user_activity` executions and user attribution through agent/A2A chains;
- execution/run/trace/session correlation;
- replay lineage;
- operations projection becomes authoritative after comparison passes.

Tests:

- session grouping, retries, multi-agent membership and source types;
- actor masking, user identity binding and per-user model/SDK/tool/MCP-tool analytics;
- legacy operations read compatibility.

### Phase 6 — execution workspace and graph

Work:

- project-scoped deep links;
- session/execution master-detail workspace;
- Cytoscape live execution graph;
- accessible trace tree;
- grouping, collapse, search, filters and path highlighting;
- realistic demo data.

Tests:

- graph adapter unit tests;
- malformed/cycle/parallel/loop/retry/A2A rendering;
- selected observation synchronized to URL;
- keyboard tree flow.

### Phase 7 — inspector and protected content

Work:

- type-aware inspector;
- prompt/message/tool/SDK/state viewers;
- preview/expanded/fullscreen;
- search/copy/download/diff/raw JSON;
- audited payload access.

Tests:

- type-specific rendering;
- missing/expired/redacted/denied payload states;
- large payload lazy load;
- content capability enforcement and audit.

### Phase 8 — timeline and latency analysis

Work:

- span waterfall with shared scale;
- queue/self/network/TTFT timing;
- critical path and clock-skew/late-data markers;
- session-level timeline.

Tests:

- parallel spans, open spans, skew, critical path and zoom range.

### Phase 9 — real-time execution

Work:

- typed SSE lifecycle stream;
- cursor/`Last-Event-ID` reconnect;
- execution state reducer;
- live graph/timeline updates and follow mode;
- stale/export-backlog indicators.

Tests:

- queued/running/success/failure transitions;
- out-of-order events;
- disconnect/reconnect with no duplicate terminal states;
- bounded stream retention.

### Phase 10 — metrics and analytics

Work:

- execution/session/user/actor/agent/environment aggregates;
- p50/p90/p95/p99;
- model/tool/SDK/MCP failure and latency;
- cost/tokens/cache;
- Observe pipeline health metrics;
- sampling controls and tail-sampling certification.

Tests:

- aggregate correctness against raw rows;
- unknown vs zero;
- retention boundary and sampled population labels.

### Phase 11 — MCP and A2A propagation

Work:

- MCP client/server integration and pair rendering;
- A2A same-trace/cross-trace links;
- lazy cross-agent graph expansion;
- trust-boundary propagation policy.

Tests:

- HTTP and non-header transport propagation;
- duplicate suppression/pairing;
- retries remain distinct;
- cross-tenant context assertion rejected.

### Phase 12 — security and privacy hardening

Work:

- enterprise secret-pattern registry;
- field masking and raw-content capability;
- payload access audit and legal hold;
- retention deletion/reconciliation;
- RBAC for Observe views/actions;
- non-superuser control-plane database role/RLS certification;
- abuse/rate-limit and export security review.

Tests:

- credential corpus redaction;
- cross-tenant and cross-project isolation;
- privilege matrix;
- retention/legal hold;
- airgap egress denial.

### Phase 13 — Docker/dev tooling and final certification

Work:

- requested `.sh` and `.ps1` dev scripts;
- align README, `.env.example`, Compose, BYOC/airgap and health checks;
- one-command deterministic FOSS demo;
- optional real-provider demo behind explicit credentials;
- recovery, restart, clean rebuild and load certification.

Exit gate:

- all final verification items below pass and are recorded with command output.

## Per-phase operating rule

After every phase:

1. run that service’s unit and integration tests;
2. run contract generation/checks;
3. build and start the application;
4. generate/continue the demo execution;
5. inspect the affected UI and API;
6. fix errors before marking the phase complete;
7. update all mandatory `PROJECT_STATE.md` sections.

Only one phase is `in_progress` at a time.

## FOSS Remediation reference execution

The deterministic demo must work without provider credentials and produce:

```text
User Request
└─ Orchestrator
   ├─ Analysis Agent
   │  ├─ Repository Retrieval
   │  ├─ Vulnerability Scanner
   │  └─ LLM Analysis
   └─ Coding Agent
      ├─ Claude generation
      └─ Cursor SDK
         ├─ Filesystem edit
         ├─ Git diff
         └─ Test Runner
            └─ failed test
               └─ retry Coding Agent
                  └─ successful test
                     └─ Evaluator
                        └─ Final Response
```

It includes parallel analysis/scanning, a failed test, retry loop, prompt version,
redacted content, token/cost values, git metadata, tool and SDK calls, evaluation and
session context. A slow mode emits lifecycle events for live UI verification.

The deterministic adapters are clearly labeled simulated. Optional real-provider mode
is separate and never required for the offline/air-gapped test suite.

## Final certification checklist

Completion cannot be claimed until:

- full Compose starts from an empty volume;
- migrations apply from current and fresh state;
- the FOSS trace is generated through supported instrumentation;
- session and execution deep links open;
- graph renders and expands/collapses correctly;
- selected nodes open the correct inspector;
- prompt/output previews and protected expansion work;
- LLM, tool, SDK, MCP/A2A fields are accurate for emitted data;
- timeline and critical path are correct;
- live updates transition without refresh;
- filters and search match raw data;
- errors/retries and malformed data remain understandable;
- payload expiry/redaction/denial states are correct;
- Docker stop/start/restart/rebuild/reset scripts work on shell and PowerShell;
- unit, integration, ingestion, SDK, propagation, redaction, large-payload, UI and
  end-to-end tests pass;
- measured performance budgets and known limitations are published.

## Approval gates and current blockers

Approved on 2026-09-16:

1. Observe is canonical and Operations is a durable content-free projection.
2. The public SDK retains the existing `aap-trace` / `aap_trace` identity.
3. `@playwright/test` may be added as a web development dependency for browser
   certification.

Remaining rules/blockers:

1. approve any other proposed new dependency individually;
2. treat unresolved Q-013/Q-014/Q-015 (login, RBAC, effective RLS) as blockers for
   production certification, not blockers for local feature development.

No real model-provider credential currently exists in the local suite. The deterministic
demo avoids making that an implementation blocker.
