# Convention compatibility (OpenInference / OpenLLMetry)

Observe ingest accepts **standard OTLP**. This SDK emits **OpenTelemetry GenAI 1.37+** semantic attributes. The Observe normalizer (`services/observe`) also maps legacy conventions.

| Source | Detection keys | Normalized kind hints |
|--------|----------------|------------------------|
| OTel GenAI 1.37 | `gen_ai.*` | `gen_ai.operation.name` → inference, tool, retrieval, agent, … |
| OpenInference | `openinference.*`, `llm.*` | LLM / tool / retrieval spans |
| OpenLLMetry | `traceloop.*` | Provider-specific LLM spans |
| LangGraph | `langgraph.node`, `langgraph.step` | workflow |
| CrewAI | `crewai.*` | agent / tool |

## Migrating from OpenInference

| OpenInference | aap-trace (GenAI) |
|---------------|-------------------|
| `openinference.span.kind` | `gen_ai.operation.name` |
| `llm.model_name` | `gen_ai.request.model` |
| `llm.token_count.prompt` | `gen_ai.usage.input_tokens` |
| `llm.token_count.completion` | `gen_ai.usage.output_tokens` |
| session id attributes | `gen_ai.conversation.id` |

## Migrating from OpenLLMetry (Traceloop)

| Traceloop | aap-trace |
|-----------|-----------|
| `traceloop.span.kind` | span helpers (`generation_span`, `tool_span`, …) |
| `traceloop.association.properties` | `TraceConfig.metadata`, `tags` |
| Workflow wrappers | `workflow_span`, LangGraph `wrap_langgraph_node` |

Brownfield apps can keep existing instrumentors and only change OTLP endpoint + `Authorization: Bearer aap_wk_...` headers.
