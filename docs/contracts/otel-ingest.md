# Contract: OTLP GenAI ingest

Observe accepts standard OTLP rather than requiring a proprietary reporter.

## Transport

- `POST /v1/traces`
- `POST /v1/logs` for correlated lifecycle/events and bounded uncorrelated platform logs
- `Content-Type: application/x-protobuf` or `application/json`
- optional `Content-Encoding: gzip`
- W3C `traceparent`/`tracestate`
- workload bearer token scoped to organization, project and optional agent
- maximum compressed request: 16 MiB
- maximum uncompressed request: 64 MiB
- maximum 10,000 spans or log records per request

Bodies are standard OTLP `ExportTraceServiceRequest` or `ExportLogsServiceRequest`.

Success uses the corresponding OTLP export response. Invalid records are removed before
the accepted envelope is persisted and are reported through OTLP partial success.
Authentication, decompression and whole-envelope parse failures reject the request.

## Durability

A successful response means:

1. the policy-sanitized canonical envelope is in object storage;
2. its sha256 digest, source-body digest, object key and tenant-scoped manifest are committed;
3. replaying the same digest is safe.

Raw source bytes are never durably written. Content fields are removed, digested, or
encrypted into tenant-scoped payload objects before the envelope write.

It does not mean ClickHouse already exposes the spans. Query freshness is reported
separately. Redis is a wake-up mechanism only; a manifest reconciler restores missing work.

## Canonical identity

- `trace_id` and `span_id` remain the source OTLP identifiers.
- `(organization_id, project_id, trace_id, span_id)` is idempotent.
- `parent_span_id` preserves hierarchy even when the parent arrives later.
- `gen_ai.conversation.id` groups traces into a session; it never replaces `trace_id`.
- Resource `service.name` plus `gen_ai.agent.id`/`name` resolve the registered agent.
- A token bound to an agent may not emit another agent identity.

## Semantic convention

The preferred schema is OpenTelemetry GenAI v1.37 or later:

- `gen_ai.operation.name`
- `gen_ai.provider.name`
- `gen_ai.request.model`, `gen_ai.response.model`
- `gen_ai.agent.id`, `gen_ai.agent.name`, `gen_ai.agent.version`
- `gen_ai.conversation.id`
- `gen_ai.usage.*`
- `gen_ai.prompt.name`, `gen_ai.prompt.version`
- `gen_ai.tool.*`, `gen_ai.retrieval.*`
- `gen_ai.system_instructions`, `gen_ai.input.messages`, `gen_ai.output.messages`

The normalizer also recognizes legacy GenAI message events, OpenInference, OpenLLMetry,
LangGraph metadata, OpenAI Agents, Google ADK, Semantic Kernel, CrewAI, AutoGen and MCP.
Every normalized span records the source convention and mapping revision.

The AAP semantic layer adds stable product dimensions:

- `aap.execution.id`, `aap.execution.parent_id`, `aap.execution.type`
- `aap.observation.type`, `aap.observation.sequence`
- `aap.project.id`, `aap.environment.id`, `aap.agent.version_id`
- `aap.user.id`, `aap.user.session_id`, `aap.actor.id`, `aap.actor.type`
- `aap.graph.*`, `aap.state.*`, `aap.retry.*`
- `aap.sdk.*`, `aap.mcp.*`, `aap.a2a.*`

## Content capture

Capture modes are:

- `none`: metadata only;
- `digest`: content digests only;
- `redacted`: digests plus approved bounded previews;
- `full`: encrypted payload objects plus digests and approved previews.

`full` never puts content in ClickHouse or the metadata envelope. The edge collector can
apply policy before data leaves the estate and Observe enforces the same boundary before
its first durable write. Object keys are server generated and tenant scoped. Payload
content is only exposed through the authenticated, audited content endpoint.

## Normalized span kinds

`workflow`, `agent`, `plan`, `inference`, `tool`, `mcp_tool`, `retrieval`, `embedding`,
`memory`, `guardrail`, `handoff`, `http`, and `unknown`.

The independent product observation taxonomy is `agent`, `node`, `generation`, `tool`,
`sdk`, `retrieval`, `chain`, `http`, `database`, `state_transition`, `event`,
`evaluation`, `error`, `retry`, `user_activity`, `mcp`, `a2a`, `checkpoint`,
`human_approval`, `guardrail`, `memory`, `embedding`, and `unknown`.

Unknown operations are retained as `unknown`; they are not discarded or guessed.

## Edge cases

- A child before its parent is valid.
- Duplicate identical spans are ignored; a conflicting duplicate is quarantined.
- Open spans may be replaced only by a later terminal version with the same identity.
- Clock skew is retained and flagged; source timestamps are never silently changed.
- Cycles and multiple roots are displayed as malformed traces and remain queryable.
- Traces over 25,000 spans are stored but detail responses paginate and declare truncation.
- Payload processing failure does not silently downgrade `full` to metadata-only.
- A poison envelope is quarantined after bounded retries without blocking later envelopes.
