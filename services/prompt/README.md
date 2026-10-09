# Prompt artifact workspace

Independently deployable FastAPI service owning PostgreSQL schema `prompt`.

## Run locally

```bash
cd services/prompt
pip install -e ".[dev]"
export PROMPT_DATABASE_URL=postgresql://prompt:prompt@localhost:5432/prompt
export PROMPT_ENCRYPTION_KEYS_JSON='{"local:default":"<fernet-key>"}'
export PROMPT_INTERNAL_SERVICE_TOKEN=dev-internal-token
prompt-api
```

Human APIs require `Authorization: Bearer $PROMPT_INTERNAL_SERVICE_TOKEN` plus mandatory
`X-Organization-Id`, `X-Project-Id`, and `X-Actor` headers matching the path scope.

Runtime fetch uses workload bearer introspection (`prompt` module, `prompt:read` scope).

Console/BFF may inspect the same resolved artifact (label, pin/revision, production
guards, ETag, digest headers) without a workload token via internal auth:

`GET /v1/orgs/{org_id}/projects/{project_id}/runtime/read/artifacts/{artifact_key}`

Playground `compare` mode is documented in OpenAPI (`PlaygroundCompareOutput`): parallel
router calls with one result per artifact ref and shared merged messages.

## Tests

```bash
pytest
ruff check .
mypy prompt
prompt-export-openapi openapi.json
```

Integration tests use testcontainers when Docker is available (`PROMPT_DATABASE_URL` optional).
Optional live router check: `PROMPT_ROUTER_INTEGRATION_URL=http://localhost:8080 pytest -k live_router`.

KMS key refs: `kms:aws:<key-id>`, `kms:azure:<vault-url>#<key-name>`, `kms:gcp:<resource>`.
Install extras: `pip install 'aap-prompt[aws]'`, `[azure]`, or `[gcp]`.

Protected label promotion requires internal scopes via `X-Internal-Scopes`
(`prompt:label:production`, `prompt:label:staging`, `prompt:label:latest`).

Playground streaming cancel is durable in Postgres (`cancel_requested` → worker
`cancelled`). Optional `PROMPT_REDIS_URL` publishes ephemeral cancel signals for
multi-instance deployments; without Redis, single-instance local + Postgres
reconciliation still works.
