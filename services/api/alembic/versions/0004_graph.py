"""Agent Graph: nodes, edges, and the discovery pipeline that populates them.

Milestone M3. Layer 3 of the HLD, and the asset that compounds: every additional agent
makes the graph more valuable than the sum of the agents in it.

Three decisions worth understanding before changing anything here.

**One edge table, traversed with recursive CTEs.** Not Apache AGE, not Neo4j. Managed
Postgres will not install a graph extension, and BYOC means a customer's RDS instance is
the deployment target (AGENTS.md, deployment modes). The graph is small in graph terms --
tens of thousands of nodes, not billions -- so a recursive CTE over a well-indexed edge
table answers reachability in single-digit milliseconds. Revisit only when a measurement
says otherwise.

**Declared and observed edges coexist rather than overwrite.** The unique constraint on
graph_edges includes `source`, so an edge asserted by a descriptor and the same edge seen
in telemetry are two rows. That is deliberate: the gap between them is the most valuable
data in the product. A declared edge with no observed counterpart is documentation nobody
honours. An observed edge with no declared counterpart is an agent doing something its
owner never wrote down, and that is the finding a security reviewer actually wants.

**Edges retire, they do not delete.** `retired_at` is set when a rebuild no longer sees
an edge. Deleting would destroy the answer to "when did this agent stop reaching the
payments system?", which is a question every incident review asks.

Hand-written per AGENTS.md rule 7.

Revision ID: 0004_graph
Revises: 0003_evidence
Create Date: 2026-09-13
"""

from __future__ import annotations

from alembic import op

