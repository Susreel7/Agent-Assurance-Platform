"""Tenant projects and revocable workload credentials for machine callers.

Closes the machine-identity gap for ingest and gateway reporters: opaque high-entropy
keys verified by SHA-256 digest only, scoped to org, project, optional agent, environment,
entitled modules, scopes and allowed model patterns.

Also adds row-level security for ``obligation_templates``, which migration 0013 created
without policies.

Hand-written per AGENTS.md rule 7.

Revision ID: 0014_workload_identity
Revises: 0013_probe_assertions
Create Date: 2026-09-15
"""

from __future__ import annotations

from alembic import op

revision = "0014_workload_identity"
down_revision = "0013_probe_assertions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE obligation_templates ENABLE ROW LEVEL SECURITY;
        ALTER TABLE obligation_templates FORCE ROW LEVEL SECURITY;
        CREATE POLICY obligation_templates_reference_read ON obligation_templates
            FOR SELECT
            USING (org_id IS NULL OR current_org_matches(org_id));
        CREATE POLICY obligation_templates_tenant_write ON obligation_templates
            FOR ALL
            USING (current_org_matches(org_id))
            WITH CHECK (current_org_matches(org_id));
    """)

    op.execute("""
        CREATE TABLE projects (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            slug text NOT NULL,
            name text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT projects_slug_present CHECK (slug <> ''),
            CONSTRAINT projects_name_present CHECK (name <> ''),
            CONSTRAINT projects_slug_len CHECK (length(slug) <= 128),
            CONSTRAINT projects_name_len CHECK (length(name) <= 256),
            CONSTRAINT projects_org_id_id_key UNIQUE (org_id, id)
        );

        CREATE UNIQUE INDEX projects_org_slug_idx ON projects (org_id, lower(slug));
        CREATE INDEX projects_org_idx ON projects (org_id);
        CREATE UNIQUE INDEX agents_org_id_id_idx ON agents (org_id, id);
    """)

    op.execute("""
        CREATE TABLE workload_credentials (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            project_id uuid NOT NULL,
            agent_id uuid,
            name text NOT NULL,
            environment lifecycle_state NOT NULL,
            modules text[] NOT NULL DEFAULT '{}'::text[],
            scopes text[] NOT NULL DEFAULT '{}'::text[],
            allowed_model_patterns text[] NOT NULL DEFAULT '{}'::text[],
            expires_at timestamptz,
            revoked_at timestamptz,
            active_generation_id uuid,
            last_used_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            created_by text NOT NULL,
            CONSTRAINT workload_credentials_name_present CHECK (name <> ''),
            CONSTRAINT workload_credentials_name_len CHECK (length(name) <= 128),
            CONSTRAINT workload_credentials_modules_valid CHECK (
                modules <@ ARRAY['router', 'observe', 'prompt', 'evaluate']::text[]
            ),
            CONSTRAINT workload_credentials_modules_cardinality CHECK (
                cardinality(modules) >= 1 AND cardinality(modules) <= 4
            ),
            CONSTRAINT workload_credentials_scopes_cardinality CHECK (
                cardinality(scopes) >= 1 AND cardinality(scopes) <= 32
            ),
            CONSTRAINT workload_credentials_patterns_cardinality CHECK (
                cardinality(allowed_model_patterns) <= 64
            ),
            CONSTRAINT workload_credentials_scopes_present CHECK (
                array_position(scopes, '') IS NULL
            ),
            CONSTRAINT workload_credentials_scopes_total_len CHECK (
                length(array_to_string(scopes, '')) <= 4096
            ),
            CONSTRAINT workload_credentials_patterns_total_len CHECK (
                length(array_to_string(allowed_model_patterns, '')) <= 16384
            ),
            CONSTRAINT workload_credentials_created_by_len CHECK (
                created_by <> '' AND length(created_by) <= 512
            ),
            CONSTRAINT workload_credentials_org_id_id_key UNIQUE (org_id, id),
            CONSTRAINT workload_credentials_project_same_org_fkey
                FOREIGN KEY (org_id, project_id)
                REFERENCES projects (org_id, id)
                ON DELETE CASCADE,
            CONSTRAINT workload_credentials_agent_same_org_fkey
                FOREIGN KEY (org_id, agent_id)
                REFERENCES agents (org_id, id)
                ON DELETE SET NULL (agent_id)
        );

        CREATE INDEX workload_credentials_org_idx ON workload_credentials (org_id);
        CREATE INDEX workload_credentials_project_idx
            ON workload_credentials (org_id, project_id);
        CREATE INDEX workload_credentials_agent_idx
            ON workload_credentials (org_id, agent_id)
            WHERE agent_id IS NOT NULL;
    """)

    op.execute("""
        CREATE TABLE workload_credential_generations (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            credential_id uuid NOT NULL,
            generation_number integer NOT NULL,
            secret_digest bytea NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            revoked_at timestamptz,
            CONSTRAINT workload_credential_generations_digest_len
                CHECK (octet_length(secret_digest) = 32),
            CONSTRAINT workload_credential_generations_number_positive
                CHECK (generation_number >= 1),
            CONSTRAINT workload_credential_generations_credential_same_org_fkey
                FOREIGN KEY (org_id, credential_id)
                REFERENCES workload_credentials (org_id, id)
                ON DELETE CASCADE,
            CONSTRAINT workload_credential_generations_org_credential_id_key
                UNIQUE (org_id, credential_id, id)
        );

        CREATE UNIQUE INDEX workload_credential_generations_credential_number_idx
            ON workload_credential_generations (credential_id, generation_number);
        CREATE UNIQUE INDEX workload_credential_generations_credential_id_idx
            ON workload_credential_generations (credential_id, id);
        CREATE INDEX workload_credential_generations_org_idx
            ON workload_credential_generations (org_id);
        CREATE INDEX workload_credential_generations_credential_idx
            ON workload_credential_generations (org_id, credential_id);
    """)

    op.execute("""
        ALTER TABLE workload_credentials
            ADD CONSTRAINT workload_credentials_active_generation_fkey
            FOREIGN KEY (org_id, id, active_generation_id)
            REFERENCES workload_credential_generations (org_id, credential_id, id)
            ON DELETE RESTRICT
            DEFERRABLE INITIALLY DEFERRED;
    """)

    op.execute("""
        ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
        ALTER TABLE projects FORCE ROW LEVEL SECURITY;
        CREATE POLICY projects_tenant_isolation ON projects
            USING (current_org_matches(org_id))
            WITH CHECK (current_org_matches(org_id));

        ALTER TABLE workload_credentials ENABLE ROW LEVEL SECURITY;
        ALTER TABLE workload_credentials FORCE ROW LEVEL SECURITY;
        CREATE POLICY workload_credentials_tenant_isolation ON workload_credentials
            USING (current_org_matches(org_id))
            WITH CHECK (current_org_matches(org_id));

        ALTER TABLE workload_credential_generations ENABLE ROW LEVEL SECURITY;
        ALTER TABLE workload_credential_generations FORCE ROW LEVEL SECURITY;
        CREATE POLICY workload_credential_generations_tenant_isolation
            ON workload_credential_generations
            USING (current_org_matches(org_id))
            WITH CHECK (current_org_matches(org_id));
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS workload_credential_generations CASCADE;
        DROP TABLE IF EXISTS workload_credentials CASCADE;
        DROP TABLE IF EXISTS projects CASCADE;
        DROP INDEX IF EXISTS agents_org_id_id_idx;

        DROP POLICY IF EXISTS obligation_templates_tenant_write ON obligation_templates;
        DROP POLICY IF EXISTS obligation_templates_reference_read ON obligation_templates;
        ALTER TABLE obligation_templates DISABLE ROW LEVEL SECURITY;
    """)
