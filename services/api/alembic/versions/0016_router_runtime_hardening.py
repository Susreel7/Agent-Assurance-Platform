"""Harden router snapshots, route identity, and per-credential limits.

Revision ID: 0016_router_runtime_hardening
Revises: 0015_router_runtime
Create Date: 2026-09-15
"""

from __future__ import annotations

from alembic import op

revision = "0016_router_runtime_hardening"
down_revision = "0015_router_runtime"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE projects
            ADD COLUMN trace_capture_mode text NOT NULL DEFAULT 'digest',
            ADD COLUMN payload_retention_days integer NOT NULL DEFAULT 30,
            ADD COLUMN payload_encryption_key_ref text,
            ADD CONSTRAINT projects_trace_capture_mode CHECK (
                trace_capture_mode IN ('none', 'digest', 'redacted', 'full')
            ),
            ADD CONSTRAINT projects_payload_retention_range CHECK (
                payload_retention_days >= 1 AND payload_retention_days <= 3650
            ),
            ADD CONSTRAINT projects_payload_encryption_key_ref_len CHECK (
                payload_encryption_key_ref IS NULL
                OR length(payload_encryption_key_ref) <= 1024
            ),
            ADD CONSTRAINT projects_full_capture_has_key CHECK (
                trace_capture_mode <> 'full' OR payload_encryption_key_ref IS NOT NULL
            );
    """)

    op.execute("""
        ALTER TABLE workload_credentials
            ADD COLUMN rpm integer,
            ADD COLUMN tpm integer,
            ADD COLUMN max_concurrency integer,
            ADD COLUMN daily_budget_micros bigint,
            ADD CONSTRAINT workload_credentials_rpm_positive CHECK (rpm IS NULL OR rpm >= 1),
            ADD CONSTRAINT workload_credentials_tpm_positive CHECK (tpm IS NULL OR tpm >= 1),
            ADD CONSTRAINT workload_credentials_concurrency_positive CHECK (
                max_concurrency IS NULL OR max_concurrency >= 1
            ),
            ADD CONSTRAINT workload_credentials_budget_positive CHECK (
                daily_budget_micros IS NULL OR daily_budget_micros >= 1
            );
    """)

    op.execute("""
        CREATE UNIQUE INDEX agent_versions_org_agent_id_id_idx
            ON agent_versions (org_id, agent_id, id);

        ALTER TABLE model_routes
            DROP CONSTRAINT model_routes_agent_version_same_org_fkey,
            ADD CONSTRAINT model_routes_agent_version_same_agent_fkey
                FOREIGN KEY (org_id, agent_id, agent_version_id)
                REFERENCES agent_versions (org_id, agent_id, id)
                ON DELETE SET NULL (agent_version_id);

        ALTER TABLE model_route_targets
            ADD CONSTRAINT model_route_targets_route_position_unique
                UNIQUE (org_id, route_id, position);
    """)

    op.execute("""
        CREATE TABLE router_signing_keys (
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            key_id text NOT NULL,
            algorithm text NOT NULL DEFAULT 'ES256',
            public_key_pem text NOT NULL,
            first_seen_at timestamptz NOT NULL DEFAULT now(),
            last_used_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (org_id, key_id),
            CONSTRAINT router_signing_keys_key_id_len CHECK (
                length(key_id) >= 1 AND length(key_id) <= 1024
            ),
            CONSTRAINT router_signing_keys_algorithm CHECK (algorithm = 'ES256'),
            CONSTRAINT router_signing_keys_public_key_pem_format CHECK (
                public_key_pem LIKE '-----BEGIN PUBLIC KEY-----%'
            )
        );

        ALTER TABLE router_signing_keys ENABLE ROW LEVEL SECURITY;
        ALTER TABLE router_signing_keys FORCE ROW LEVEL SECURITY;
        CREATE POLICY router_signing_keys_tenant_isolation ON router_signing_keys
            USING (current_org_matches(org_id))
            WITH CHECK (current_org_matches(org_id));

        CREATE OR REPLACE FUNCTION protect_router_signing_key()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'router signing keys referenced by snapshots are immutable';
            END IF;
            IF NEW.org_id IS DISTINCT FROM OLD.org_id
                OR NEW.key_id IS DISTINCT FROM OLD.key_id
                OR NEW.algorithm IS DISTINCT FROM OLD.algorithm
                OR NEW.public_key_pem IS DISTINCT FROM OLD.public_key_pem
                OR NEW.first_seen_at IS DISTINCT FROM OLD.first_seen_at
            THEN
                RAISE EXCEPTION 'router signing key material is immutable';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER router_signing_keys_immutable
            BEFORE UPDATE OR DELETE ON router_signing_keys
            FOR EACH ROW EXECUTE FUNCTION protect_router_signing_key();
    """)

    op.execute("""
        ALTER TABLE router_config_snapshots
            DROP CONSTRAINT router_config_snapshots_key_id_len,
            ADD COLUMN config_digest text;

        UPDATE router_config_snapshots
        SET config_digest = 'sha256:' || encode(digest(config_bytes, 'sha256'), 'hex');

        ALTER TABLE router_config_snapshots
            ALTER COLUMN config_digest SET NOT NULL,
            ADD CONSTRAINT router_config_snapshots_config_digest_format CHECK (
                config_digest ~ '^sha256:[0-9a-f]{64}$'
            ),
            ADD CONSTRAINT router_config_snapshots_key_id_len CHECK (
                length(key_id) >= 1 AND length(key_id) <= 1024
            ),
            ADD CONSTRAINT router_config_snapshots_signing_key_fkey
                FOREIGN KEY (org_id, key_id)
                REFERENCES router_signing_keys (org_id, key_id)
                NOT VALID;

        CREATE OR REPLACE FUNCTION forbid_router_snapshot_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'router_config_snapshots are immutable';
            END IF;
            IF NEW.config_bytes IS DISTINCT FROM OLD.config_bytes
                OR NEW.config_digest IS DISTINCT FROM OLD.config_digest
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
    """)


def downgrade() -> None:
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

        ALTER TABLE router_config_snapshots
            DROP CONSTRAINT router_config_snapshots_config_digest_format,
            DROP CONSTRAINT router_config_snapshots_signing_key_fkey,
            DROP CONSTRAINT router_config_snapshots_key_id_len,
            DROP COLUMN config_digest,
            ADD CONSTRAINT router_config_snapshots_key_id_len CHECK (
                length(key_id) >= 1 AND length(key_id) <= 128
            );
    """)

    op.execute("""
        DROP TRIGGER router_signing_keys_immutable ON router_signing_keys;
        DROP FUNCTION protect_router_signing_key();
        DROP TABLE router_signing_keys;
    """)

    op.execute("""
        ALTER TABLE model_route_targets
            DROP CONSTRAINT model_route_targets_route_position_unique;

        ALTER TABLE model_routes
            DROP CONSTRAINT model_routes_agent_version_same_agent_fkey,
            ADD CONSTRAINT model_routes_agent_version_same_org_fkey
                FOREIGN KEY (org_id, agent_version_id)
                REFERENCES agent_versions (org_id, id)
                ON DELETE SET NULL (agent_version_id);

        DROP INDEX agent_versions_org_agent_id_id_idx;
    """)

    op.execute("""
        ALTER TABLE workload_credentials
            DROP COLUMN daily_budget_micros,
            DROP COLUMN max_concurrency,
            DROP COLUMN tpm,
            DROP COLUMN rpm;
    """)

    op.execute("""
        ALTER TABLE projects
            DROP COLUMN payload_encryption_key_ref,
            DROP COLUMN payload_retention_days,
            DROP COLUMN trace_capture_mode;
    """)
