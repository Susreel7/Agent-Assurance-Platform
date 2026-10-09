# aap-trace (Python)

Thin OpenTelemetry GenAI tracing SDK for Agent Assurance **Observe** ingest (`POST /v1/traces`).

## Install

```bash
pip install aap-trace
pip install "aap-trace[openai,langchain]"  # optional integrations
```

## Quick start

```python
from aap_trace import CaptureMode, TraceConfig, configure, generation_span, tool_span, shutdown

configure(
    TraceConfig(
        endpoint="https://observe.example/v1/traces",
        bearer_token="aap_wk_<org>.<generation>.<secret>",
        organization_id="...",
        project_id="...",
        agent_id="...",
        session_id="conversation-123",
        environment="production",
        capture_mode=CaptureMode.DIGEST,
    )
)

with generation_span(provider="openai", model="gpt-4o", input_messages=[{"role": "user", "content": "hi"}]):
    with tool_span(name="search", arguments={"q": "policy"}):
        ...

shutdown()
```

## Brownfield (zero code)

Point standard OpenTelemetry auto-instrumentation at Observe:

```bash
export OTEL_SERVICE_NAME=my-agent
export OTEL_EXPORTER_OTLP_ENDPOINT=https://observe.example
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=https://observe.example/v1/traces
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer%20aap_wk_..."
export OTEL_TRACES_EXPORTER=otlp
export OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED=false
export AAP_ORGANIZATION_ID=...
export AAP_PROJECT_ID=...
export AAP_CAPTURE_MODE=digest
# optional: control-plane base for scores (defaults to trace host without /v1/... path)
export AAP_SCORE_BASE_URL=https://api.example
# optional identity
export AAP_AGENT_ID=...
export GEN_AI_CONVERSATION_ID=session-1
```

Run your app with `opentelemetry-instrument python app.py`. Spans still land on Observe; the normalizer maps OpenInference / OpenLLMetry attributes (see `docs/COMPATIBILITY.md`).

## API surface

- Context managers: `agent_span`, `node_span`, `state_transition_span`, `retry_span`, `human_approval_span`, `generation_span`, `tool_span`, `retrieval_span`, `handoff_span`
- Typed events: `record_event`, `record_checkpoint`, `record_output_state`, `record_approval_decision`
- Decorator: `aap_trace.spans.traced`
- W3C: `inject_headers` / `extract_headers`, `current_span_context()`
- Streaming: `aap_trace.streaming.wrap_sync_stream` / `wrap_async_stream`
- Scores: `get_client().scores.submit(...)` → `POST /v1/evaluate/workload/scores` on the control plane (optional `score_base_url` / `AAP_SCORE_BASE_URL` when it differs from the trace host)
- Integrations: `aap_trace.integrations.openai`, `anthropic`, `langchain`, `langgraph`, `llama_index`, `crewai`, `asgi`

LangGraph 1.x supports sync/async invoke, sync/async streaming, branches, loops,
checkpoints, interrupts and resume through `instrument_langgraph(...)`. See the
[LangGraph guide](../../docs/tracing/langgraph.md).

Secrets and message bodies are **not** logged by the SDK. Content follows `CaptureMode`: `none`, `digest`, `redacted`, `full` (see ingest contract).

## Development

```bash
cd sdk/python
pip install -e ".[dev]"
ruff check src tests
mypy src/aap_trace
pytest
```
