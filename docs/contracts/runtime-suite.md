# Contract: Agent Runtime Suite services

This contract fixes service ownership and cross-service behavior before implementation.
Internal implementation may change; these boundaries may not drift silently.

## Modules and owners

| Module | Deployable | Owns | Durable store |
|---|---|---|---|
| Control | `api` | organizations, projects, identities, credentials, entitlements, model catalogue, signed router snapshots | PostgreSQL |
| Router | `gateway` | no authoritative configuration; request-local state only | none |
| Observe ingest | `observe-ingest` | raw OTLP envelopes and ingest manifests | object store + PostgreSQL manifest |
| Observe worker | `observe-worker` | normalization and analytical writes | ClickHouse |
| Observe query | `observe-query` | trace/session/score/search and authorized payload reads | ClickHouse + object store |
| Prompt | `prompt-api` | artifacts, immutable revisions, labels, dependencies | PostgreSQL + object store |
| Evaluate | `evaluate-api`, `evaluate-worker` | datasets, examples, experiments, evaluators, queues, rules | PostgreSQL + object store |
| Console | `web` | no business data | none |

Services may share a PostgreSQL server initially but never share schema ownership.

## Common request identity

Human requests carry an OIDC bearer token. Workloads carry an opaque AAP key exchanged for
a short-lived signed workload token, or a still-valid cached binding at the gateway.

Every authenticated principal resolves to:

```json
{
  "subject": "string",
  "organization_id": "uuid",
  "project_id": "uuid",
  "agent_id": "uuid-or-null",
  "environment": "dev|test|staging|production",
  "modules": ["router", "observe", "prompt", "evaluate"],
  "scopes": ["string"],
  "allowed_models": ["provider/model-pattern"],
  "expires_at": "RFC3339"
}
```

An organization or project header is context, never a credential. A workload bound to an
agent may not report, route or fetch protected configuration for another agent.

## Module discovery

`GET /v1/modules` is authenticated and returns only the caller's effective modules:

```json
{
  "revision": "sha256:...",
  "modules": {
    "router": {"enabled": true, "base_path": "/router", "limits": {}},
    "observe": {"enabled": true, "base_path": "/observe", "limits": {}},
    "prompt": {"enabled": false, "base_path": "/prompt", "limits": {}},
    "evaluate": {"enabled": false, "base_path": "/evaluate", "limits": {}}
  }
}
```

The edge proxy exposes one origin and dispatches by base path. A disabled service returns
`403 module_not_entitled`; an unavailable enabled service returns `503 module_unavailable`.

## Health contract

Every service exposes:

- `GET /healthz`: process liveness only; no dependency call.
- `GET /readyz`: dependency and active-config status.
- `GET /version`: build revision and supported contract revisions.

Readiness uses `ok`, `degraded`, or `not_ready`. It never returns HTML.

## Event envelope

Cross-service asynchronous events use this envelope:

```json
{
  "event_id": "uuid",
  "event_type": "dot.separated.name",
  "schema_revision": 1,
  "organization_id": "uuid",
  "project_id": "uuid",
  "subject_id": "string-or-null",
  "occurred_at": "RFC3339",
  "producer": "service-name",
  "producer_revision": "build-id",
  "idempotency_key": "string",
  "traceparent": "string-or-null",
  "payload": {}
}
```

Consumers are at-least-once and idempotent on `(producer, idempotency_key)`. Unknown
event revisions go to a dead-letter stream; they are never guessed.

## Availability rules

- Router dispatch uses an in-memory signed snapshot and no control-plane round trip.
- Observe ingest acknowledges only after the raw object and manifest are durable.
- Redis loss may remove live views and cached limits, but never durable traces or config.
- Prompt fetch supports ETag and bounded stale-if-error; exact revision fetch is immutable.
- Evaluate jobs are resumable and idempotent; a partial experiment remains explicitly partial.

## Data ownership and privacy

- PostgreSQL control data and ClickHouse trace metadata always carry organization and project.
- Object keys begin with `organization/project/purpose/` and are never accepted directly from a
  caller.
- Evidence stores only digests, classifications and decisions.
- Payload access is separately authorized and audited.
- Retention and legal hold apply to metadata and referenced objects as one logical record.

## Compatibility changes

OpenAPI, OTLP mapping and router snapshot changes require:

1. a checked-in contract fixture;
2. backward-compatible readers before writers emit the new revision;
3. mixed-version tests;
4. an explicit retirement date before removing an old revision.
