# Research position

This repository is a personal research prototype. It is a systems study of what an enterprise agent platform has to separate, not a claim that every screen is backed by production traffic.

## Question

When an agent runs for a long time, across tools, models, and people, which facts have to be durable, which facts are analytical, which facts are ephemeral, and which facts must stay unreadable to the control plane?

The prototype answers that by building the split instead of describing it:

- PostgreSQL for identity, policy, evidence, and a content-free action ledger
- ClickHouse for high-volume traces
- Redis for ephemeral queues and limits
- object storage for protected payloads, behind a different key
- one configuration surface that refuses the wrong combination of tenancy and egress

## What a reader can inspect

| Claim | Where it is enforced |
|---|---|
| No prompt or tool argument in evidence | Field-size test and the evidence schema |
| No content columns on the action ledger | `agent_actions` migration and `agent_action_facets_valid()` |
| Tenant isolation is a query predicate, with RLS as a backstop | `org_id` on tenant tables, policies in the migrations |
| An agent action has a human root | `agent_instances.human_member_id` is `NOT NULL` |
| A tainted session cannot be edited back to clean | Trigger on `agent_sessions` |
| A child delegation cannot exceed its parent | Trigger on `delegations` |
| SaaS, BYOC, and air-gap are different boots, not a comment | Validators in `app/config.py` |
| The harness list in the console is the harness list in the database | Unit test comparing the enum to both check constraints |

## What is still open

Later migrations are written as Alembic revisions. Applying them, and running the SQL invariant file, requires PostgreSQL. On a machine without Docker those tests skip. The README's quick start is the path that applies them.

Discovery of unregistered agents, and ingest of shell, HTTP, and file-read actions into the ledger, are specified and not yet the source of the numbers on the home page. The home page says so. A zero on that page would be a false measurement.

## How to describe it

A short form that matches the tree:

> Personal research prototype of a control and observation plane for multi-step AI agents. Separates durable execution metadata (PostgreSQL), high-volume traces (ClickHouse), ephemeral propagation (Redis), and protected content. Studies how execution traces, evaluation signals, policy evidence, and workload routing stay tenant-isolated across SaaS, customer-cloud, and air-gapped deployments. FastAPI, Go, PostgreSQL, ClickHouse, Redis, OpenTelemetry.

Three bullets, if a résumé needs them:

- Built a multi-service control plane that keeps authorization and evidence in PostgreSQL, analytical traces in ClickHouse, and queues in Redis, so a lost cache cannot rewrite the record of what an agent did.
- Defined a content-free action ledger: append-only, partitioned, graded by how strongly the platform could have intervened, and constrained to a closed harness vocabulary (Cursor, Claude Code, Copilot, Codex, Gemini CLI, LangGraph, SDK, CI).
- Specified and prototyped three deployment boundaries — operator SaaS, customer-controlled cloud, and air-gapped — with boot-time checks that reject telemetry or multi-tenancy in an isolated install, and with OIDC left as deployment configuration rather than a baked-in directory.
