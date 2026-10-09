# LangGraph instrumentation

`aap-trace[langgraph]` supports LangGraph 1.x and emits standard OpenTelemetry spans
with the AAP execution semantic layer. The adapter does not capture hidden reasoning.

## Minimal integration

```python
from aap_trace.integrations.langgraph import instrument_langgraph

compiled = builder.compile(checkpointer=checkpointer)
graph = instrument_langgraph(
    compiled,
    graph_name="foss-remediation",
    graph_version="git:abc123",
)

result = graph.invoke(
    {"repository": "acme/payments"},
    {"configurable": {"thread_id": "session-9281"}},
)
```

The proxy preserves the compiled graph API and instruments `invoke`, `ainvoke`, `stream`
and `astream`. It injects a fresh callback handler per invocation, so concurrent
executions do not share loop counters or active node state.

## Captured execution

- one `agent` root with `aap.execution.id`;
- one `node` observation per LangGraph node invocation;
- stable graph name, version, node ID/path and graph step;
- loop iteration for repeated node invocations;
- branch/trigger metadata as typed `state_transition` events;
- input/output state under the configured content-capture policy;
- checkpoint namespace and thread correlation;
- node errors with OpenTelemetry exception status;
- interrupts and approval requests;
- resume commands;
- nested LLM and tool spans under the active node context.

The static graph definition is represented by bounded nodes/edges and attached to the
root according to capture policy. Use `describe_langgraph(compiled)` when a control-plane
registration flow needs the same architecture contract directly.

## Manual node integration

Applications that construct nodes dynamically can wrap an individual sync or async
callable:

```python
from aap_trace.integrations.langgraph import wrap_langgraph_node

analysis = wrap_langgraph_node(
    "analysis",
    analysis,
    graph_name="foss-remediation",
    graph_version="git:abc123",
)
```

Use `on_checkpoint(...)` only for custom checkpointers that expose checkpoint IDs not
available through LangGraph callback metadata.

## Interrupt and approval semantics

An interrupt marks the node as waiting and emits `approval.requested`. A later
`Command(resume=...)` emits `execution.resumed`. Each external invocation remains a
separate agent execution; session/replay lineage links are added by the session layer.
Approval content follows capture policy and actor identity must be supplied by the host
application when known.

## Compatibility and limits

- Supported runtime: Python 3.12+, LangGraph `>=1.0,<2`.
- Callback metadata is version-isolated in `aap_trace.integrations.langgraph`.
- Nested runnable callbacks inheriting `langgraph_node` are suppressed, preventing one
  logical node from becoming duplicate node observations.
- A graph can contain at most 5,000 static nodes and 10,000 static edges in the emitted
  architecture contract; execution spans are not discarded by this static limit.
