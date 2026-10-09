# Observe data plane

Independently deployable OTLP ingest, normalization worker, and trace query services.

## Processes

| Entrypoint | Port | Role |
|---|---|---|
| `observe-ingest` | 8080 | OTLP `/v1/traces`, durable envelope + manifest |
| `observe-worker` | 8081 | Normalize manifests → ClickHouse + Postgres metadata |
| `observe-query` | 8082 | Internal-token query APIs, SSE live tail |

## Storage

- **PostgreSQL** `observe` schema — manifests, payload refs, quarantine, trace metadata
- **ClickHouse** — normalized span analytics (`observe/clickhouse/init.sql`)
- **Object store** — raw OTLP envelopes; encrypted payload blobs in `full` capture mode
- **Redis** — optional ingest wake-up pub/sub only

## Configuration

All settings use the `OBSERVE_` prefix via `observe.config.get_settings()`.

Cloud object stores (`s3`, `azure`, `gcs`) are configuration stubs until the matching
optional extra is implemented; use `local` for Compose.

## Migrations

Hand-written SQL in `observe/migrations/`. Applied on startup when
`OBSERVE_RUN_MIGRATIONS_ON_STARTUP=true`.

## Contracts

See `docs/contracts/otel-ingest.md` and `docs/contracts/runtime-suite.md`.
