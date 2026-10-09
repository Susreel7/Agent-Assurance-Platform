.DEFAULT_GOAL := help
SHELL := /bin/sh
COMPOSE := docker compose
BYOC := docker compose -f docker-compose.yml -f docker-compose.byoc.yml
VERSION ?= 0.1.0

.PHONY: help
help: ## show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-18s\033[0m %s\n",$$1,$$2}'

# ---------------------------------------------------------------- development

.PHONY: bootstrap
bootstrap: ## one-time: generate the local signing key and dev license
	@mkdir -p secrets/byoc
	@test -f secrets/signing.pem || ( \
	  openssl ecparam -name prime256v1 -genkey -noout -out secrets/signing.pem && \
	  chmod 600 secrets/signing.pem && \
	  echo "generated secrets/signing.pem" )
	@test -f secrets/router-config-pub.pem || ( \
	  openssl ec -in secrets/signing.pem -pubout -out secrets/router-config-pub.pem && \
	  echo "generated secrets/router-config-pub.pem for gateway snapshot verification" )
	@test -f secrets/byoc/license-key.pem || ( \
	  openssl ecparam -name prime256v1 -genkey -noout -out secrets/byoc/license-key.pem && \
	  openssl ec -in secrets/byoc/license-key.pem -pubout -out secrets/byoc/license-pub.pem && \
	  echo "generated local license keypair" )
	@python tools/issue_license.py \
	  --key secrets/byoc/license-key.pem \
	  --out secrets/byoc/license.aap \
	  --licensee "Local Development" --mode byoc --days 365 --max-agents 100 \
	  --modules router,observe,prompt,evaluate
	@test -f .env || ( cp .env.example .env && echo "created .env from .env.example" )

.PHONY: up
up: bootstrap ## full stack, seeded — must complete in under two minutes
	$(COMPOSE) up -d --build
	@echo ""
	@echo "  console   http://localhost:5173"
	@echo "  api docs  http://localhost:8000/docs"
	@echo "  readiness http://localhost:8000/readyz"
	@echo ""

.PHONY: down
down: ## stop, keep volumes
	$(COMPOSE) down

.PHONY: reset
reset: ## destroy and rebuild from scratch — the demo reset
	$(COMPOSE) down -v
	$(MAKE) up

.PHONY: logs
logs: ## tail api and worker
	$(COMPOSE) logs -f api worker

.PHONY: shell
shell: ## psql into the database
	$(COMPOSE) exec postgres psql -U aap -d aap

.PHONY: byoc-up
byoc-up: bootstrap ## bring the stack up in BYOC mode against local MinIO
	$(BYOC) up -d --build
	@echo "BYOC mode: single-tenant, offline license, S3 object store via MinIO"
	@echo "  minio console  http://localhost:9001"

.PHONY: byoc-down
byoc-down:
	$(BYOC) down

# ---------------------------------------------------------------- database

.PHONY: migrate
migrate: ## apply migrations
	$(COMPOSE) run --rm migrate

.PHONY: migration
migration: ## scaffold an empty revision (edit it by hand — see AGENTS.md rule 7)
	@test -n "$(NAME)" || ( echo "usage: make migration NAME=short_description"; exit 1 )
	$(COMPOSE) run --rm migrate alembic revision -m "$(NAME)"

.PHONY: seed
seed: ## regenerate the synthetic fleet
	$(COMPOSE) run --rm seed

# ---------------------------------------------------------------- quality

.PHONY: test
test: ## unit, integration and golden-file tests
	$(COMPOSE) run --rm api pytest -q --cov=app --cov-report=term-missing --cov-fail-under=70

.PHONY: test-invariants
test-invariants: ## only the load-bearing property tests
	$(COMPOSE) run --rm api pytest -q -m invariant

.PHONY: lint
lint:
	$(COMPOSE) run --rm api sh -c "ruff check . && ruff format --check ."

.PHONY: fmt
fmt:
	$(COMPOSE) run --rm api ruff format .

.PHONY: typecheck
typecheck:
	$(COMPOSE) run --rm api mypy app

.PHONY: check
check: lint typecheck test check-contracts ## everything CI runs

.PHONY: smoke
smoke: ## end-to-end check of both demo flows against a fresh stack
	$(MAKE) reset
	$(COMPOSE) run --rm api python -m tests.smoke

# ---------------------------------------------------------------- contracts

.PHONY: openapi
openapi: ## regenerate the OpenAPI document
	$(COMPOSE) run --rm api python -m app.export_openapi > services/web/openapi.json

.PHONY: client
client: openapi ## regenerate the typed frontend client from the contract
	cd services/web && npx openapi-typescript openapi.json -o src/api/schema.d.ts

.PHONY: check-contracts
check-contracts: ## regenerate API in memory, compare the snapshot, then build the console
	$(COMPOSE) run --rm -v ./services/web:/contracts:ro api \
	  python -m app.export_openapi --check /contracts/openapi.json
	$(COMPOSE) run --rm --no-deps web npm run build

.PHONY: validate-spec
validate-spec: ## validate every example descriptor against the AAP schema
	$(COMPOSE) run --rm api python -m packages.aap_cli.validate \
	  --schema packages/aap-spec/schema/aap-0.1.schema.json \
	  packages/aap-spec/examples/*.json

# ---------------------------------------------------------------- release

.PHONY: images
images: ## build per-cloud image variants
	docker build --build-arg EXTRAS=aws   -t aap-api:$(VERSION)-aws    services/api
	docker build --build-arg EXTRAS=azure -t aap-api:$(VERSION)-azure  services/api
	docker build --build-arg EXTRAS=gcp   -t aap-api:$(VERSION)-gcp    services/api
	docker build --build-arg EXTRAS=none  -t aap-api:$(VERSION)-airgap services/api
	docker build -t aap-collector:$(VERSION) services/collector
	docker build -t aap-web:$(VERSION)       services/web

.PHONY: airgap
airgap: images ## offline bundle: saved images, signed manifest, chart, checksums
	./deploy/airgap/build-bundle.sh $(VERSION)

.PHONY: helm-lint
helm-lint:
	helm lint deploy/helm/agent-assurance -f deploy/helm/agent-assurance/values.yaml
	helm lint deploy/helm/agent-assurance -f deploy/helm/agent-assurance/values-byoc-aws.yaml
