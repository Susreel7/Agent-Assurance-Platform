# Evaluate service

Independently deployable datasets, experiments, evaluators, online scoring rules,
annotation queues, and release gates. Owns PostgreSQL schema `evaluate`.

## Entrypoints

- `evaluate-api` — HTTP API (port 8096 by default)
- `evaluate-worker` — durable job processor; Redis is wake-up only

## Configuration

All settings use the `EVALUATE_` prefix. See `evaluate/config.py`.

## Migrations

Hand-written SQL in `evaluate/migrations/`. Applied on startup when
`EVALUATE_RUN_MIGRATIONS_ON_STARTUP=true`.

## Tests

```bash
cd services/evaluate
pip install -e ".[dev]"
ruff check evaluate tests
mypy evaluate
pytest
```

Set `EVALUATE_DATABASE_URL` or install testcontainers for integration tests.
