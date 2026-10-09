# AAP Router (Go gateway)

Stateless OpenAI-compatible data plane. Signed `router.json` includes embedded
`workload_bindings` (same bytes are signed — no unsigned companion files).

## Snapshot layout (file mode)

When `GATEWAY_CONFIG_URL` is unset, the gateway loads from disk and polls
`GATEWAY_CONFIG_DIR` on `GATEWAY_CONFIG_POLL_INTERVAL` (default 30s).

```
/etc/gateway/
  router.json       # schema_revision 1 + workload_bindings[]
  router.json.sig   # detached ECDSA P-256 signature over router.json bytes
  credentials.json  # optional credential_ref map
```

## Remote signed config (HTTP mode)

When `GATEWAY_CONFIG_URL` is set, the gateway polls that URL with `If-None-Match`,
accepts only `200` or `304`, and verifies a **pinned** public key before activation.
It never fetches or trusts a public key from the endpoint.

Required verification key (one of):

- `GATEWAY_CONFIG_PUBLIC_KEY_PEM` — inline PEM
- `GATEWAY_CONFIG_PUBLIC_KEY_FILE` — path to PEM on disk

Optional request headers:

- `GATEWAY_CONFIG_AUTHORIZATION` → `Authorization`
- `GATEWAY_CONFIG_ORG_ID` → `X-Org-Id`

On `200`, the response must include `X-AAP-Config-Signature` (standard base64 detached
ES256 over the raw JSON body), `X-AAP-Config-Key-Id`, `X-AAP-Rules-Digest`,
`X-AAP-Snapshot-Id`, and `ETag` (typically `"<rules_digest>"`). Headers must match the
parsed signed JSON. Bodies are capped by `GATEWAY_CONFIG_MAX_BYTES` (default 4 MiB).
HTTP fetches use `GATEWAY_CONFIG_HTTP_TIMEOUT` (default 30s).

Set `GATEWAY_CONFIG_REQUIRED=true` to exit on startup if the first load fails. Any later
poll failure keeps the last good snapshot.

## Workload bindings (in signed JSON)

Each binding requires unique `generation_id` and `secret_hash`, matching snapshot
`organization_id` / `project_id`, non-expired `expires_at`, and non-revoked
`revoked_at`. Auth uses `aap_wk_<org>.<generation>.<secret>` hashed with SHA-256.

## Normalization

Anthropic, Bedrock Converse, Gemini, and Vertex chat/responses success and error
paths are mapped to OpenAI-compatible JSON. Native Anthropic/Gemini SSE and Bedrock
event-stream frames are converted incrementally to `chat.completion.chunk` + `[DONE]`.

Azure OpenAI URLs are built once with deployment path and `api-version` query.

## Build and test

```bash
cd services/gateway
gofmt -w .
go test ./...
go vet ./...
go test -bench=BenchmarkGatewayOverhead -benchmem ./internal/handler/ -run=^$
```
