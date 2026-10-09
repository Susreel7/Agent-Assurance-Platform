"""Declared agent composition vs what production actually ran.

Track 1 makes an agent's makeup reviewable: tools, MCP servers, models, skills,
sub-agents, configs, rules (as digests and bounded obligations), memory sources and
guardrails. The descriptor carries the declaration; ``run_steps`` and
``tool_usage_daily`` carry observation. This revision stores reconciliation rows and
normalised rule obligations so Postgres can enforce the same 512-byte bound evidence
uses, without ever storing prompt text.

Hand-written per AGENTS.md rule 7.

Revision ID: 0010_agent_composition
Revises: 0009_run_steps
Create Date: 2026-09-14
"""

from __future__ import annotations

from alembic import op

revision = "0010_agent_composition"
down_revision = "0009_run_steps"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Extend BOM kinds so composition elements participate in the same declaration index
    # operations already uses for tool/MCP reconciliation (D-039).
    op.execute("""
        ALTER TYPE component_kind ADD VALUE IF NOT EXISTS 'skill';
        ALTER TYPE component_kind ADD VALUE IF NOT EXISTS 'config';
        ALTER TYPE component_kind ADD VALUE IF NOT EXISTS 'rule_source';
        ALTER TYPE component_kind ADD VALUE IF NOT EXISTS 'rule_obligation';
        ALTER TYPE component_kind ADD VALUE IF NOT EXISTS 'model_policy';
    """)

    op.execute("""
        CREATE TYPE reconciliation_status AS ENUM (
            'aligned',
            'declared_only',
            'observed_only',
            'conflict'
        );
    """)

    op.execute("""
        CREATE TABLE composition_rule_obligations (
            id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id           uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            agent_version_id uuid NOT NULL REFERENCES agent_versions(id) ON DELETE CASCADE,
            obligation_id    text NOT NULL,
            source_ref       text NOT NULL,
            category         text NOT NULL,
            polarity         text NOT NULL,
            strength         text NOT NULL,
            statement        text NOT NULL,
            digest           text NOT NULL,
            created_at       timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT composition_obligations_unique
                UNIQUE (org_id, agent_version_id, obligation_id),
            CONSTRAINT composition_obligations_statement_bounded CHECK (
                octet_length(statement) <= 512
            ),
            CONSTRAINT composition_obligations_id_nonempty CHECK (
                length(trim(obligation_id)) > 0
            )
        );

        CREATE INDEX composition_obligations_version_idx
            ON composition_rule_obligations (org_id, agent_version_id);
    """)

    op.execute("""
        CREATE TABLE composition_reconciliations (
            id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id           uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            agent_id         uuid NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            agent_version_id uuid NOT NULL REFERENCES agent_versions(id) ON DELETE CASCADE,
            element_kind     text NOT NULL,
            element_key      text NOT NULL,
            declared         boolean NOT NULL,
            observed         boolean NOT NULL,
            status           reconciliation_status NOT NULL,
            observed_count   integer NOT NULL DEFAULT 0,
            window_start     date NOT NULL,
            window_end       date NOT NULL,
            computed_at      timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT composition_reconciliations_unique
                UNIQUE (org_id, agent_version_id, element_kind, element_key, window_end)
        );

        CREATE INDEX composition_reconciliations_agent_idx
            ON composition_reconciliations (org_id, agent_id, window_end DESC);
    """)

    op.execute("""
        ALTER TABLE composition_rule_obligations ENABLE ROW LEVEL SECURITY;
        ALTER TABLE composition_rule_obligations FORCE ROW LEVEL SECURITY;
        CREATE POLICY composition_obligations_tenant ON composition_rule_obligations
            USING (current_org_matches(org_id))
            WITH CHECK (current_org_matches(org_id));

        ALTER TABLE composition_reconciliations ENABLE ROW LEVEL SECURITY;
        ALTER TABLE composition_reconciliations FORCE ROW LEVEL SECURITY;
        CREATE POLICY composition_reconciliations_tenant ON composition_reconciliations
            USING (current_org_matches(org_id))
            WITH CHECK (current_org_matches(org_id));
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS composition_reconciliations CASCADE;
        DROP TABLE IF EXISTS composition_rule_obligations CASCADE;
        DROP TYPE IF EXISTS reconciliation_status;
    """)
