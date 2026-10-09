"""Inside a run: the steps a graph actually walked.

`0008` records that a run happened, what it cost and how it ended. That answers every
estate-level question and none of the ones asked about a *particular* run, which are the
only questions anybody has once something goes wrong: which node failed, what did it call
before it failed, where did the four minutes go, why did it retry twice.

This revision adds one row per step. For a LangGraph agent a step is a node execution, a
tool or MCP call made inside a node, or a model call; the callback handler that reports it
already receives exactly these events and already knows the node name, so nothing here
asks a reporter for something it has to derive.

**Why a row per step, when `0008` argued for a daily rollup of tool calls.** Because the
question is different. `tool_usage_daily` answers "which tools does the estate use and
which of them fail", and a bucket answers that as well as rows would at a fraction of the
size. A step table answers "what happened in *this* run", and there is no aggregate that
can answer it afterwards -- the ordering and the parentage are the content. So both exist,
and neither is derivable from the other.

Volume is the obvious objection. A step table is runs times steps: on the seeded demo
estate, about 11k runs become about 90k steps. Partitioned monthly like its parent, so
retention is a DROP TABLE and the working set is the current month. The row is deliberately
narrow -- integers, enums and two bounded names -- because the width of this row is the one
thing that decides whether a year of history is affordable.

**`parent_seq` rather than a closure table or a path string.** A LangGraph trace is two
levels deep in practice: a node, and the calls made inside it. One nullable integer
pointing at another step's `seq` in the same run renders that, and a run detail screen
reads it with one pass and no recursion. If somebody later builds agents that nest ten
deep this is the wrong shape, and it will be obvious, and the fix is a migration rather
than a rescue.

**Reuses `run_outcome` instead of adding `step_outcome`.** A step succeeds, fails, is
refused by a guardrail, times out, or is still running -- the same six words, meaning the
same six things. A parallel enum would drift, and the console's colour for `refused` would
have to be declared twice.

**AGENTS.md rule 5 applies here more sharply than anywhere else in the schema**, because a
step is the closest this product ever gets to a prompt. `name` is a node or tool
identifier bounded to 128 characters; `error_kind` is a classification bounded to 64.
There is no arguments column, no result column, and no room to smuggle one in -- a
reporter holding a model's output has nowhere to put it, which is the point.

Hand-written per AGENTS.md rule 7, and wants reading line by line before it is applied.

Revision ID: 0009_run_steps
Revises: 0008_operations
Create Date: 2026-09-14
"""

from __future__ import annotations

from alembic import op

