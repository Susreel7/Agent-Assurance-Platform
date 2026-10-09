#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")/.."
docker compose down -v --remove-orphans
docker system prune -f
docker compose build --no-cache "$@"
docker compose up -d
