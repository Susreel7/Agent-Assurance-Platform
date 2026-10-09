"""Runtime operations: what the fleet actually did, what it cost, which tools it called.

Everything before this revision describes agents as *declared*: a descriptor, a bill of
materials, an approval. Nothing recorded what an agent did after it shipped, so the
console could say an agent was accredited but not whether it had run this week, cost
anything, or called a tool nobody declared. This revision adds that half.

Two tables, and the split between them is the only interesting decision here.

**`agent_runs` is one row per invocation.** For a LangGraph agent that is one graph
invocation; `step_count` is node executions and `tool_call_count` is tool and MCP calls
made inside it. Per-invocation granularity is kept because the questions people actually
ask are per-invocation — which run failed, what did that run cost, how long did it take —
and because a rollup cannot answer them afterwards.

**`tool_usage_daily` is a rollup, not a row per call.** A row per tool call is
runs times tools, which makes it the largest table in the product by an order of
magnitude, and no screen asks a question a daily bucket cannot answer: which tools are
used, which fail, which get blocked. If per-call detail is ever needed it belongs in
evidence, where it would arrive with a digest and a decision rather than as a metric.

**Runs are not evidence.** Evidence is the tamper-evident record that gets shown to an
auditor; runs are operational telemetry that gets graphed. They are separate tables
because they have different retention, different volume and different trust
requirements. But AGENTS.md rule 5 still applies in full: every text field below is
bounded to a length no prompt, completion or tool argument fits into, and there is
nowhere to put one. A run says *that* a model was called and what it cost, never what
was said to it.

**Money is integer micros of USD.** `cost_micros bigint`. Floating point money summed
over a million rows disagrees with itself depending on the order of summation, which is
the one property a cost report must not have.

Hand-written per AGENTS.md rule 7, and wants reading line by line before it is applied.

Revision ID: 0008_operations
Revises: 0007_identity_bindings
Create Date: 2026-09-14
"""

from __future__ import annotations

from alembic import op