revision = "0009_run_steps"
down_revision = "0008_operations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # What kind of step this is.
    #
    # `node` is the LangGraph node itself. `tool` and `mcp_tool` are split because the
    # whole product turns on the difference: a native tool is code the team wrote and
    # ships in its own descriptor, while an MCP tool came from a server with its own
    # supply chain that can change what it exposes without anybody's descriptor
    # changing. Collapsing them would push that distinction into `surface` and make
    # every "which of these is third-party" query a two-column test.
    #
    # `guardrail` earns a kind rather than a boolean because a refusal has a location:
    # knowing a run was blocked is much less useful than knowing which check blocked it
    # and what had already happened by then.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TYPE step_kind AS ENUM (
            'node',
            'llm',
            'tool',
            'mcp_tool',
            'retrieval',
            'guardrail',
            'handoff',
            'sub_agent'
        );
    """)

    # ------------------------------------------------------------------
    # run_steps. Partitioned monthly by started_at.
    #
    # No foreign key to agent_runs, and that is deliberate rather than an oversight.
    # agent_runs is keyed (id, started_at), so the reference would have to carry the
    # parent's start as well -- and worse, retention drops agent_runs partitions, which
    # a dependent foreign key turns from a DROP TABLE into a failure or a cascade
    # nobody asked for. Partitioning both tables on the same clock aligns their
    # retention by construction, which is the property the foreign key was wanted for.
    #
    # The foreign key to agents is kept, for the same reason 0008 keeps it: a step is
    # reported by the agent or by a collector watching it, and both know which
    # registered agent they are. An unknown agent here is a misconfigured reporter.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE run_steps (
            id              uuid NOT NULL DEFAULT gen_random_uuid(),
            org_id          uuid NOT NULL,

            run_id          uuid NOT NULL,
            agent_id        uuid NOT NULL REFERENCES agents(id) ON DELETE CASCADE,

            -- Ordinal within the run, chosen by the reporter. It is the reporter's
            -- sequence counter, not a timestamp ordering: two steps can start in the
            -- same millisecond, and concurrent branches of a graph routinely do.
            seq             integer NOT NULL,

            -- The step this one happened inside -- a node, for a tool call. NULL for a
            -- top-level step. Points at another step's seq in the same run; not a
            -- foreign key, because the parent may arrive in the same batch and
            -- ordering within a batch is not something a reporter should have to
            -- guarantee.
            parent_seq      integer,

            kind            step_kind NOT NULL,

            -- The node name, the tool name, the model name. One column rather than
            -- three nullable ones, because every screen renders it in the same place
            -- and a three-way coalesce in every query is worse than a name whose
            -- meaning depends on kind.
            name            text NOT NULL,

            -- Where a tool came from, when this step is one. NULL for a node.
            surface         tool_surface,
            server_name     text NOT NULL DEFAULT '',

            started_at      timestamptz NOT NULL,
            ended_at        timestamptz,
            duration_ms     integer,

            outcome         run_outcome NOT NULL DEFAULT 'running',

            -- Which try this is. A LangGraph node that retries on a tool timeout
            -- produces several steps with the same name, and a timeline that cannot
            -- tell a retry from a loop iteration is a timeline people misread.
            attempt         integer NOT NULL DEFAULT 1,

            model           text,
            tokens_in       bigint NOT NULL DEFAULT 0,
            tokens_out      bigint NOT NULL DEFAULT 0,
            cost_micros     bigint NOT NULL DEFAULT 0,

            error_kind      text,
            recorded_at     timestamptz NOT NULL DEFAULT now(),

            PRIMARY KEY (id, started_at),

            -- The upsert's conflict target, and what makes a replayed batch idempotent.
            -- started_at is in it because a unique constraint on a partitioned table
            -- must include the partition key; it costs nothing, because a replay of a
            -- step carries the same start it carried the first time.
            CONSTRAINT run_steps_seq_unique UNIQUE (org_id, run_id, seq, started_at),

            CONSTRAINT run_steps_window_sane CHECK (
                ended_at IS NULL OR ended_at >= started_at
            ),
            -- The same rule as agent_runs: either running, or finished and knows when.
            CONSTRAINT run_steps_terminal_has_end CHECK (
                (outcome = 'running') = (ended_at IS NULL)
            ),
            CONSTRAINT run_steps_counts_sane CHECK (
                seq         >= 0 AND
                attempt     >= 1 AND
                (parent_seq IS NULL OR parent_seq <> seq) AND
                (duration_ms IS NULL OR duration_ms >= 0) AND
                tokens_in   >= 0 AND
                tokens_out  >= 0 AND
                cost_micros >= 0
            ),
            -- A node has no tool surface and a tool has one. Enforced here because the
            -- run detail screen groups by surface and a node that claimed to be an MCP
            -- call would appear under a server that never ran it.
            CONSTRAINT run_steps_surface_matches_kind CHECK (
                (kind IN ('tool', 'mcp_tool', 'retrieval')) = (surface IS NOT NULL)
            ),
            -- An MCP call comes from a named server. Without this a reporter can log an
            -- MCP step with no provenance, which is the one thing this table exists to
            -- make impossible to lose.
            CONSTRAINT run_steps_mcp_names_its_server CHECK (
                kind <> 'mcp_tool' OR length(server_name) > 0
            ),

            -- AGENTS.md rule 5. There is no arguments column and no result column; these
            -- bounds are what stop the two text columns that do exist from becoming one.
            CONSTRAINT run_steps_no_content CHECK (
                length(name)                     BETWEEN 1 AND 128 AND
                length(server_name)              <= 128 AND
                length(coalesce(model, ''))      <= 128 AND
                length(coalesce(error_kind, '')) <= 64
            )
        ) PARTITION BY RANGE (started_at);
    """)

    op.execute("""
        -- The run detail screen's only query: every step of one run, in order.
        CREATE INDEX run_steps_run_idx
            ON run_steps (run_id, seq);

        -- "Which node is slow", "which node fails", across an agent. The kind is in the
        -- key because these questions are always asked of nodes or always of tools,
        -- never of both at once.
        CREATE INDEX run_steps_agent_name_idx
            ON run_steps (agent_id, kind, name, started_at DESC);

        CREATE INDEX run_steps_org_time_idx
            ON run_steps (org_id, started_at DESC);

        -- Failures, for the error breakdown. Partial, so it stays proportional to the
        -- number of failures rather than to the whole history.
        CREATE INDEX run_steps_failed_idx
            ON run_steps (org_id, started_at DESC)
            WHERE outcome NOT IN ('running', 'succeeded');
    """)

    # ------------------------------------------------------------------
    # Immutability once terminal. The same rule as agent_runs, written out again
    # rather than generalised -- 0008 made that argument and it has not changed: a
    # shared helper would have to build dynamic SQL around a table name, and two
    # readable functions beat one clever one.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION forbid_terminal_step_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF coalesce(current_setting('app.partition_maintenance', true), 'off')
                   = 'on' THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION 'run_steps is append-only: delete is forbidden'
                    USING HINT = 'expire steps by dropping a partition';
            END IF;

            IF OLD.outcome <> 'running' THEN
                RAISE EXCEPTION 'step %/% already finished as %, and is immutable',
                    OLD.run_id, OLD.seq, OLD.outcome
                    USING HINT = 'report a new attempt rather than rewriting this one';
            END IF;

            IF  NEW.id         IS DISTINCT FROM OLD.id
             OR NEW.org_id     IS DISTINCT FROM OLD.org_id
             OR NEW.run_id     IS DISTINCT FROM OLD.run_id
             OR NEW.seq        IS DISTINCT FROM OLD.seq
             OR NEW.started_at IS DISTINCT FROM OLD.started_at
            THEN
                RAISE EXCEPTION 'step identity is immutable';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER run_steps_terminal_immutable
            BEFORE UPDATE OR DELETE ON run_steps
            FOR EACH ROW EXECUTE FUNCTION forbid_terminal_step_mutation();
    """)

    # ------------------------------------------------------------------
    # Partition management. Mirrors ensure_run_partition exactly.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE run_steps_default PARTITION OF run_steps DEFAULT;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION ensure_run_step_partition(p_month date)
        RETURNS text AS $$
        DECLARE
            lo    date := date_trunc('month', p_month)::date;
            hi    date := (date_trunc('month', p_month) + interval '1 month')::date;
            name  text := 'run_steps_' || to_char(lo, 'YYYYMM');
            moved integer := 0;
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_class WHERE relname = name) THEN
                RETURN name;
            END IF;

            -- Built detached, filled from the default partition, then attached.
            -- Attaching first would make the ATTACH scan the default partition and
            -- fail on the very rows being rescued.
            EXECUTE format(
                'CREATE TABLE %I (LIKE run_steps INCLUDING DEFAULTS '
                'INCLUDING CONSTRAINTS)', name);

            SET LOCAL app.partition_maintenance = 'on';

            EXECUTE format(
                'INSERT INTO %I SELECT * FROM run_steps_default '
                'WHERE started_at >= %L AND started_at < %L', name, lo, hi);
            GET DIAGNOSTICS moved = ROW_COUNT;

            EXECUTE format(
                'DELETE FROM run_steps_default '
                'WHERE started_at >= %L AND started_at < %L', lo, hi);

            EXECUTE format(
                'ALTER TABLE run_steps ATTACH PARTITION %I '
                'FOR VALUES FROM (%L) TO (%L)', name, lo, hi);

            RETURN name || ' (' || moved || ' rows recovered from default)';
        END;
        $$ LANGUAGE plpgsql;
    """)

    # The same span as agent_runs, so a run and its steps are never in a month where
    # one of them has a partition and the other does not.
    op.execute("""
        DO $$
        DECLARE m date;
        BEGIN
            FOR m IN
                SELECT generate_series(
                    date_trunc('month', now()) - interval '13 months',
                    date_trunc('month', now()) + interval '3 months',
                    interval '1 month'
                )::date
            LOOP
                PERFORM ensure_run_step_partition(m);
            END LOOP;
        END $$;
    """)

    # ------------------------------------------------------------------
    # Row-level security
    # ------------------------------------------------------------------
    op.execute("""
        ALTER TABLE run_steps ENABLE ROW LEVEL SECURITY;
        ALTER TABLE run_steps FORCE ROW LEVEL SECURITY;
        CREATE POLICY run_steps_tenant_isolation ON run_steps
            USING (current_org_matches(org_id))
            WITH CHECK (current_org_matches(org_id));
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS run_steps CASCADE;

        DROP FUNCTION IF EXISTS ensure_run_step_partition(date) CASCADE;
        DROP FUNCTION IF EXISTS forbid_terminal_step_mutation() CASCADE;

        DROP TYPE IF EXISTS step_kind;
    """)
