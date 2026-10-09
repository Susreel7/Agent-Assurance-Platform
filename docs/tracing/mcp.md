# MCP and A2A Tracing

## MCP

Wrap an MCP operation with `mcp_span`, recording server, JSON-RPC method, role
(`client` or `server`), request ID, and policy-safe arguments. Use
`inject_mcp_context` before sending a JSON-RPC message and `extract_mcp_context` on the
server before starting its span.

W3C `traceparent`, `tracestate`, and `baggage` are placed in the message `_meta` object.
Existing metadata is preserved. Instrumented client/server observations are correlated
by request ID and server; the execution link is de-duplicated rather than pretending the
two spans are one operation.

Never put credentials or transport headers in MCP attributes. MCP arguments/results
are content attributes and follow the project's capture, redaction, encryption, and
retention policy.

## Agent-to-agent

Use `a2a_span` for the caller-side handoff and propagate normal W3C context to the
callee. Preserve:

- caller and target agent IDs;
- target execution/trace IDs when known;
- parent execution/trace context;
- shared session ID;
- protocol and request correlation metadata.

The Observe worker records an `a2a_invocation` execution link. The execution workspace
shows the relationship and deep-links to the child execution or trace. A callee remains
its own execution root; cross-agent expansion does not flatten ownership, policy, or
failure boundaries.