revision = "0008_operations"
down_revision = "0007_identity_bindings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # Enums
    #
    # `running` is a real outcome rather than a null, because "how many agents are
    # working right now" is a question the console asks on every load and a null
    # would make it a scan for absence instead of an index lookup.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TYPE run_outcome AS ENUM (
            'running',
            'succeeded',
            'failed',
            'refused',
            'timed_out',
            'cancelled'
        );
    """)

    # `refused` is separated from `failed` deliberately. An agent declining to act --
    # because a guardrail fired or a policy denied it -- is the system working, and
    # folding it into failures makes a well-governed estate look broken.

    # Where a tool came from. `mcp` is the one that matters for this product: an MCP
    # server is a dependency with its own supply chain, and the tools it exposes can
    # change without the agent's descriptor changing at all.
    op.execute("""
        CREATE TYPE tool_surface AS ENUM (
            'mcp',
            'native',
            'retrieval',
            'sub_agent',
            'handoff'
        );
    """)

    # ------------------------------------------------------------------
    # agent_runs. Partitioned monthly by started_at.
    #
    # Partitioned for the same reason evidence is: retention is expressed in months,
    # and dropping an expired month should be a DROP TABLE rather than a DELETE across
    # millions of rows. The primary key must include the partition key, hence
    # (id, started_at).
    #
    # agent_id carries a foreign key, unlike evidence_events.agent_id. Evidence can
    # legitimately predate registration -- a discovery scan finds an agent nobody
    # declared -- but a run is reported by the agent itself or by a collector watching
    # it, and both know which registered agent they are. An unknown agent_id here is a
    # misconfigured reporter, and failing the ingest says so.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE agent_runs (
            id                uuid NOT NULL DEFAULT gen_random_uuid(),
            org_id            uuid NOT NULL,

            agent_id          uuid NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
            -- Nullable: a reporter that knows the agent may not know which published
            -- version is live, and refusing the run over that loses the metric.
            agent_version_id  uuid REFERENCES agent_versions(id) ON DELETE SET NULL,

            environment       lifecycle_state NOT NULL,

            started_at        timestamptz NOT NULL,
            ended_at          timestamptz,
            duration_ms       integer,

            outcome           run_outcome NOT NULL DEFAULT 'running',

            -- Shape of the work. For LangGraph, step_count is node executions.
            step_count        integer NOT NULL DEFAULT 0,
            tool_call_count   integer NOT NULL DEFAULT 0,
            retry_count       integer NOT NULL DEFAULT 0,

            -- Cost. Integer micros of USD; see the module docstring.
            model             text,
            tokens_in         bigint NOT NULL DEFAULT 0,
            tokens_out        bigint NOT NULL DEFAULT 0,
            cost_micros       bigint NOT NULL DEFAULT 0,

            -- Governance signals, which is what makes this table ours rather than an
            -- ordinary APM table. A run that a human had to take over, and a run a
            -- guardrail intervened in, are the two facts an assurance report needs.
            escalated         boolean NOT NULL DEFAULT false,
            guardrail_blocks  integer NOT NULL DEFAULT 0,

            -- A classification, never a message. 'tool_timeout', 'rate_limited',
            -- 'context_overflow'. A stack trace or a model refusal string would be
            -- customer content and is refused by the length bound below.
            error_kind        text,

            -- Correlates to a trace in whatever the customer already runs. We store
            -- the id so an operator can follow it there; we do not store spans.
            trace_id          text,

            -- How we learned. 'sdk', 'otel', 'collector', 'manual', 'seed'.
            reported_by       text NOT NULL DEFAULT 'sdk',
            recorded_at       timestamptz NOT NULL DEFAULT now(),

            PRIMARY KEY (id, started_at),

            CONSTRAINT agent_runs_window_sane CHECK (
                ended_at IS NULL OR ended_at >= started_at
            ),
            -- A run is either still going, or it finished and knows when. Without this
            -- the "active now" count and the duration histogram disagree about the
            -- same row.
            CONSTRAINT agent_runs_terminal_has_end CHECK (
                (outcome = 'running') = (ended_at IS NULL)
            ),
            CONSTRAINT agent_runs_counts_sane CHECK (
                duration_ms      IS NULL OR duration_ms >= 0
            ),
            CONSTRAINT agent_runs_shape_sane CHECK (
                step_count       >= 0 AND
                tool_call_count  >= 0 AND
                retry_count      >= 0 AND
                guardrail_blocks >= 0
            ),
            CONSTRAINT agent_runs_cost_sane CHECK (
                tokens_in   >= 0 AND
                tokens_out  >= 0 AND
                cost_micros >= 0
            ),

            -- AGENTS.md rule 5, enforced by the schema and not only by review. These
            -- bounds are what make this table approvable inside a regulated estate.
            CONSTRAINT agent_runs_no_content CHECK (
                length(coalesce(model, ''))      <= 128 AND
                length(coalesce(error_kind, '')) <= 64  AND
                length(coalesce(trace_id, ''))   <= 128 AND
                length(reported_by)              <= 32
            )
        ) PARTITION BY RANGE (started_at);
    """)

    # Declared on the parent so every partition inherits them. started_at trails each
    # composite because every question about runs is time-bounded.
    op.execute("""
        CREATE INDEX agent_runs_org_time_idx
            ON agent_runs (org_id, started_at DESC);

        CREATE INDEX agent_runs_agent_time_idx
            ON agent_runs (agent_id, started_at DESC);

        CREATE INDEX agent_runs_env_time_idx
            ON agent_runs (org_id, environment, started_at DESC);

        CREATE INDEX agent_runs_outcome_time_idx
            ON agent_runs (org_id, outcome, started_at DESC);

        -- "What is running right now". Partial, so it stays proportional to the number
        -- of in-flight runs rather than to the whole history.
        CREATE INDEX agent_runs_active_idx
            ON agent_runs (org_id, started_at DESC) WHERE outcome = 'running';

        CREATE INDEX agent_runs_trace_idx
            ON agent_runs (trace_id) WHERE trace_id IS NOT NULL;
    """)

    # ------------------------------------------------------------------
    # Immutability, but only once terminal.
    #
    # Unlike evidence, a run legitimately changes: it is created when work starts and
    # updated when it ends. What must not change is a run that has already reported its
    # outcome, because that is what the cost report and the reliability figure are
    # computed from. So the trigger permits exactly one transition -- out of `running`
    # -- and freezes the row after it.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE OR REPLACE FUNCTION forbid_terminal_run_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                -- Retention drops whole partitions; maintenance moves rows out of the
                -- default partition. Neither goes row by row through this path.
                IF coalesce(current_setting('app.partition_maintenance', true), 'off')
                   = 'on' THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION 'agent_runs is append-only: delete is forbidden'
                    USING HINT = 'expire runs by dropping a partition';
            END IF;

            IF OLD.outcome <> 'running' THEN
                RAISE EXCEPTION 'run % already finished as %, and is immutable',
                    OLD.id, OLD.outcome
                    USING HINT = 'report a new run rather than rewriting this one';
            END IF;

            -- Identity and placement are fixed even while the run is in flight. Moving
            -- a run between agents or organisations mid-flight would rewrite history
            -- that has already been graphed.
            IF  NEW.id          IS DISTINCT FROM OLD.id
             OR NEW.org_id      IS DISTINCT FROM OLD.org_id
             OR NEW.agent_id    IS DISTINCT FROM OLD.agent_id
             OR NEW.started_at  IS DISTINCT FROM OLD.started_at
            THEN
                RAISE EXCEPTION 'run identity is immutable';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER agent_runs_terminal_immutable
            BEFORE UPDATE OR DELETE ON agent_runs
            FOR EACH ROW EXECUTE FUNCTION forbid_terminal_run_mutation();
    """)

    # ------------------------------------------------------------------
    # Partition management.
    #
    # The same shape as ensure_evidence_partition, written out again rather than
    # generalised. A shared helper would have to take a table name and build dynamic
    # SQL around an identifier, and two twenty-line functions are easier to review than
    # one that constructs statements from arguments.
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE agent_runs_default PARTITION OF agent_runs DEFAULT;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION ensure_run_partition(p_month date)
        RETURNS text AS $$
        DECLARE
            lo    date := date_trunc('month', p_month)::date;
            hi    date := (date_trunc('month', p_month) + interval '1 month')::date;
            name  text := 'agent_runs_' || to_char(lo, 'YYYYMM');
            moved integer := 0;
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_class WHERE relname = name) THEN
                RETURN name;
            END IF;

            -- Built detached, filled from the default partition, then attached.
            -- Attaching first would make the ATTACH scan the default partition and
            -- fail on the very rows being rescued.
            EXECUTE format(
                'CREATE TABLE %I (LIKE agent_runs INCLUDING DEFAULTS '
                'INCLUDING CONSTRAINTS)', name);

            SET LOCAL app.partition_maintenance = 'on';

            EXECUTE format(
                'INSERT INTO %I SELECT * FROM agent_runs_default '
                'WHERE started_at >= %L AND started_at < %L', name, lo, hi);
            GET DIAGNOSTICS moved = ROW_COUNT;

            EXECUTE format(
                'DELETE FROM agent_runs_default '
                'WHERE started_at >= %L AND started_at < %L', lo, hi);

            EXECUTE format(
                'ALTER TABLE agent_runs ATTACH PARTITION %I '
                'FOR VALUES FROM (%L) TO (%L)', name, lo, hi);

            RETURN name || ' (' || moved || ' rows recovered from default)';
        END;
        $$ LANGUAGE plpgsql;
    """)

    # Thirteen months back so a year of history can be imported and compared
    # year-on-year, three ahead so the worker's monthly sweep is a safety net rather
    # than load-bearing.
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
                PERFORM ensure_run_partition(m);
            END LOOP;
        END $$;
    """)

    # ------------------------------------------------------------------
    # tool_usage_daily.
    #
    # Accumulating, so no immutability trigger: ingest adds to today's bucket with an
    # upsert. That is the opposite rule from every other table in this schema, which is
    # why it is stated here rather than left to be inferred -- these are metrics, and a
    # metric that cannot be incremented is not one.
    #
    # server_name is NOT NULL with an empty-string default rather than nullable. The
    # uniqueness of a bucket depends on it, and a nullable column in a unique
    # constraint makes every row with no server distinct from every other, so the
    # upsert would insert a new row per call instead of incrementing. Empty means "no
    # server: a tool defined in the agent's own code".
    # ------------------------------------------------------------------
    op.execute("""
        CREATE TABLE tool_usage_daily (
            id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id            uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            agent_id          uuid NOT NULL REFERENCES agents(id) ON DELETE CASCADE,

            day               date NOT NULL,

            surface           tool_surface NOT NULL,
            server_name       text NOT NULL DEFAULT '',
            tool_name         text NOT NULL,

            calls             bigint NOT NULL DEFAULT 0,
            errors            bigint NOT NULL DEFAULT 0,
            -- Blocked by policy rather than broken. Kept apart from errors because a
            -- denial is the product working and an error is not.
            denied            bigint NOT NULL DEFAULT 0,

            -- Sum and max, not a percentile. A percentile cannot be derived from daily
            -- buckets after the fact, and storing one that was computed per-batch and
            -- then averaged would be a number that looks precise and means nothing.
            total_duration_ms bigint NOT NULL DEFAULT 0,
            max_duration_ms   integer NOT NULL DEFAULT 0,

            first_seen_at     timestamptz NOT NULL DEFAULT now(),
            last_seen_at      timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT tool_usage_daily_bucket_unique
                UNIQUE (org_id, agent_id, day, surface, server_name, tool_name),

            CONSTRAINT tool_usage_daily_counts_sane CHECK (
                calls             >= 0 AND
                errors            >= 0 AND
                denied            >= 0 AND
                total_duration_ms >= 0 AND
                max_duration_ms   >= 0 AND
                errors + denied   <= calls
            ),
            CONSTRAINT tool_usage_daily_names_bounded CHECK (
                length(server_name) <= 128 AND
                length(tool_name)   BETWEEN 1 AND 128
            )
        );

        CREATE INDEX tool_usage_daily_org_day_idx
            ON tool_usage_daily (org_id, day DESC);

        CREATE INDEX tool_usage_daily_agent_day_idx
            ON tool_usage_daily (agent_id, day DESC);

        -- The estate-wide question: which tool, across every agent, is failing.
        CREATE INDEX tool_usage_daily_tool_idx
            ON tool_usage_daily (org_id, surface, server_name, tool_name);
    """)

    # ------------------------------------------------------------------
    # Row-level security
    # ------------------------------------------------------------------
    for table in ("agent_runs", "tool_usage_daily"):
        op.execute(f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY {table}_tenant_isolation ON {table}
                USING (current_org_matches(org_id))
                WITH CHECK (current_org_matches(org_id));
        """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS tool_usage_daily CASCADE;
        DROP TABLE IF EXISTS agent_runs CASCADE;

        DROP FUNCTION IF EXISTS ensure_run_partition(date) CASCADE;
        DROP FUNCTION IF EXISTS forbid_terminal_run_mutation() CASCADE;

        DROP TYPE IF EXISTS tool_surface;
        DROP TYPE IF EXISTS run_outcome;
    """)
