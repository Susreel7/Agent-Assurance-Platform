"""Router control-plane runtime — deployments, routes, signed config snapshots.

Project-scoped model deployments and routes compile into immutable, signed router
configuration bytes for the Go gateway. Workload credential generations (router module,
active and unrevoked) embed as bindings with sha256 secret digests only.

Hand-written per AGENTS.md rule 7.

Revision ID: 0015_router_runtime
Revises: 0014_workload_identity
Create Date: 2026-09-15
"""

from __future__ import annotations

from alembic import op

revision = "0015_router_runtime"
down_revision = "0014_workload_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS agent_versions_org_id_id_idx
            ON agent_versions (org_id, id);
    """)

    op.execute("""
        CREATE TYPE router_provider AS ENUM (
            'openai',
            'openai_compatible',
            'azure_openai',
            'anthropic',
            'bedrock',
            'gemini',
            'vertex'
        );

        CREATE TYPE router_route_strategy AS ENUM (
            'priority',
            'weighted',
            'least_busy',
            'latency',
            'lowest_cost'
        );

        CREATE TYPE router_snapshot_status AS ENUM (
            'active',
            'superseded',
            'expired'
        );
    """)

    op.execute("""
        CREATE TABLE model_deployments (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id uuid NOT NULL,
            name text NOT NULL,
            provider router_provider NOT NULL,
            model text NOT NULL,
            endpoint text NOT NULL,
            credential_ref text NOT NULL,
            region text NOT NULL,
            jurisdiction text NOT NULL,
            capabilities text[] NOT NULL,
            priority integer NOT NULL DEFAULT 100,
            weight integer NOT NULL DEFAULT 100,
            rpm integer,
            tpm integer,
            timeout_ms integer NOT NULL DEFAULT 60000,
            max_retries integer NOT NULL DEFAULT 2,
            input_price_micros_per_m bigint NOT NULL DEFAULT 0,
            output_price_micros_per_m bigint NOT NULL DEFAULT 0,
            max_concurrency integer,
            daily_budget_micros bigint,
            cooldown_failure_threshold integer,
            cooldown_initial_ms integer,
            cooldown_max_ms integer,
            data_classes text[],
            disabled_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            created_by text NOT NULL,
            CONSTRAINT model_deployments_name_present CHECK (name <> ''),
            CONSTRAINT model_deployments_name_len CHECK (length(name) <= 128),
            CONSTRAINT model_deployments_model_len CHECK (
                length(model) >= 1 AND length(model) <= 256
            ),
            CONSTRAINT model_deployments_endpoint_len CHECK (
                length(endpoint) >= 1 AND length(endpoint) <= 2048
            ),
            CONSTRAINT model_deployments_credential_ref_len CHECK (
                length(credential_ref) >= 1 AND length(credential_ref) <= 512
            ),
            CONSTRAINT model_deployments_region_len CHECK (
                length(region) >= 1 AND length(region) <= 64
            ),
            CONSTRAINT model_deployments_jurisdiction_len CHECK (
                length(jurisdiction) >= 1 AND length(jurisdiction) <= 16
            ),
            CONSTRAINT model_deployments_capabilities_valid CHECK (
                capabilities <@ ARRAY[
                    'chat', 'responses', 'embeddings', 'streaming', 'responses_stream',
                    'tools', 'json_schema', 'vision', 'reasoning'
                ]::text[]
                AND cardinality(capabilities) >= 1
            ),
            CONSTRAINT model_deployments_priority_range CHECK (
                priority >= 0 AND priority <= 10000
            ),
            CONSTRAINT model_deployments_weight_range CHECK (
                weight >= 1 AND weight <= 10000
            ),
            CONSTRAINT model_deployments_timeout_range CHECK (
                timeout_ms >= 100 AND timeout_ms <= 3600000
            ),
            CONSTRAINT model_deployments_max_retries_range CHECK (
                max_retries >= 0 AND max_retries <= 10
            ),
            CONSTRAINT model_deployments_prices_nonneg CHECK (
                input_price_micros_per_m >= 0 AND output_price_micros_per_m >= 0
            ),
            CONSTRAINT model_deployments_cooldown_consistent CHECK (
                (cooldown_failure_threshold IS NULL
                    AND cooldown_initial_ms IS NULL
                    AND cooldown_max_ms IS NULL)
                OR (
                    cooldown_failure_threshold IS NOT NULL
                    AND cooldown_initial_ms IS NOT NULL
                    AND cooldown_max_ms IS NOT NULL
                    AND cooldown_failure_threshold >= 1
                    AND cooldown_failure_threshold <= 100
                    AND cooldown_initial_ms >= 1
                    AND cooldown_initial_ms <= 3600000
                    AND cooldown_max_ms >= 1
                    AND cooldown_max_ms <= 86400000
                )
            ),
            CONSTRAINT model_deployments_created_by_len CHECK (
                created_by <> '' AND length(created_by) <= 512
            ),
            CONSTRAINT model_deployments_org_id_id_key UNIQUE (org_id, id),
            CONSTRAINT model_deployments_org_project_id_key UNIQUE (org_id, project_id, id),
            CONSTRAINT model_deployments_project_same_org_fkey
                FOREIGN KEY (org_id, project_id)
                REFERENCES projects (org_id, id)
                ON DELETE CASCADE
        );

        CREATE INDEX model_deployments_org_project_idx
            ON model_deployments (org_id, project_id);
        CREATE INDEX model_deployments_enabled_idx
            ON model_deployments (org_id, project_id)
            WHERE disabled_at IS NULL;
    """)

    op.execute("""
        CREATE TABLE model_routes (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id uuid NOT NULL,
            agent_id uuid NOT NULL,
            agent_version_id uuid,
            environment lifecycle_state NOT NULL,
            alias text NOT NULL,
            strategy router_route_strategy NOT NULL DEFAULT 'priority',
            enforcement model_routing_enforcement_level NOT NULL DEFAULT 'advisory',
            permitted_regions text[],
            data_classes text[],
            fallback_before_first_byte boolean NOT NULL DEFAULT true,
            max_attempts integer NOT NULL DEFAULT 3,
            response_cache_enabled boolean NOT NULL DEFAULT false,
            response_cache_ttl_seconds integer,
            disabled_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            created_by text NOT NULL,
            CONSTRAINT model_routes_alias_present CHECK (alias <> ''),
            CONSTRAINT model_routes_alias_len CHECK (length(alias) <= 256),
            CONSTRAINT model_routes_environment_runtime CHECK (
                environment IN ('dev', 'test', 'staging', 'production')
            ),
            CONSTRAINT model_routes_max_attempts_range CHECK (
                max_attempts >= 1 AND max_attempts <= 10
            ),
            CONSTRAINT model_routes_cache_ttl_range CHECK (
                response_cache_ttl_seconds IS NULL
                OR (response_cache_ttl_seconds >= 1
                    AND response_cache_ttl_seconds <= 86400)
            ),
            CONSTRAINT model_routes_created_by_len CHECK (
                created_by <> '' AND length(created_by) <= 512
            ),
            CONSTRAINT model_routes_org_id_id_key UNIQUE (org_id, id),
            CONSTRAINT model_routes_org_project_id_key UNIQUE (org_id, project_id, id),
            CONSTRAINT model_routes_project_same_org_fkey
                FOREIGN KEY (org_id, project_id)
                REFERENCES projects (org_id, id)
                ON DELETE CASCADE,
            CONSTRAINT model_routes_agent_same_org_fkey
                FOREIGN KEY (org_id, agent_id)
                REFERENCES agents (org_id, id)
                ON DELETE CASCADE,
            CONSTRAINT model_routes_agent_version_same_org_fkey
                FOREIGN KEY (org_id, agent_version_id)
                REFERENCES agent_versions (org_id, id)
                ON DELETE SET NULL (agent_version_id),
            CONSTRAINT model_routes_identity_unique UNIQUE (
                org_id, project_id, agent_id, environment, alias
            )
        );

        CREATE INDEX model_routes_org_project_idx ON model_routes (org_id, project_id);
        CREATE INDEX model_routes_agent_idx ON model_routes (org_id, agent_id);
    """)

    op.execute("""
        CREATE TABLE model_route_targets (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id uuid NOT NULL,
            route_id uuid NOT NULL,
            deployment_id uuid NOT NULL,
            position integer NOT NULL,
            disabled_at timestamptz,
            CONSTRAINT model_route_targets_position_positive CHECK (position >= 0),
            CONSTRAINT model_route_targets_org_id_id_key UNIQUE (org_id, id),
            CONSTRAINT model_route_targets_route_deployment_unique
                UNIQUE (org_id, route_id, deployment_id),
            CONSTRAINT model_route_targets_route_same_org_fkey
                FOREIGN KEY (org_id, route_id)
                REFERENCES model_routes (org_id, id)
                ON DELETE CASCADE,
            CONSTRAINT model_route_targets_deployment_same_org_fkey
                FOREIGN KEY (org_id, deployment_id)
                REFERENCES model_deployments (org_id, id)
                ON DELETE CASCADE,
            CONSTRAINT model_route_targets_project_route_fkey
                FOREIGN KEY (org_id, project_id, route_id)
                REFERENCES model_routes (org_id, project_id, id)
                ON DELETE CASCADE,
            CONSTRAINT model_route_targets_project_deployment_fkey
                FOREIGN KEY (org_id, project_id, deployment_id)
                REFERENCES model_deployments (org_id, project_id, id)
                ON DELETE CASCADE
        );

        CREATE INDEX model_route_targets_route_idx
            ON model_route_targets (org_id, route_id, position);
    """)

    op.execute("""
        CREATE TABLE router_config_snapshots (
            id uuid PRIMARY KEY,
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id uuid NOT NULL,
            config_bytes bytea NOT NULL,
            rules_digest text NOT NULL,
            signature text NOT NULL,
            key_id text NOT NULL,
            issued_at timestamptz NOT NULL,
            expires_at timestamptz NOT NULL,
            status router_snapshot_status NOT NULL DEFAULT 'active',
            compiled_by text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT router_config_snapshots_rules_digest_format CHECK (
                rules_digest ~ '^sha256:[0-9a-f]{64}$'
            ),
            CONSTRAINT router_config_snapshots_signature_len CHECK (
                length(signature) >= 16 AND length(signature) <= 1024
            ),
            CONSTRAINT router_config_snapshots_key_id_len CHECK (
                length(key_id) >= 1 AND length(key_id) <= 128
            ),
            CONSTRAINT router_config_snapshots_compiled_by_len CHECK (
                compiled_by <> '' AND length(compiled_by) <= 512
            ),
            CONSTRAINT router_config_snapshots_org_id_id_key UNIQUE (org_id, id),
            CONSTRAINT router_config_snapshots_project_same_org_fkey
                FOREIGN KEY (org_id, project_id)
                REFERENCES projects (org_id, id)
                ON DELETE CASCADE
        );

        CREATE INDEX router_config_snapshots_project_active_idx
            ON router_config_snapshots (org_id, project_id, issued_at DESC)
            WHERE status = 'active';
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION forbid_router_snapshot_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'router_config_snapshots are immutable';
            END IF;
            IF NEW.config_bytes IS DISTINCT FROM OLD.config_bytes
                OR NEW.rules_digest IS DISTINCT FROM OLD.rules_digest
                OR NEW.signature IS DISTINCT FROM OLD.signature
                OR NEW.key_id IS DISTINCT FROM OLD.key_id
                OR NEW.issued_at IS DISTINCT FROM OLD.issued_at
                OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
                OR NEW.compiled_by IS DISTINCT FROM OLD.compiled_by
                OR NEW.id IS DISTINCT FROM OLD.id
                OR NEW.org_id IS DISTINCT FROM OLD.org_id
                OR NEW.project_id IS DISTINCT FROM OLD.project_id
            THEN
                RAISE EXCEPTION 'router_config_snapshots are immutable except status';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER router_config_snapshots_immutable
            BEFORE UPDATE OR DELETE ON router_config_snapshots
            FOR EACH ROW EXECUTE FUNCTION forbid_router_snapshot_mutation();
    """)

    op.execute("""
        ALTER TABLE model_deployments ENABLE ROW LEVEL SECURITY;
        ALTER TABLE model_deployments FORCE ROW LEVEL SECURITY;
        CREATE POLICY model_deployments_tenant_isolation ON model_deployments
            USING (current_org_matches(org_id))
            WITH CHECK (current_org_matches(org_id));

        ALTER TABLE model_routes ENABLE ROW LEVEL SECURITY;
        ALTER TABLE model_routes FORCE ROW LEVEL SECURITY;
        CREATE POLICY model_routes_tenant_isolation ON model_routes
            USING (current_org_matches(org_id))
            WITH CHECK (current_org_matches(org_id));

        ALTER TABLE model_route_targets ENABLE ROW LEVEL SECURITY;
        ALTER TABLE model_route_targets FORCE ROW LEVEL SECURITY;
        CREATE POLICY model_route_targets_tenant_isolation ON model_route_targets
            USING (current_org_matches(org_id))
            WITH CHECK (current_org_matches(org_id));

        ALTER TABLE router_config_snapshots ENABLE ROW LEVEL SECURITY;
        ALTER TABLE router_config_snapshots FORCE ROW LEVEL SECURITY;
        CREATE POLICY router_config_snapshots_tenant_isolation ON router_config_snapshots
            USING (current_org_matches(org_id))
            WITH CHECK (current_org_matches(org_id));
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS agent_versions_org_id_id_idx;

        DROP TRIGGER IF EXISTS router_config_snapshots_immutable ON router_config_snapshots;
        DROP FUNCTION IF EXISTS forbid_router_snapshot_mutation();

        DROP TABLE IF EXISTS router_config_snapshots CASCADE;
        DROP TABLE IF EXISTS model_route_targets CASCADE;
        DROP TABLE IF EXISTS model_routes CASCADE;
        DROP TABLE IF EXISTS model_deployments CASCADE;

        DROP TYPE IF EXISTS router_snapshot_status;
        DROP TYPE IF EXISTS router_route_strategy;
        DROP TYPE IF EXISTS router_provider;
    """)
