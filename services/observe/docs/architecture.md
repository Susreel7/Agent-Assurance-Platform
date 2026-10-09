# Observe architecture

Three processes share one Python package and one container image. They do not import
`services/api` or read control-plane tables.

```
OTLP client → ingest → object store + Postgres manifest
                ↓ (Redis wake, optional)
              worker → ClickHouse spans + Postgres metadata/payload refs
Console/API → query → ClickHouse + signed payload metadata
```

Postgres polling reconciles pending manifests if Redis is unavailable. No raw span content
is stored in Postgres or ClickHouse; `full` capture writes encrypted blobs to object storage
only.
