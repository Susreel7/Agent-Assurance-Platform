#!/bin/sh
# Idempotently creates service-owned databases on the shared local Postgres cluster.
set -eu

password="${POSTGRES_PASSWORD:?POSTGRES_PASSWORD must be set}"

for name in observe prompt evaluate; do
  psql \
    --set=ON_ERROR_STOP=1 \
    --set=runtime_name="$name" \
    --set=runtime_password="$password" \
    --username "$POSTGRES_USER" \
    --dbname "$POSTGRES_DB" <<'EOSQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'runtime_name', :'runtime_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'runtime_name')\gexec

SELECT format('ALTER ROLE %I LOGIN PASSWORD %L', :'runtime_name', :'runtime_password')\gexec

SELECT format('CREATE DATABASE %I OWNER %I', :'runtime_name', :'runtime_name')
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = :'runtime_name')\gexec

SELECT format('GRANT ALL PRIVILEGES ON DATABASE %I TO %I', :'runtime_name', :'runtime_name')\gexec
EOSQL
done
