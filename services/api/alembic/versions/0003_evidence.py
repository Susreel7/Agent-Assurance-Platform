"""Evidence store: append-only events, Merkle batches, published checkpoints.

Milestone M2. This is the substrate layer 4 and layer 5 read from, so it lands before
the graph and before accreditation.

Two decisions in here carry the whole design.

**The hash chain is per batch, not per event.** A chain where every row hashes the
previous row serialises every insert behind one lock, which caps ingest at a few hundred
events a second per organisation no matter how much hardware is available. Instead events
are hashed independently on arrival, then a sealer groups them into a batch, builds an
RFC 6962 Merkle tree over the leaves and chains the *batch* digests. Tamper detection is
unchanged, ingest parallelises, and an auditor gains something a row chain cannot offer:
an inclusion proof for one event that reveals nothing about the others.

**Events carry digests, classifications and decisions. Never content.** The CHECK
constraints below are the second line of defence after AGENTS.md rule 5, because a
collector running inside a regulated estate is only approvable if the schema itself makes
payload capture impossible.

Hand-written per AGENTS.md rule 7.

Revision ID: 0003_evidence
Revises: 0002_company_model
Create Date: 2026-09-13
"""

from __future__ import annotations

from alembic import op

revision = "0003_evidence"
down_revision = "0002_company_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Enums
    #
    # Labels name the *fact being evidenced*, not the mechanism that observed it
    # (NAMING.md section 7). Mechanism lives in evidence_events.detected_by, so the
    # same fact arriving from a span, a Kubernetes scan or a manual upload is one
    # label rather than three.
    #
    # The first thirteen are already referenced by control_mappings in 0002. The
    # remainder gain their mappings in 0005, which keeps the "every kind answers some
    # control" invariant true at every revision rather than only at head.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TYPE evidence_kind AS ENUM (
            'model_inventory',
            'tool_permission_inventory',
            'data_class_inventory',
            'bom_completeness',
            'ownership_record',
            'residency_proof',
            'oversight_record',
            'change_history',
            'materiality_verdict',
            'adversarial_probe',
            'vulnerability_scan',
            'service_level_attainment',
            'chain_integrity',
            'accreditation_decision',
            'attestation_run',
            'policy_decision',
            'routing_decision',
            'failover_event',
            'incident_record',
            'approval_record',
            'prompt_integrity',
            'delegation_record',
            'guardrail_activation',
            'retention_proof',
            'access_review'
        );
    """)

    # ------------------------------------------------------------------
    # control_mappings.evidence_kind adopts the type the moment it exists.
    #
    # 0002 had to create that column as text with a hand-written CHECK, because the
    # vocabulary had no home yet. That list then drifted: it stopped at sixteen values
    # while this type reached twenty-five, so the mappings 0005 adds for the newer kinds
    # were rejected by a constraint three migrations away from them. Converting the
    # column makes the drift structurally impossible rather than merely fixed.
    # ------------------------------------------------------------------
    op.execute("""
        ALTER TABLE control_mappings
            DROP CONSTRAINT IF EXISTS control_mappings_evidence_kind_valid;

        ALTER TABLE control_mappings
            ALTER COLUMN evidence_kind TYPE evidence_kind
            USING evidence_kind::evidence_kind;
    """)

    # One vocabulary for "what happened", spanning policy verdicts, probe results and
    # plain observation. A single column means the evidence explorer needs no per-kind
    # special casing to render an outcome.
    op.execute("""
        CREATE TYPE evidence_outcome AS ENUM (
            'observed',
            'allow',
            'deny',
            'redact',
            'reroute',
            'require_approval',
            'pass',
            'fail',
            'degraded',
            'error'
        );
    """)

    # ------------------------------------------------------------------
    # Batches. The chain lives here.
    #
    # tree_size is cumulative across all batches for the organisation, so a consumer
    # holding an older checkpoint can verify the log is append-only by checking that
    # tree_size only ever grows and that prev_batch_digest matches what they held.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE evidence_batches (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id            uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

            seq               bigint NOT NULL,

            window_start      timestamptz NOT NULL,
            window_end        timestamptz NOT NULL,

            leaf_count        integer NOT NULL,
            tree_size         bigint NOT NULL,

            -- RFC 6962 root over this batch's leaves, lowercase hex, 'sha256:' prefixed
            merkle_root       text NOT NULL,
            -- digest of batch seq-1, or the genesis constant for seq 0
            prev_batch_digest text NOT NULL,
            batch_digest      text NOT NULL,

            sealed_at         timestamptz NOT NULL DEFAULT now(),
            sealed_by         text NOT NULL DEFAULT 'service:worker',

            -- ES256 over batch_digest. Null when no signing key is configured; the
            -- chain is still verifiable, it simply is not attributable.
            signature         text,
            signing_key_ref   text,

            CONSTRAINT evidence_batches_seq_unique    UNIQUE (org_id, seq),
            CONSTRAINT evidence_batches_digest_unique UNIQUE (org_id, batch_digest),
            CONSTRAINT evidence_batches_window_sane   CHECK (window_end > window_start),
            CONSTRAINT evidence_batches_leaves_sane   CHECK (leaf_count > 0),
            CONSTRAINT evidence_batches_digest_shape  CHECK (
                merkle_root       ~ '^sha256:[0-9a-f]{64}$' AND
                prev_batch_digest ~ '^sha256:[0-9a-f]{64}$' AND
                batch_digest      ~ '^sha256:[0-9a-f]{64}$'
            )
        );

        CREATE INDEX evidence_batches_org_seq_idx ON evidence_batches (org_id, seq DESC);

        CREATE TRIGGER evidence_batches_immutable
            BEFORE UPDATE OR DELETE ON evidence_batches
            FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
    """)

    # ------------------------------------------------------------------
    # Events. Partitioned monthly by occurred_at.
    #
    # Partitioning by occurred_at rather than recorded_at means retention is expressed
    # in the same terms the customer's retention policy is written in, and dropping an
    # expired month is a DROP TABLE rather than a DELETE over millions of rows.
    #
    # The primary key must include the partition key, hence (id, occurred_at).
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE evidence_events (
            id                uuid NOT NULL DEFAULT gen_random_uuid(),
            org_id            uuid NOT NULL,

            -- Three different questions, deliberately not collapsed (NAMING.md §2):
            -- when it happened, when we learned, when the row was written.
            occurred_at       timestamptz NOT NULL,
            recorded_at       timestamptz NOT NULL DEFAULT now(),

            kind              evidence_kind NOT NULL,

            -- All nullable: some evidence is organisation-level (an access review) and
            -- some predates the agent being registered (a discovery finding).
            agent_id          uuid,
            agent_version_id  uuid,
            engagement_id     uuid,
            customer_id       uuid,

            -- 'person:', 'role:', 'team:' or 'service:' prefixed (NAMING.md §6)
            actor             text NOT NULL DEFAULT 'service:collector',
            action            text NOT NULL,
            outcome           evidence_outcome NOT NULL DEFAULT 'observed',

            -- What the action was about: a tool name, a control ref, a region, a model id
            subject_ref       text,

            -- The governed facts. These, and only these, are what accreditation reads.
            region            text,
            data_classes      text[] NOT NULL DEFAULT '{}',
            decision          text,
            reason_code       text,

            -- Bounded structured extras: digests, enum labels, counts. Never free text
            -- from a prompt, a completion or a tool argument.
            detail            jsonb NOT NULL DEFAULT '{}'::jsonb,

            -- sha256 over the canonical leaf. Field order is frozen; see
            -- app/domains/evidence/service.py and AGENTS.md rule 10.
            content_digest    text NOT NULL,

            detected_by       text NOT NULL DEFAULT 'collector',

            -- Written once by the sealer. Null means this event is not yet anchored.
            batch_id          uuid REFERENCES evidence_batches(id),
            leaf_index        integer,

            PRIMARY KEY (id, occurred_at),

            CONSTRAINT evidence_events_digest_shape CHECK (
                content_digest ~ '^sha256:[0-9a-f]{64}$'
            ),
            CONSTRAINT evidence_events_detected_valid CHECK (
                detected_by IN ('collector','otel','k8s','egress','mcp_scan',
                                'descriptor','probe','scanner','manual','computed')
            ),
            CONSTRAINT evidence_events_anchor_consistent CHECK (
                (batch_id IS NULL AND leaf_index IS NULL) OR
                (batch_id IS NOT NULL AND leaf_index IS NOT NULL AND leaf_index >= 0)
            ),

            -- AGENTS.md rule 5, enforced by the schema rather than only by review.
            -- A field that could hold customer content is bounded to a length no
            -- meaningful payload fits into.
            CONSTRAINT evidence_events_no_content CHECK (
                length(action)                    <= 128 AND
                length(coalesce(subject_ref,''))  <= 512 AND
                length(coalesce(decision,''))     <= 128 AND
                length(coalesce(reason_code,''))  <= 128 AND
                length(coalesce(region,''))       <= 64  AND
                length(actor)                     <= 256 AND
                pg_column_size(detail)            <= 4096
            )
        ) PARTITION BY RANGE (occurred_at);
    """)

    # Indexes are declared on the parent so every partition inherits them.
    #
    # occurred_at leads each composite because every evidence query is time-bounded --
    # an explorer view, a retention sweep and a pack render all ask "in this window".
    op.execute("""
        CREATE INDEX evidence_events_org_time_idx
            ON evidence_events (org_id, occurred_at DESC);

        CREATE INDEX evidence_events_agent_time_idx
            ON evidence_events (agent_id, occurred_at DESC) WHERE agent_id IS NOT NULL;

        CREATE INDEX evidence_events_kind_time_idx
            ON evidence_events (org_id, kind, occurred_at DESC);

        CREATE INDEX evidence_events_engagement_time_idx
            ON evidence_events (engagement_id, occurred_at DESC)
            WHERE engagement_id IS NOT NULL;

        -- The residency query: "did anything touch this data class outside its region?"
        CREATE INDEX evidence_events_classes_idx
            ON evidence_events USING gin (data_classes);

        -- The sealer's scan. Partial, so it stays proportional to the unsealed backlog
        -- rather than to the whole log.
        CREATE INDEX evidence_events_unsealed_idx
            ON evidence_events (org_id, occurred_at) WHERE batch_id IS NULL;

        CREATE INDEX evidence_events_batch_idx
            ON evidence_events (batch_id, leaf_index) WHERE batch_id IS NOT NULL;
    """)

    # ------------------------------------------------------------------
    # Immutability, with exactly two sanctioned exceptions.
    #
    # forbid_mutation() is too blunt here. The sealer must stamp batch_id and
    # leaf_index after the fact, and partition maintenance must move rows out of the
    # default partition. Both are anchoring mechanics rather than changes to what the
    # evidence says, so this trigger permits precisely those and nothing else.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION forbid_evidence_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                -- Retention drops whole partitions; maintenance moves rows out of the
                -- default partition. Neither goes row by row through this path.
                IF coalesce(current_setting('app.partition_maintenance', true), 'off')
                   = 'on' THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION 'evidence_events is append-only: delete is forbidden'
                    USING HINT = 'expire evidence by dropping a partition';
            END IF;

            -- The governed content of an event may never change.
            IF  NEW.id               IS DISTINCT FROM OLD.id
             OR NEW.org_id           IS DISTINCT FROM OLD.org_id
             OR NEW.occurred_at      IS DISTINCT FROM OLD.occurred_at
             OR NEW.recorded_at      IS DISTINCT FROM OLD.recorded_at
             OR NEW.kind             IS DISTINCT FROM OLD.kind
             OR NEW.agent_id         IS DISTINCT FROM OLD.agent_id
             OR NEW.agent_version_id IS DISTINCT FROM OLD.agent_version_id
             OR NEW.engagement_id    IS DISTINCT FROM OLD.engagement_id
             OR NEW.customer_id      IS DISTINCT FROM OLD.customer_id
             OR NEW.actor            IS DISTINCT FROM OLD.actor
             OR NEW.action           IS DISTINCT FROM OLD.action
             OR NEW.outcome          IS DISTINCT FROM OLD.outcome
             OR NEW.subject_ref      IS DISTINCT FROM OLD.subject_ref
             OR NEW.region           IS DISTINCT FROM OLD.region
             OR NEW.data_classes     IS DISTINCT FROM OLD.data_classes
             OR NEW.decision         IS DISTINCT FROM OLD.decision
             OR NEW.reason_code      IS DISTINCT FROM OLD.reason_code
             OR NEW.detail           IS DISTINCT FROM OLD.detail
             OR NEW.content_digest   IS DISTINCT FROM OLD.content_digest
             OR NEW.detected_by      IS DISTINCT FROM OLD.detected_by
            THEN
                RAISE EXCEPTION 'evidence_events is append-only: % is immutable',
                    'event content'
                    USING HINT = 'insert a correcting event instead';
            END IF;

            -- Anchoring is write-once. Re-anchoring an event would let a second batch
            -- claim a leaf the first batch already committed to.
            IF OLD.batch_id IS NOT NULL THEN
                RAISE EXCEPTION 'evidence event is already anchored to batch %',
                    OLD.batch_id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER evidence_events_append_only
            BEFORE UPDATE OR DELETE ON evidence_events
            FOR EACH ROW EXECUTE FUNCTION forbid_evidence_mutation();
    """)

    # ------------------------------------------------------------------
    # Partition management.
    #
    # A default partition exists because losing evidence is worse than misfiling it:
    # a gap in an audit trail outlives whatever caused it. ensure_evidence_partition
    # therefore also drains any rows the default partition caught for the month it is
    # creating, which is the step that makes a default partition safe to keep.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE evidence_events_default PARTITION OF evidence_events DEFAULT;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION ensure_evidence_partition(p_month date)
        RETURNS text AS $$
        DECLARE
            lo   date := date_trunc('month', p_month)::date;
            hi   date := (date_trunc('month', p_month) + interval '1 month')::date;
            name text := 'evidence_events_' || to_char(lo, 'YYYYMM');
            moved integer := 0;
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_class WHERE relname = name) THEN
                RETURN name;
            END IF;

            -- Build the partition detached, fill it from the default partition, then
            -- attach. Attaching first would make the ATTACH scan the default partition
            -- and fail on the very rows we are trying to rescue.
            EXECUTE format(
                'CREATE TABLE %I (LIKE evidence_events INCLUDING DEFAULTS '
                'INCLUDING CONSTRAINTS)', name);

            SET LOCAL app.partition_maintenance = 'on';

            EXECUTE format(
                'INSERT INTO %I SELECT * FROM evidence_events_default '
                'WHERE occurred_at >= %L AND occurred_at < %L', name, lo, hi);
            GET DIAGNOSTICS moved = ROW_COUNT;

            EXECUTE format(
                'DELETE FROM evidence_events_default '
                'WHERE occurred_at >= %L AND occurred_at < %L', lo, hi);

            EXECUTE format(
                'ALTER TABLE evidence_events ATTACH PARTITION %I '
                'FOR VALUES FROM (%L) TO (%L)', name, lo, hi);

            RETURN name || ' (' || moved || ' rows recovered from default)';
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Twelve months back so a customer can import existing audit history, three ahead
    # so the worker's monthly sweep is a safety net rather than load-bearing.
    op.execute("""
        DO $$
        DECLARE m date;
        BEGIN
            FOR m IN
                SELECT generate_series(
                    date_trunc('month', now()) - interval '12 months',
                    date_trunc('month', now()) + interval '3 months',
                    interval '1 month'
                )::date
            LOOP
                PERFORM ensure_evidence_partition(m);
            END LOOP;
        END $$;
    """)

    # ------------------------------------------------------------------
    # Published checkpoints.
    #
    # A root the organisation has shown to someone outside it. Once a customer or
    # auditor holds a checkpoint, we can no longer rewrite history before it even with
    # full database access -- which is the property that makes the log worth trusting
    # rather than merely worth reading.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE evidence_checkpoints (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id        uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            batch_id      uuid NOT NULL REFERENCES evidence_batches(id),

            tree_size     bigint NOT NULL,
            root          text NOT NULL,

            published_at  timestamptz NOT NULL DEFAULT now(),
            -- 'trust_portal', 'accreditation_pack', or a customer slug
            published_to  text NOT NULL,
            external_ref  text,

            signature     text,

            CONSTRAINT evidence_checkpoints_unique UNIQUE (org_id, batch_id, published_to)
        );

        CREATE INDEX evidence_checkpoints_org_idx
            ON evidence_checkpoints (org_id, published_at DESC);

        CREATE TRIGGER evidence_checkpoints_immutable
            BEFORE UPDATE OR DELETE ON evidence_checkpoints
            FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
    """)

    # ------------------------------------------------------------------
    # Row-level security
    # ------------------------------------------------------------------
    for table in ("evidence_events", "evidence_batches", "evidence_checkpoints"):
        op.execute(f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY {table}_tenant_isolation ON {table}
                USING (current_org_matches(org_id))
                WITH CHECK (current_org_matches(org_id));
        """)


