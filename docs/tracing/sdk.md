# Tracing SDK Reference

The compatibility-frozen Python distribution/import identity is `aap-trace` /
`aap_trace`. The TypeScript package is `@agent-assurance/trace`. Both emit the same
OpenTelemetry and `aap.*` semantic attributes.

## Execution scopes

- `agent_span`: complete invocation and execution ID.
- `node_span`: graph node path, step, attempt, iteration and state references.
- `generation_span`: provider/model request, usage, latency, cost and content references.
- `tool_span`, `sdk_span`, `retrieval_span`: typed external work.
- `http_span`, `database_span`: safe network/storage metadata.
- `mcp_span`, `a2a_span`: protocol-aware cross-boundary work.
- `state_transition_span`, `retry_span`, `human_approval_span`: explicit workflow state.
- `observation_span`: supported custom/future observation type.

`start_managed_span` supports streaming and callback APIs whose span lifetime outlives
the function that starts the operation.

## Content levels

SDK capture modes are `none`, `digest`, `redacted`, and `full`. The server-side project
policy is authoritative and sanitizes before durable write even if a client asks for
more. Prompts, messages, tool/SDK arguments, state, retrieval documents, and outputs
are content fields.

## Context propagation

Use `inject_headers` / `extract_headers` for HTTP and `inject_mcp_context` /
`extract_mcp_context` for MCP JSON-RPC. OpenTelemetry parentage should be preserved
across queues and agent handoffs whenever the transport supports it.

## Shutdown

Call `shutdown()` during a graceful process stop to flush the batch exporter. Do not
flush after each span; that would place telemetry latency on the agent's critical path.
