# Docker Development

Run commands from the repository root.

## Standard commands

```text
# Start / start without rebuild
docker compose up -d --build
docker compose up -d

# Stop / restart
docker compose stop
docker compose restart
docker compose restart <service>

# Remove containers / also remove data
docker compose down
docker compose down -v

# Rebuild
docker compose down
docker compose build --no-cache
docker compose up -d

# Full clean rebuild (destructive)
docker compose down -v --remove-orphans
docker system prune -f
docker compose build --no-cache
docker compose up -d

# Inspect
docker compose ps
docker compose logs -f
docker compose logs -f <service>
docker compose exec <service> sh
```

Apply Observe migrations explicitly when needed:

```text
docker compose exec -T observe-query python -c "from observe.config import get_settings; from observe.migrations.runner import apply_migrations; apply_migrations(get_settings().database_url)"
```

## Convenience scripts

Unix/macOS:

```text
scripts/dev-up.sh
scripts/dev-down.sh
scripts/dev-rebuild.sh
scripts/dev-reset.sh
scripts/logs.sh [service]
scripts/status.sh
```

Windows PowerShell:

```text
.\scripts\dev-up.ps1
.\scripts\dev-down.ps1
.\scripts\dev-rebuild.ps1
.\scripts\dev-reset.ps1
.\scripts\logs.ps1 [service]
.\scripts\status.ps1
```

Reset scripts delete volumes and run Docker system pruning. Use them only when local
data loss is intended.

For the customer-hosted/air-gap profile:

```text
docker compose -f docker-compose.yml -f docker-compose.byoc.yml up -d --build
```

That overlay uses local MinIO, offline licensing, disables product telemetry/update
checks, enables Observe air-gap validation, and places services on an internal network.
