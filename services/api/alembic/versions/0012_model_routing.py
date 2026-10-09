"""Model catalogue, gateway configuration emission, and routing audit.

We are the policy authority upstream of an AI gateway (LiteLLM is the first supported
target): we compile an agent's obligations into gateway configuration, expose a
pre-dispatch decision API, and ingest what the gateway actually did. We do not run a
proxy in this repository — that stays in the customer's network.

Revision ID: 0012_model_routing
Revises: 0011_change_review
Create Date: 2026-09-15
"""

from __future__ import annotations

from alembic import op

revision = "0012_model_routing"
down_revision = "0011_change_review"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TYPE model_hosting_mode AS ENUM (
            'vendor_api',
            'cloud_managed',
            'self_hosted'
        );

        CREATE TYPE model_data_handling_terms AS ENUM (
            'zero_retention',
            '30_day',
            'provider_default',
            'unknown'
        );

        CREATE TYPE model_classification_state AS ENUM (
            'classified',
            'unclassified',
            'deprecated'
        );

        CREATE TYPE model_routing_enforcement_level AS ENUM (
            'advisory',
            'overrideable',
            'blocking'
        );
    """)

    # org_id IS NULL rows are shipped reference data; tenants may override with org_id set.
    op.execute("""
        CREATE TABLE model_catalog_entries (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid REFERENCES organizations(id) ON DELETE CASCADE,
            provider text NOT NULL,
            model_id text NOT NULL,
            display_name text,
            hosting_mode model_hosting_mode NOT NULL,
            primary_region text NOT NULL,
            jurisdiction text NOT NULL,
            cross_border_ok boolean NOT NULL DEFAULT false,
            data_handling_terms model_data_handling_terms NOT NULL DEFAULT 'unknown',
            classification_state model_classification_state NOT NULL DEFAULT 'classified',
            source text NOT NULL,
            source_url text,
            valid_from date NOT NULL DEFAULT CURRENT_DATE,
            valid_to date,
            digest text NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT model_catalog_entries_source_url_len
                CHECK (source_url IS NULL OR length(source_url) <= 512)
        );

        CREATE UNIQUE INDEX model_catalog_entries_identity_idx ON model_catalog_entries (
            COALESCE(org_id, '00000000-0000-0000-0000-000000000000'::uuid),
            lower(provider),
            lower(model_id),
            valid_from
        );

        CREATE INDEX model_catalog_entries_org_idx
            ON model_catalog_entries (org_id)
            WHERE org_id IS NOT NULL;

        CREATE INDEX model_catalog_entries_unclassified_idx
            ON model_catalog_entries (classification_state)
            WHERE classification_state = 'unclassified';
    """)

    op.execute("""
        CREATE TABLE model_catalog_aliases (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid REFERENCES organizations(id) ON DELETE CASCADE,
            alias text NOT NULL,
            catalog_entry_id uuid NOT NULL REFERENCES model_catalog_entries(id) ON DELETE CASCADE,
            created_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE UNIQUE INDEX model_catalog_aliases_identity_idx ON model_catalog_aliases (
            COALESCE(org_id, '00000000-0000-0000-0000-000000000000'::uuid),
            lower(alias)
        );
    """)

    op.execute("""
        CREATE TABLE gateway_request_logs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            agent_id uuid REFERENCES agents(id) ON DELETE SET NULL,
            agent_version_id uuid REFERENCES agent_versions(id) ON DELETE SET NULL,
            engagement_id uuid REFERENCES engagements(id) ON DELETE SET NULL,
            model_provider text NOT NULL,
            model_id text NOT NULL,
            region_used text,
            virtual_key_ref text,
            outcome text NOT NULL,
            policy_decision_id uuid REFERENCES policy_decisions(id) ON DELETE SET NULL,
            log_digest text NOT NULL,
            logged_at timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT gateway_request_logs_digest_len CHECK (length(log_digest) <= 128)
        );

        CREATE INDEX gateway_request_logs_org_logged_idx
            ON gateway_request_logs (org_id, logged_at DESC);

        CREATE UNIQUE INDEX gateway_request_logs_dedup_idx
            ON gateway_request_logs (org_id, log_digest);
    """)

    op.execute("""
        ALTER TABLE model_catalog_entries ENABLE ROW LEVEL SECURITY;
        ALTER TABLE model_catalog_aliases ENABLE ROW LEVEL SECURITY;
        ALTER TABLE gateway_request_logs ENABLE ROW LEVEL SECURITY;

        CREATE POLICY model_catalog_entries_tenant ON model_catalog_entries
            FOR ALL
            USING (org_id IS NULL OR current_org_matches(org_id))
            WITH CHECK (org_id IS NULL OR current_org_matches(org_id));

        CREATE POLICY model_catalog_aliases_tenant ON model_catalog_aliases
            FOR ALL
            USING (org_id IS NULL OR current_org_matches(org_id))
            WITH CHECK (org_id IS NULL OR current_org_matches(org_id));

        CREATE POLICY gateway_request_logs_tenant ON gateway_request_logs
            FOR ALL
            USING (current_org_matches(org_id))
            WITH CHECK (current_org_matches(org_id));
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS gateway_request_logs CASCADE")
    op.execute("DROP TABLE IF EXISTS model_catalog_aliases CASCADE")
    op.execute("DROP TABLE IF EXISTS model_catalog_entries CASCADE")
    op.execute("DROP TYPE IF EXISTS model_routing_enforcement_level")
    op.execute("DROP TYPE IF EXISTS model_classification_state")
    op.execute("DROP TYPE IF EXISTS model_data_handling_terms")
    op.execute("DROP TYPE IF EXISTS model_hosting_mode")
