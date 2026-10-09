# Instrumentation

The SDK is a thin semantic layer over OpenTelemetry. It emits normal OTLP telemetry and
adds the `aap.*` attributes required to reconstruct agent execution semantics.

## Minimum setup

```python
from aap_trace import TraceConfig, configure

configure(TraceConfig.from_otel_env())
```

Required environment:

```text
OTEL_EXPORTER_OTLP_ENDPOINT=http://collector:4318
AAP_WORKLOAD_TOKEN=<scoped workload credential>
AAP_ORGANIZATION_ID=<organization UUID>
AAP_PROJECT_ID=<project UUID>
```

Set agent, environment, session, user, source, repository, and version metadata before
the first execution. Hidden chain-of-thought must never be inferred or manufactured.
Provider-exposed reasoning token counts or reasoning summaries may be recorded as
explicit metadata.

## Manual API

Use `agent_span` for the invocation root and typed children such as `node_span`,
`generation_span`, `tool_span`, `sdk_span`, `retrieval_span`, `http_span`,
`database_span`, `mcp_span`, and `a2a_span`. Record state changes, checkpoints,
approvals, retries, errors, and important evidence with the corresponding `record_*`
functions.

Decorators (`observe_agent`, `observe_node`, `observe_generation`, `observe_tool`, and
generic `observe`) preserve return values, exceptions, async behavior, and parentage.

## Automatic integrations

Supported integration modules cover LangGraph, LangChain callbacks, OpenAI,
Anthropic, OpenAI Agents SDK, ASGI/HTTP, LlamaIndex, and CrewAI foundations. Streaming
LLM wrappers keep spans open until completion, cancellation, or error and capture
time-to-first-token when available.

## Performance behavior

The SDK uses OpenTelemetry's batch span processor. Export does not occur on the agent's
critical path, and exporter failure does not fail the agent. Configure sampling at the
SDK/collector, keep payload capture at metadata or digest unless content is needed, and
call `shutdown()` during graceful process termination.
