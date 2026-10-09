# System

Agent Assurance Platform is a control plane and an observation plane for multi-step AI agents. One console sits over both. Services do not import each other or read each other's tables. They talk over versioned HTTP, OTLP, and small event contracts.

## What runs

| Service | Role | Language |
|---|---|---|
| `services/api` | Tenancy, identity, policy, registry, evidence, operations | Python, FastAPI |
| `services/gateway` | Low-latency model data plane. OpenAI-compatible routes | Go |
| `services/observe` | OTLP ingest, normalization, query | Python |
| `services/collector` | Estate-side collector. Deliberately small | Python |
| `services/prompt` | Versioned prompts, rules, and skills | Python |
| `services/evaluate` | Datasets, experiments, evaluators, gates | Python |
| `services/mcp-adapter` | MCP calls that must pass a grant before they reach a server | Python |
| `services/web` | Operator console | React, TypeScript |

Shared packages:

- `packages/aap-spec` — the agent descriptor schema
- `packages/aap-cli` — validate, diff, and publish a descriptor
- `sdk/python` and `sdk/typescript` — tracing SDKs, including a LangGraph integration

## Boundaries that do not move

1. Evidence stores digests, classifications, and decisions. It does not store prompts, completions, or tool arguments. A test rejects an evidence text field over 512 bytes.
2. Every tenant query filters by `org_id`. Row-level security is a backstop, not the control.
3. `agent_versions`, `evidence_events`, and `release_changes` are append-only. Database triggers enforce that.
4. Configuration is read only in `services/api/app/config.py`. An invalid combination of deployment mode, tenancy, and egress refuses to boot.
5. Cloud SDKs are called only behind `services/api/app/providers/`, so a customer-hosted install can swap secrets, object storage, and signing without a code change.

The dependency order inside the API is one-way and is listed in [AGENTS.md](../AGENTS.md).

## Where to go next

- [Data paths](data-paths.md) — Postgres, ClickHouse, Redis, and protected content
- [Deployment](deployment.md) — SaaS, customer cloud, and air-gapped
- [Harnesses](harnesses.md) — which clients the ledger can name
- [Console](console.md) — the screens
- [Research position](research.md) — what this prototype is studying
