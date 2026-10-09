"""Baseline: organisations, agents, immutable versions, ownership, BOM, releases, jobs.

Covers milestones M0 and M1. Evidence (M2), graph (M3) and accreditation (M5) arrive in
later migrations so that each can be reviewed on its own.

Hand-written per AGENTS.md rule 7. Raw SQL is used deliberately: this file is read far
more often than it is written, and the SQL is clearer than the equivalent op() calls.

Revision ID: 0001_baseline
Create Date: 2026-09-13
"""

from __future__ import annotations

from alembic import op

revision = "0001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Extensions. pgcrypto only — see AGENTS.md. Managed Postgres (RDS,
    # Azure Database, Cloud SQL) will not install anything beyond this, which
    # is why the graph is recursive CTEs rather than a graph extension.
    # ------------------------------------------------------------------
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    # ------------------------------------------------------------------
    # Shared enums
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TYPE lifecycle_state AS ENUM
            ('dev','test','staging','production','retired');

        CREATE TYPE ownership_role AS ENUM
            ('accountable','approver_of_record','technical','change_authority','business');

        CREATE TYPE component_kind AS ENUM
            ('model','prompt','tool','mcp_server','library','dataset','sub_agent',
             'vector_store','data_source','guardrail');

        CREATE TYPE materiality AS ENUM ('material','immaterial','needs_review');
    """)

    # ------------------------------------------------------------------
    # Immutability guard, reused by every append-only table
    # ------------------------------------------------------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION forbid_mutation() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'append-only table: % is immutable', TG_TABLE_NAME
                USING HINT = 'insert a new row instead of modifying an existing one';
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Row-level security predicate. Returns true when the current transaction is
    # either scoped to this row's tenant or explicitly bypassing (worker sweeps,
    # partition maintenance).
    op.execute("""
        CREATE OR REPLACE FUNCTION current_org_matches(row_org uuid)
        RETURNS boolean AS $$
        BEGIN
            IF coalesce(current_setting('app.bypass_rls', true), 'off') = 'on' THEN
                RETURN true;
            END IF;
            RETURN row_org = nullif(current_setting('app.org_id', true), '')::uuid;
        END;
        $$ LANGUAGE plpgsql STABLE;
    """)

    # ------------------------------------------------------------------
    # Organisations. Present even in single-tenant BYOC installs so the code
    # path is identical across deployment modes.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE organizations (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            slug        text NOT NULL UNIQUE,
            name        text NOT NULL,
            created_at  timestamptz NOT NULL DEFAULT now()
        );
    """)

    # ------------------------------------------------------------------
    # Agents and their immutable versions
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE agents (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id              uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            urn                 text NOT NULL,
            display_name        text NOT NULL,
            description         text,
            owning_team         text,
            lifecycle_state     lifecycle_state NOT NULL DEFAULT 'dev',

            -- what is running now, versus what was actually signed off
            current_version_id  uuid,
            baseline_version_id uuid,

            -- set when the agent was found rather than registered
            discovered_at       timestamptz,
            first_seen_source   text NOT NULL DEFAULT 'declared',

            created_at          timestamptz NOT NULL DEFAULT now(),
            updated_at          timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agents_urn_unique UNIQUE (org_id, urn),
            CONSTRAINT agents_source_valid CHECK (
                first_seen_source IN ('declared','otel','k8s','egress','mcp_scan','manual')
            )
        );

        CREATE INDEX agents_org_state_idx ON agents (org_id, lifecycle_state);
        CREATE INDEX agents_org_team_idx  ON agents (org_id, owning_team);
    """)

    op.execute("""
        CREATE TABLE agent_versions (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id            uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            agent_id          uuid NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            semver            text NOT NULL,

            -- the complete AAP descriptor, plus a hash over its canonical form
            descriptor_json   jsonb NOT NULL,
            descriptor_digest text NOT NULL,

            -- denormalised for list filters; always derivable from the descriptor
            runtime_framework text,
            runtime_language  text,
            environment       lifecycle_state NOT NULL,
            autonomy          text,

            -- source control linkage, so a release can point back at a commit
            vcs_provider      text,
            vcs_repo          text,
            vcs_ref           text,

            published_at      timestamptz NOT NULL DEFAULT now(),
            published_by      text NOT NULL,

            CONSTRAINT agent_versions_semver_unique UNIQUE (agent_id, semver)
        );

        CREATE INDEX agent_versions_agent_idx  ON agent_versions (agent_id, published_at DESC);
        CREATE INDEX agent_versions_digest_idx ON agent_versions (org_id, descriptor_digest);

        -- "which agents use this model provider?" and similar descriptor queries
        CREATE INDEX agent_versions_descriptor_gin
            ON agent_versions USING gin (descriptor_json jsonb_path_ops);

        CREATE TRIGGER agent_versions_immutable
            BEFORE UPDATE OR DELETE ON agent_versions
            FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
    """)

    op.execute("""
        ALTER TABLE agents
            ADD CONSTRAINT agents_current_version_fk
                FOREIGN KEY (current_version_id) REFERENCES agent_versions(id),
            ADD CONSTRAINT agents_baseline_version_fk
                FOREIGN KEY (baseline_version_id) REFERENCES agent_versions(id);
    """)

    # ------------------------------------------------------------------
    # Ownership, with validity windows so accountability survives a reorg
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE agent_ownership (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id       uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            agent_id     uuid NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            role         ownership_role NOT NULL,
            principal_id text NOT NULL,
            source       text NOT NULL DEFAULT 'declared',
            valid_from   timestamptz NOT NULL DEFAULT now(),
            valid_to     timestamptz,

            CONSTRAINT ownership_window_sane CHECK (valid_to IS NULL OR valid_to > valid_from)
        );

        -- exactly one current holder per role per agent
        CREATE UNIQUE INDEX agent_ownership_current_idx
            ON agent_ownership (agent_id, role) WHERE valid_to IS NULL;

        CREATE INDEX agent_ownership_principal_idx
            ON agent_ownership (org_id, principal_id) WHERE valid_to IS NULL;
    """)

    # ------------------------------------------------------------------
    # Bill of materials
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE bom_components (
            id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id           uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            agent_version_id uuid NOT NULL REFERENCES agent_versions(id) ON DELETE CASCADE,

            kind             component_kind NOT NULL,
            name             text NOT NULL,
            version          text,
            provider         text,
            licence          text,

            effect           text,
            reversible       boolean,
            human_approval   text,

            -- content hash: prompts and configs change without a version bump
            digest           text,

            -- what the component claims about itself, e.g. MCP tool annotations
            declared_meta    jsonb NOT NULL DEFAULT '{}'::jsonb,
            -- what we actually measured, for reconciliation against the claim
            observed_meta    jsonb NOT NULL DEFAULT '{}'::jsonb,

            CONSTRAINT bom_unique UNIQUE (agent_version_id, kind, name, version),
            CONSTRAINT bom_effect_valid CHECK (effect IS NULL OR effect IN ('read','write','none')),
            CONSTRAINT bom_approval_valid CHECK (
                human_approval IS NULL OR human_approval IN ('none','required','conditional')
            )
        );

        -- "which agents depend on X?" across the whole estate
        CREATE INDEX bom_lookup_idx ON bom_components (org_id, kind, name);
        CREATE INDEX bom_version_idx ON bom_components (agent_version_id);

        CREATE TRIGGER bom_components_immutable
            BEFORE UPDATE OR DELETE ON bom_components
            FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
    """)

    # ==================================================================
    # RELEASES — agent-native change management.
    #
    # Source control shows line diffs. It cannot tell you that the model
    # changed, the timeout doubled, a write-capable tool was added or the
    # instruction was semantically rewritten. Those facts are what a reviewer,
    # an owner and an approver actually need, so they are modelled explicitly.
    # ==================================================================
    op.execute("""
        CREATE TYPE release_state AS ENUM
            ('draft','proposed','approved','rolled_out','rolled_back','abandoned');

        CREATE TYPE change_category AS ENUM (
            'model',            -- provider, family, id, hosting, role
            'inference_params', -- temperature, top_p, max_tokens, seed
            'prompt',           -- system prompt or instruction content
            'tool',             -- tool added, removed, effect changed
            'mcp_server',       -- MCP endpoint added, removed, version changed
            'capability',       -- declared action surface
            'dependency',       -- library and package versions
            'data_source',      -- databases, vector stores, retrieval sources
            'data_class',       -- classes of data touched
            'residency',        -- permitted regions, cross-border stance
            'guardrail',        -- input and output filters, schema validation
            'oversight',        -- human approval requirements
            'resilience',       -- timeouts, retries, circuit breakers, fallbacks
            'delegation',       -- agent-to-agent trust edges
            'deployment',       -- runtime, framework version, environment
            'metadata'          -- ownership, naming, description
        );

        CREATE TYPE change_operation AS ENUM ('added','removed','modified');

        CREATE TYPE impact_dimension AS ENUM
            ('behaviour','security','cost','latency','compliance');
    """)

    op.execute("""
        CREATE TABLE releases (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id            uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            agent_id          uuid NOT NULL REFERENCES agents(id) ON DELETE CASCADE,

            from_version_id   uuid REFERENCES agent_versions(id),   -- null on first release
            to_version_id     uuid NOT NULL REFERENCES agent_versions(id),

            release_tag       text NOT NULL,
            title             text,
            notes             text,                                 -- author's own summary
            state             release_state NOT NULL DEFAULT 'draft',

            -- roll-ups so the release list renders without joining changes
            change_count      integer NOT NULL DEFAULT 0,
            material_count    integer NOT NULL DEFAULT 0,
            review_count      integer NOT NULL DEFAULT 0,

            -- which dimensions this release touches, for the impact badges
            impacts           impact_dimension[] NOT NULL DEFAULT '{}',
            categories        change_category[] NOT NULL DEFAULT '{}',

            -- computed consequence for existing approvals
            accreditation_impact    text NOT NULL DEFAULT 'none',
            affected_accreditations integer NOT NULL DEFAULT 0,

            -- source control linkage
            vcs_provider      text,
            vcs_repo          text,
            vcs_ref           text,
            vcs_pr_ref        text,

            proposed_by       text,
            proposed_at       timestamptz,
            approved_by       text,
            approved_at       timestamptz,
            rolled_out_at     timestamptz,
            rolled_back_at    timestamptz,
            created_at        timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT releases_tag_unique UNIQUE (agent_id, release_tag),
            CONSTRAINT releases_versions_differ CHECK (from_version_id IS DISTINCT FROM to_version_id),
            CONSTRAINT releases_acc_impact_valid CHECK (
                accreditation_impact IN ('none','requires_revalidation','suspends')
            )
        );

        CREATE INDEX releases_agent_idx ON releases (agent_id, created_at DESC);
        CREATE INDEX releases_org_state_idx ON releases (org_id, state, created_at DESC);
        CREATE INDEX releases_material_idx
            ON releases (org_id, created_at DESC) WHERE material_count > 0;
        CREATE INDEX releases_vcs_idx ON releases (org_id, vcs_provider, vcs_repo, vcs_ref);
    """)

    op.execute("""
        CREATE TABLE release_changes (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id        uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            release_id    uuid NOT NULL REFERENCES releases(id) ON DELETE CASCADE,

            category      change_category NOT NULL,
            operation     change_operation NOT NULL,

            -- machine-addressable location in the descriptor, e.g. 'models[0].family'
            path          text NOT NULL,
            -- human label, e.g. 'Primary model'
            subject       text NOT NULL,

            before_value  jsonb,
            after_value   jsonb,

            -- the one-line sentence shown in the release view. This is the field that
            -- makes the product legible to a non-author reviewer.
            summary       text NOT NULL,
            detail        text,

            impacts       impact_dimension[] NOT NULL DEFAULT '{}',
            severity      text NOT NULL DEFAULT 'info',

            -- verdict from the materiality engine, with the rules that produced it
            verdict       materiality NOT NULL DEFAULT 'immaterial',
            rules_fired   text[] NOT NULL DEFAULT '{}',

            -- how we learned about this change
            detected_by   text NOT NULL DEFAULT 'descriptor_diff',

            -- set when a human overrode the automatic verdict
            adjudicated_by      text,
            adjudicated_at      timestamptz,
            adjudication_reason text,

            created_at    timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT release_changes_severity_valid CHECK (
                severity IN ('critical','high','medium','low','info')
            ),
            CONSTRAINT release_changes_detected_valid CHECK (
                detected_by IN ('descriptor_diff','bom_diff','observed','manual')
            )
        );

        CREATE INDEX release_changes_release_idx ON release_changes (release_id, category);
        CREATE INDEX release_changes_category_idx ON release_changes (org_id, category, created_at DESC);
        CREATE INDEX release_changes_review_idx
            ON release_changes (org_id, created_at DESC) WHERE verdict = 'needs_review';
    """)

    # Keep the release roll-ups correct without the application having to remember.
    op.execute("""
        CREATE OR REPLACE FUNCTION refresh_release_rollup() RETURNS trigger AS $$
        DECLARE
            target uuid := coalesce(NEW.release_id, OLD.release_id);
        BEGIN
            UPDATE releases r SET
                change_count   = c.total,
                material_count = c.material,
                review_count   = c.review,
                impacts        = c.impacts,
                categories     = c.categories,
                accreditation_impact = CASE
                    WHEN c.material > 0 THEN 'suspends'
                    WHEN c.review   > 0 THEN 'requires_revalidation'
                    ELSE 'none'
                END
            FROM (
                SELECT
                    count(*)                                              AS total,
                    count(*) FILTER (WHERE verdict = 'material')           AS material,
                    count(*) FILTER (WHERE verdict = 'needs_review')       AS review,
                    coalesce(array_agg(DISTINCT i) FILTER (WHERE i IS NOT NULL), '{}')
                        AS impacts,
                    coalesce(array_agg(DISTINCT category), '{}')           AS categories
                FROM release_changes
                LEFT JOIN LATERAL unnest(impacts) AS i ON true
                WHERE release_id = target
            ) c
            WHERE r.id = target;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER release_changes_rollup
            AFTER INSERT OR UPDATE OR DELETE ON release_changes
            FOR EACH ROW EXECUTE FUNCTION refresh_release_rollup();
    """)

    # ------------------------------------------------------------------
    # Job queue. Postgres SKIP LOCKED instead of a broker — see AGENTS.md.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE jobs (
            id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            org_id        uuid REFERENCES organizations(id) ON DELETE CASCADE,
            kind          text NOT NULL,
            payload       jsonb NOT NULL DEFAULT '{}'::jsonb,
            dedupe_key    text,
            run_after     timestamptz NOT NULL DEFAULT now(),
            attempts      integer NOT NULL DEFAULT 0,
            max_attempts  integer NOT NULL DEFAULT 5,
            locked_by     text,
            locked_at     timestamptz,
            completed_at  timestamptz,
            failed_at     timestamptz,
            last_error    text,
            created_at    timestamptz NOT NULL DEFAULT now()
        );

        -- the dequeue index: partial, so it stays small as completed rows accumulate
        CREATE INDEX jobs_ready_idx ON jobs (run_after)
            WHERE completed_at IS NULL AND failed_at IS NULL AND locked_by IS NULL;

        -- at-most-one pending job per dedupe key
        CREATE UNIQUE INDEX jobs_dedupe_idx ON jobs (kind, dedupe_key)
            WHERE completed_at IS NULL AND failed_at IS NULL AND dedupe_key IS NOT NULL;
    """)

    # ------------------------------------------------------------------
    # Row-level security. A backstop, not the primary control: every query
    # still filters by org_id explicitly.
    # ------------------------------------------------------------------
    for table in (
        "agents",
        "agent_versions",
        "agent_ownership",
        "bom_components",
        "releases",
        "release_changes",
    ):
        op.execute(f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY {table}_tenant_isolation ON {table}
                USING (current_org_matches(org_id))
                WITH CHECK (current_org_matches(org_id));
        """)

    # ------------------------------------------------------------------
    # Default organisation. Single-tenant installs need one to exist before
    # the first request; in SaaS this row is simply the local dev tenant.
    # ------------------------------------------------------------------
    op.execute("""
        INSERT INTO organizations (slug, name)
        VALUES ('default', 'Default Organisation')
        ON CONFLICT (slug) DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS release_changes CASCADE;
        DROP TABLE IF EXISTS releases CASCADE;
        DROP TABLE IF EXISTS jobs CASCADE;
        DROP TABLE IF EXISTS bom_components CASCADE;
        DROP TABLE IF EXISTS agent_ownership CASCADE;
        DROP TABLE IF EXISTS agent_versions CASCADE;
        DROP TABLE IF EXISTS agents CASCADE;
        DROP TABLE IF EXISTS organizations CASCADE;

        DROP FUNCTION IF EXISTS refresh_release_rollup() CASCADE;
        DROP FUNCTION IF EXISTS current_org_matches(uuid) CASCADE;
        DROP FUNCTION IF EXISTS forbid_mutation() CASCADE;

        DROP TYPE IF EXISTS impact_dimension;
        DROP TYPE IF EXISTS change_operation;
        DROP TYPE IF EXISTS change_category;
        DROP TYPE IF EXISTS release_state;
        DROP TYPE IF EXISTS materiality;
        DROP TYPE IF EXISTS component_kind;
        DROP TYPE IF EXISTS ownership_role;
        DROP TYPE IF EXISTS lifecycle_state;
    """)
