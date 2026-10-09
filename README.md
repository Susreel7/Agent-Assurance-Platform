# Agent Assurance Platform

A research prototype for observing and evaluating multi-step AI agents.

It keeps four kinds of state apart: durable execution metadata in PostgreSQL, high-volume analytical traces in ClickHouse, ephemeral propagation in Redis, and protected content in object storage. The same images are specified for three deployments — operator SaaS, a customer-controlled cloud, and an air-gapped install — and the process refuses to boot if the combination would leak.

FastAPI · Go · PostgreSQL · ClickHouse · Redis · OpenTelemetry · React

## Pages

| | |
|---|---|
| [System](docs/system.md) | Services, boundaries, and what each one is allowed to store |
| [Data paths](docs/data-paths.md) | PostgreSQL, ClickHouse, Redis, and protected content |
| [Deployment](docs/deployment.md) | SaaS, customer cloud, air-gapped, and how to run it locally |
| [Harnesses](docs/harnesses.md) | Cursor, Claude Code, Copilot, Codex, Gemini CLI, LangGraph, SDK, and CI |
| [Console](docs/console.md) | Every screen, and what a fresh install shows |
| [Research position](docs/research.md) | The question this prototype is studying, and a résumé-length description |
| [Tracing](docs/tracing/architecture.md) | How OTLP ingest, the SDK, and privacy capture fit together |
| [Local tracing setup](docs/tracing/local-development.md) | Runtime credentials after the stack is seeded |

Working conventions for anyone changing the code are in [AGENTS.md](AGENTS.md). Delivery status is in [PROJECT_STATE.md](PROJECT_STATE.md).

## Harnesses the ledger can name

Each mark links to the page for that client. The same eight values are a database check constraint and the strip on the console home page.

[![Cursor](docs/assets/harnesses/cursor.svg)](docs/harnesses.md#cursor)
[![Claude Code](docs/assets/harnesses/claude.svg)](docs/harnesses.md#claude-code)
[![GitHub Copilot](docs/assets/harnesses/copilot.svg)](docs/harnesses.md#github-copilot)
[![OpenAI Codex](docs/assets/harnesses/codex.svg)](docs/harnesses.md#openai-codex)
[![Gemini CLI](docs/assets/harnesses/gemini.svg)](docs/harnesses.md#gemini-cli)
[![LangGraph](docs/assets/harnesses/langgraph.svg)](docs/harnesses.md#langgraph)
[![SDK](docs/assets/harnesses/sdk.svg)](docs/harnesses.md#sdk)
[![CI](docs/assets/harnesses/ci.svg)](docs/harnesses.md#ci)

## Run it

Docker Compose v2.

```sh
make up
```

Windows, once local development secrets exist:

```text
.\scripts\dev-up.ps1
```

| Surface | URL |
|---|---|
| [Console](http://localhost:5173) | http://localhost:5173 |
| [API reference](http://localhost:8000/docs) | http://localhost:8000/docs |
| Readiness | http://localhost:8000/readyz |

Sign-in with no issuer configured is a development session at `developer@localhost`. A real directory is an OIDC issuer and audience in the environment, never a value committed here. Details are in [Deployment](docs/deployment.md).

```sh
make byoc-up   # customer-hosted paths, MinIO standing in for S3
make test
make check
```

The adapter's only shipped MCP server is [`examples/mcp`](examples/mcp/README.md). It is synthetic: no network client and no credential.

## Layout

```text
services/api          control plane
services/gateway      model data plane (Go)
services/observe      OTLP ingest, normalization, query
services/collector    estate-side collector
services/prompt       prompt and rule workspace
services/evaluate     datasets, experiments, gates
services/mcp-adapter  grant check in front of MCP
services/web          console
sdk/                  Python and TypeScript tracing SDKs
packages/             descriptor schema and CLI
examples/mcp          synthetic MCP server
deploy/helm           shared and AWS BYOC values
docs/                 the pages linked above
```

## What this repository does not contain

No identity-provider tenant, client secret, signing key, or internal hostname. `.env` is gitignored. Copy [`.env.example`](.env.example). If you point the adapter at your own MCP server, keep that configuration out of git.
