# @agent-assurance/trace (TypeScript)

Node-first OpenTelemetry GenAI tracing SDK for Agent Assurance **Observe** (`POST /v1/traces`). Uses `AsyncLocalStorage` context propagation and fetch-based OTLP/HTTP export.

## Install

```bash
npm install @agent-assurance/trace
```

## Quick start

```typescript
import {
  configure,
  shutdown,
  withSpan,
  generationSpan,
  toolSpan,
} from "@agent-assurance/trace";

configure({
  endpoint: "https://observe.example/v1/traces",
  bearerToken: "aap_wk_<org>.<generation>.<secret>",
  organizationId: "...",
  projectId: "...",
  agentId: "...",
  sessionId: "conversation-123",
  captureMode: "digest",
});

await generationSpan("openai", "gpt-4o", [{ role: "user", content: "hi" }])(async () => {
  await toolSpan("search", { q: "policy" })(async () => {
    /* ... */
  });
});

await shutdown();
```

## Brownfield

```bash
export OTEL_SERVICE_NAME=my-agent
export OTEL_EXPORTER_OTLP_ENDPOINT=https://observe.example
export OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=https://observe.example/v1/traces
export OTEL_EXPORTER_OTLP_HEADERS="Authorization=Bearer%20aap_wk_..."
export OTEL_TRACES_EXPORTER=otlp
export AAP_ORGANIZATION_ID=...
export AAP_PROJECT_ID=...
# optional: control-plane base for scores (defaults to trace host without /v1/... path)
export AAP_SCORE_BASE_URL=https://api.example
```

Use `@opentelemetry/auto-instrumentations-node` or existing OpenLLMetry/OpenInference exporters pointed at the same endpoint. See `docs/COMPATIBILITY.md`.

Scores from `getClient().scores.submit(...)` call `POST /v1/evaluate/workload/scores` with the workload bearer (`evaluate:score` scope).

## Scripts

```bash
npm install
npm run typecheck
npm run lint
npm test
npm run build
```