revision = "0004_graph"
down_revision = "0003_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Enums
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TYPE graph_node_kind AS ENUM (
            'agent',
            'model',
            'prompt',
            'tool',
            'mcp_server',
            'data_class',
            'data_source',
            'vector_store',
            'dataset',
            'guardrail',
            'team',
            'person',
            'region',
            'framework',
            'customer',
            'engagement'
        );
    """)

    # Edge kinds are directional and named from source to destination, so
    # 'agent uses_model model' reads in the order the row is written.
    op.execute("""
        CREATE TYPE graph_edge_kind AS ENUM (
            'uses_model',
            'uses_prompt',
            'invokes_tool',
            'connects_mcp',
            'reads_data',
            'writes_data',
            'delegates_to',
            'owned_by',
            'accountable_for',
            'deployed_in',
            'processes_in',
            'accredited_under',
            'in_scope_for',
            'guarded_by',
            'depends_on'
        );
    """)

    op.execute("""
        CREATE TYPE graph_source AS ENUM ('declared','observed','inferred');
    """)

    # ------------------------------------------------------------------
    # Nodes
    #
    # node_key is a stable natural key within (org_id, kind), which is what lets a
    # rebuild be idempotent and lets two different sources converge on one node:
    #   agent        -> its URN
    #   model        -> provider/family/id
    #   tool         -> kind:server:name
    #   mcp_server   -> the server URL
    #   data_class   -> the class label
    #   team, region -> the identifier itself
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE graph_nodes (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id        uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

            kind          graph_node_kind NOT NULL,
            node_key      text NOT NULL,
            label         text NOT NULL,

            -- Back-reference for nodes that are also first-class records elsewhere.
            -- Null for a model or a tool, which exist only as graph nodes.
            entity_id     uuid,

            -- Rendering and filtering attributes: provider, hosting, effect,
            -- reversibility, criticality. Digests and enum labels, never content.
            attrs         jsonb NOT NULL DEFAULT '{}'::jsonb,

            -- Provenance at node level, so the console can show "3 agents nobody
            -- declared" without walking edges.
            is_declared   boolean NOT NULL DEFAULT false,
            is_observed   boolean NOT NULL DEFAULT false,

            first_seen_at timestamptz NOT NULL DEFAULT now(),
            last_seen_at  timestamptz NOT NULL DEFAULT now(),
            retired_at    timestamptz,

            CONSTRAINT graph_nodes_key_unique UNIQUE (org_id, kind, node_key),
            CONSTRAINT graph_nodes_provenance_present CHECK (is_declared OR is_observed)
        );

        CREATE INDEX graph_nodes_org_kind_idx ON graph_nodes (org_id, kind)
            WHERE retired_at IS NULL;

        -- "which agents nobody wrote down?" -- the discovery screen's headline query
        CREATE INDEX graph_nodes_undeclared_idx ON graph_nodes (org_id, kind)
            WHERE is_declared = false AND retired_at IS NULL;

        CREATE INDEX graph_nodes_entity_idx ON graph_nodes (org_id, entity_id)
            WHERE entity_id IS NOT NULL;

        CREATE INDEX graph_nodes_attrs_gin
            ON graph_nodes USING gin (attrs jsonb_path_ops);
    """)

    # ------------------------------------------------------------------
    # Edges
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE graph_edges (
            id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id           uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

            src_id           uuid NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,
            dst_id           uuid NOT NULL REFERENCES graph_nodes(id) ON DELETE CASCADE,

            kind             graph_edge_kind NOT NULL,
            source           graph_source NOT NULL,

            -- 0.00-1.00. Declared edges are 1.00 by definition; observed edges carry
            -- the collector's confidence, inferred edges carry the rule's.
            confidence       numeric(3,2) NOT NULL DEFAULT 1.00,

            -- Which version asserted a declared edge. Null for observed edges, which
            -- belong to the running system rather than to any descriptor.
            agent_version_id uuid REFERENCES agent_versions(id) ON DELETE SET NULL,

            -- For an observed edge: how many times it was seen in the current window.
            -- A tool invoked once and a tool invoked ten thousand times are different
            -- risks, and a reviewer triaging a blast radius needs to tell them apart.
            observation_count bigint NOT NULL DEFAULT 0,

            attrs            jsonb NOT NULL DEFAULT '{}'::jsonb,

            first_seen_at    timestamptz NOT NULL DEFAULT now(),
            last_seen_at     timestamptz NOT NULL DEFAULT now(),
            retired_at       timestamptz,

            -- source is part of the key on purpose: declared and observed versions of
            -- the same edge must both exist for the gap to be visible.
            CONSTRAINT graph_edges_unique UNIQUE (org_id, src_id, dst_id, kind, source),
            CONSTRAINT graph_edges_no_self_loop CHECK (src_id <> dst_id),
            CONSTRAINT graph_edges_confidence_range CHECK (
                confidence >= 0 AND confidence <= 1
            )
        );

        -- The traversal indexes. Both directions, both partial on live edges, because
        -- reachability walks forward and blast radius walks backward.
        CREATE INDEX graph_edges_out_idx ON graph_edges (org_id, src_id, kind)
            WHERE retired_at IS NULL;
        CREATE INDEX graph_edges_in_idx  ON graph_edges (org_id, dst_id, kind)
            WHERE retired_at IS NULL;

        -- "what is running that nobody declared?" and its mirror, "what did we
        -- document that never actually happens?"
        CREATE INDEX graph_edges_source_idx ON graph_edges (org_id, source, kind)
            WHERE retired_at IS NULL;

        CREATE INDEX graph_edges_version_idx ON graph_edges (agent_version_id)
            WHERE agent_version_id IS NOT NULL;
    """)

    # ------------------------------------------------------------------
    # Reconciliation view.
    #
    # A view rather than application code because both the console and the
    # accreditation pack need exactly this comparison, and two implementations of it
    # would eventually disagree -- at which point the product is telling a customer two
    # different stories about their own estate.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE VIEW graph_edge_reconciliation AS
        SELECT
            e.org_id,
            e.src_id,
            e.dst_id,
            e.kind,
            bool_or(e.source = 'declared') AS declared,
            bool_or(e.source = 'observed') AS observed,
            max(e.last_seen_at)            AS last_seen_at,
            sum(e.observation_count)       AS observation_count,
            CASE
                WHEN bool_or(e.source = 'declared') AND bool_or(e.source = 'observed')
                    THEN 'confirmed'
                WHEN bool_or(e.source = 'declared')
                    THEN 'declared_not_observed'
                ELSE 'observed_not_declared'
            END AS reconciliation
        FROM graph_edges e
        WHERE e.retired_at IS NULL
        GROUP BY e.org_id, e.src_id, e.dst_id, e.kind;
    """)

    # ------------------------------------------------------------------
    # Discovery. Layer 2 of the HLD: finding agents nobody registered.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TYPE discovery_kind AS ENUM (
            'otel',
            'k8s',
            'egress',
            'mcp_scan',
            'provider_keys',
            'vcs',
            'manual'
        );

        CREATE TYPE discovery_state AS ENUM (
            'new',
            'confirmed',
            'dismissed',
            'merged'
        );
    """)

    op.execute("""
        CREATE TABLE discovery_sources (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id       uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

            kind         discovery_kind NOT NULL,
            name         text NOT NULL,

            -- Endpoint, namespace selector or scan target. Credentials are never here;
            -- they resolve through app/providers/secrets.py by reference.
            config       jsonb NOT NULL DEFAULT '{}'::jsonb,
            secret_ref   text,

            is_enabled   boolean NOT NULL DEFAULT true,

            last_run_at      timestamptz,
            last_status      text,
            last_error       text,
            findings_last_run integer NOT NULL DEFAULT 0,

            created_at   timestamptz NOT NULL DEFAULT now(),
            updated_at   timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT discovery_sources_name_unique UNIQUE (org_id, name)
        );

        CREATE TRIGGER discovery_sources_touch
            BEFORE UPDATE ON discovery_sources
            FOR EACH ROW EXECUTE FUNCTION touch_updated_at();
    """)

    op.execute("""
        CREATE TABLE discovery_findings (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id         uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            source_id      uuid NOT NULL
                               REFERENCES discovery_sources(id) ON DELETE CASCADE,

            -- What we think we found, in the same key space as graph_nodes so a
            -- confirmed finding can be promoted without re-keying it.
            candidate_kind graph_node_kind NOT NULL,
            candidate_key  text NOT NULL,
            label          text NOT NULL,

            -- Why we think so: span attributes seen, image name, endpoint reached.
            -- Bounded like evidence, for the same reason.
            signals        jsonb NOT NULL DEFAULT '{}'::jsonb,
            confidence     numeric(3,2) NOT NULL DEFAULT 0.50,

            state          discovery_state NOT NULL DEFAULT 'new',

            -- Set when the finding becomes a registered agent.
            agent_id       uuid REFERENCES agents(id) ON DELETE SET NULL,

            first_seen_at  timestamptz NOT NULL DEFAULT now(),
            last_seen_at   timestamptz NOT NULL DEFAULT now(),
            resolved_by    text,
            resolved_at    timestamptz,
            resolution_note text,

            CONSTRAINT discovery_findings_unique
                UNIQUE (org_id, source_id, candidate_kind, candidate_key),
            CONSTRAINT discovery_findings_confidence_range CHECK (
                confidence >= 0 AND confidence <= 1
            ),
            CONSTRAINT discovery_findings_merge_consistent CHECK (
                (state = 'merged') = (agent_id IS NOT NULL)
            )
        );

        -- The triage queue: unresolved findings, highest confidence first.
        CREATE INDEX discovery_findings_triage_idx
            ON discovery_findings (org_id, confidence DESC, last_seen_at DESC)
            WHERE state = 'new';

        CREATE INDEX discovery_findings_source_idx
            ON discovery_findings (source_id, state);
    """)

    # ------------------------------------------------------------------
    # Row-level security
    # ------------------------------------------------------------------
    for table in (
        "graph_nodes",
        "graph_edges",
        "discovery_sources",
        "discovery_findings",
    ):
        op.execute(f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY {table}_tenant_isolation ON {table}
                USING (current_org_matches(org_id))
                WITH CHECK (current_org_matches(org_id));
        """)


def downgrade() -> None:
    op.execute("""
        DROP VIEW IF EXISTS graph_edge_reconciliation;

        DROP TABLE IF EXISTS discovery_findings CASCADE;
        DROP TABLE IF EXISTS discovery_sources CASCADE;
        DROP TABLE IF EXISTS graph_edges CASCADE;
        DROP TABLE IF EXISTS graph_nodes CASCADE;

        DROP TYPE IF EXISTS discovery_state;
        DROP TYPE IF EXISTS discovery_kind;
        DROP TYPE IF EXISTS graph_source;
        DROP TYPE IF EXISTS graph_edge_kind;
        DROP TYPE IF EXISTS graph_node_kind;
    """)