def downgrade() -> None:
    # Put control_mappings back on text before dropping the type it depends on,
    # restoring the sixteen-value CHECK that 0002 expects to own.
    op.execute("""
        ALTER TABLE control_mappings
            ALTER COLUMN evidence_kind TYPE text
            USING evidence_kind::text;

        ALTER TABLE control_mappings
            DROP CONSTRAINT IF EXISTS control_mappings_evidence_kind_valid;

        ALTER TABLE control_mappings
            ADD CONSTRAINT control_mappings_evidence_kind_valid CHECK (
                evidence_kind IN (
                    'bom_completeness','model_inventory','tool_permission_inventory',
                    'data_class_inventory','residency_proof','redaction_record',
                    'approval_record','ownership_record','oversight_record',
                    'change_history','materiality_verdict',
                    'vulnerability_scan','adversarial_probe',
                    'service_level_attainment','chain_integrity','incident_record'
                )
            );
    """)

    op.execute("""
        DROP TABLE IF EXISTS evidence_checkpoints CASCADE;
        DROP TABLE IF EXISTS evidence_events CASCADE;
        DROP TABLE IF EXISTS evidence_batches CASCADE;

        DROP FUNCTION IF EXISTS ensure_evidence_partition(date) CASCADE;
        DROP FUNCTION IF EXISTS forbid_evidence_mutation() CASCADE;

        DROP TYPE IF EXISTS evidence_outcome;
        DROP TYPE IF EXISTS evidence_kind;
    """)
