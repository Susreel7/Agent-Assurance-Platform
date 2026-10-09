# Local Agent Observability Development

## Start the platform

```text
docker compose up -d --build
docker compose ps
```

Bootstrap a local project/workload credential using the seeded organization ID:

```text
python tools/bootstrap_runtime.py --org-id <organization-uuid>
```

The bootstrap writes runtime IDs and the workload bearer to the git-ignored `.env`.
Do not paste or commit the credential.

## Generate the reference execution

```text
python scripts/demo_foss_remediation.py --configure-full-capture
```

The script emits a deterministic production-shaped graph for a FOSS Remediation Agent,
including LangGraph nodes, LLM generations, retrieval, scanner/tool operations, Cursor
SDK work, failed and successful test attempts, retry, approval, MCP, A2A, evaluation,
prompt/output payloads, tokens, cost, and source-control context. It waits for the
execution projection and prints the direct console URL.

Pass `--run-key <key>` to reproduce IDs and test ingest idempotency. Use a new key to
create a new execution.

## Verification

Open the printed URL and verify graph/tree/timeline views, node selection/deep links,
inspector-specific fields, failed/retry highlighting, protected content expansion,
events, session grouping, and cross-agent relationships. Use the Analytics page for
aggregates and sampling policy.

Run focused tests from each service directory or use the repository's normal CI
commands. Migration status is available in `observe.schema_migrations`; an unapplied SQL
file is not considered applied.
