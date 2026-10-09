# Agent Assurance Platform — working conventions

Read this at the start of every session. It is the contract for how this codebase is written.

## Shape of the system

This repository is a licensed suite of independently deployable products:

- `services/api`: assurance/control plane (FastAPI + PostgreSQL).
- `services/gateway`: stateless low-latency model data plane (Go).
- `services/observe-*`: OTLP ingest, normalization and trace query.
- prompt and evaluation services own their APIs and PostgreSQL schemas.
- `services/web`: one entitlement-aware console over all enabled products.

Services communicate through versioned HTTP, OTLP and event contracts. They never import
another service's implementation or read another service's tables. A shared PostgreSQL
cluster is acceptable for the initial deployment, but schemas and migrations have one
owner. ClickHouse owns hot trace analytics, Redis owns ephemeral queue/cache/limit state,
and the object-store provider owns payloads. Redis is never the only durable copy.

The four-file domain rules below apply inside `services/api`.

Domain modules live in `app/domains/<name>/` with exactly four files:

| File | Contains | Must not contain |
|---|---|---|
| `schemas.py` | Pydantic models for the boundary | SQL, business logic |
| `repository.py` | SQL only, via SQLAlchemy `select()` | Business logic, HTTP concerns |
| `service.py` | Business logic, orchestration | Raw SQL, HTTP concerns |
| `router.py` | Thin HTTP handlers | Business logic of any kind |

ORM models live in `app/db/models/<migration-area>.py`, not in the domain — the four-file
rule has no room for them, and a model is often read by a neighbouring domain's
repository while its `service.py` stays private. Models are thin: no relationships, no
cascades, no behaviour.

Request dependencies live in `app/api/deps.py`. Tenant resolution is the security
boundary of the application, so it stays in one short file that can be read in full.

## Non-negotiable rules

1. **Never write raw SQL outside `repository.py`.**
2. **Never import another domain's `repository.py`.** Import its `service.py`.
3. **Within the assurance/control-plane API, dependency direction is one-way:**
   `customers -> frameworks -> registry -> connections -> mcp_registry -> releases -> bom -> operations -> composition -> evidence -> engagements -> graph -> policy -> materiality -> accreditation -> assurance -> model_routing -> sla -> attestation -> portal`
   Never import rightward. Publish a domain event instead.
   The canonical order lives in `app/domains/layer_order.py`; keep this line aligned with it.
   `composition` parses descriptor declarations and reconciles them against `operations`
   telemetry; it sits before `assurance` because findings are recorded there, not in
   composition. `model_routing` compiles gateway policy from engagements, registry and
   `composition.model_policy`, evaluates pre-dispatch against `policy`, and records drift
   through `assurance` — so it sits after both.
   `operations` (runs, cost, tool and MCP usage) reads `registry` and `bom` and is read
   by nothing to its left. `home`, `modules`, and `workload_identity` sit outside this
   chain, as does the `observe` BFF: `home` composes the landing page, `modules` exposes
   signed entitlements, `observe` calls its independent query service without owning
   trace tables, and `workload_identity` is imported by request authentication and those
   cross-cutting service boundaries.
   `customers` sits first because accreditation is always produced *for a named client*,
   and nothing about a client depends on the agents delivered to them.
4. **`agent_versions`, `evidence_events` and `release_changes` are append-only.** No UPDATE, no
   DELETE. Database triggers enforce this. Do not attempt to work around them.
5. **Evidence stores digests, classifications and decisions. NEVER prompts, completions or tool
   arguments.** If a field could hold customer content, it does not belong in evidence. A test
   asserts no evidence text field exceeds 512 bytes; do not weaken it.
6. **Every query filters by `org_id`.** Row-level security is a backstop, not the control.
7. **Do not generate Alembic migrations.** Migrations are written by hand and reviewed line by
   line. Every service owns its own migration chain.
8. **Never read `os.environ` outside `app/config.py`.** All configuration flows through
   `get_settings()`. This is what makes BYOC deployment possible.
9. **Never call a cloud SDK directly outside `app/providers/`.** Secrets, object storage and
   signing go through the provider abstraction, because in BYOC the provider differs per customer.
10. **Do not change the hash-chain field order in `domains/evidence/service.py`.** It is frozen and
    every existing chain depends on it.

## Style

- Python 3.12, full type hints, `mypy` strict on `app/`.
- Pydantic v2 at every boundary. No bare `dict` crossing a module boundary.
- SQLAlchemy 2.0 style only: `select()`, never legacy `Query`.
- `ruff` for lint and format. Line length 100.
- Errors: raise domain exceptions from `service.py`; translate to HTTP in `router.py`.
- **Prefer explicit repetition over clever abstraction.** Boring code that is obviously correct
  beats concise code that needs study. This codebase is maintained by one person.

## Testing

- Every service function gets a unit test.
- Every endpoint gets an integration test against a real Postgres via testcontainers.
- **Golden-file tests guard two contracts:** the AAP descriptor and the accreditation pack. If a
  golden file changes, that is a breaking change — say so explicitly and stop.
- Never mock the database. Mock only outbound third-party HTTP.
- Invariant tests are more valuable than coverage. Prioritise: evidence immutability, chain
  verification, cross-tenant isolation, approver-of-record enforcement, evidence field size bounds.

## Deployment modes — this constrains everything

The same images run in three modes. Code must never assume which.

| Mode | Who operates | Tenancy | Egress to us |
|---|---|---|---|
| `saas` | We do | multi | n/a |
| `byoc` | Customer's cloud, we manage | single | opt-in metadata only |
| `airgap` | Customer, fully isolated | single | none, ever |

Consequences you must respect:

- **No Postgres extension beyond `pgcrypto`.** Managed Postgres (RDS, Azure Database, Cloud SQL)
  will not install Apache AGE or similar. The graph is recursive CTEs for this reason.
- **No hardcoded endpoints.** Everything through `get_settings()`.
- **No phone-home on the critical path.** Licensing is an offline signed file.
- **Signing key may live in the customer's KMS.** Never assume a local PEM.

## Do not

- Add a dependency without asking. The set is deliberately small.
- Introduce Kafka, Neo4j, Elasticsearch or Celery. Redis is approved only for ephemeral
  runtime-suite state; ClickHouse is approved only for observability.
- Add a caching layer before a measurement shows one is needed.
- Widen an API response without regenerating `openapi.json` and the typed client.

## Working mode

One complete vertical slice at a time: storage, service, API, contract, screen and tests.
The suite program may span slices, but a slice is not `OK` until its independent service
and cross-service contract have both been exercised.
