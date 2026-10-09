"""The agent action ledger: one row per capability invocation, content-free, append-only.

`0023` built the identity chain. This is the thing that hangs off the end of it, and it
is the MVP (`design/17` §7). One envelope — ``aap.action.v1``, specified in
`design/15-capability-governance.md` §9 — for every capability kind, so an MCP tool call,
a shell command and an outbound HTTP request are one table, one index, one screen and one
policy model rather than three of each.

**What this table is for, in one sentence.** An investigator picks any action from the
last thirty days and reconstructs who, which agent, which version, which capability,
which arguments (by digest), which policy would have applied and at what enforcement
grade — without the product ever having stored a prompt, a completion or a tool argument.
Every column below exists because that sentence needs it, and no column exists for any
other reason.

**Why this is not `evidence_events`.** Evidence is the tamper-evident record an auditor
reads: low volume, Merkle-anchored, hash-chained per batch, and it answers "was the
control in place". This is a security ledger: three orders of magnitude more rows, read
by index during an incident, and it answers "what did the fleet actually do". They have
different volumes, different retention and different readers, so they are different
tables. `design/10` keeps both.

**Why this is not `agent_runs`.** A run is an invocation of an agent and is mutable while
it is in flight. An action is a single already-happened capability invocation and is never
mutable. `agent_runs` also has no notion of a human root, a capability, a decision or an
enforcement grade.

**`enforcement_grade` is mandatory and that is the product.** `design/12`: **A** mediated,
**B** interposed with a real veto, **C** vendor-enforced and attested, **D** observed
afterwards, **E** not covered. A decision without a grade is not a decision, it is a
suggestion, and a coverage number without its denominator does not ship. ``unknown`` is
accepted at ingestion — a collector may know what happened before it knows what it could
have done about it — and ``effective_enforcement_grade()`` below maps it to ``E`` so that
every query counts it honestly. There is no code path in which ``unknown`` reads as
protection.

**Content-freedom is enforced by the schema, not by review.** There is no column for a
prompt, a completion, a file body, a full path, a raw command line or a raw tool argument,
and there is nowhere to put one. ``argument_digest`` is a digest. ``argument_facets`` is
an allow-listed, type-checked, length-bounded object validated by
``agent_action_facets_valid()``: an unrecognised key is a constraint violation, not a
convenient extension point. This is what makes the collector approvable inside a regulated
estate, and it is why the claim "prove you don't store our code" has a schema-level answer
(`design/17` §8, objection 24).

Two fields from `design/15` §9 are deliberately **not** here. ``payload_ref`` is omitted
because the MVP has no audited-reveal path for it to point at, and a pointer with no
resolver is an invitation to build one. ``provenance.signature`` is omitted because
collector signing keys are V1; ``prev_event_hash`` plus ``event_hash`` already make
suppression detectable (threat model AP-9), which is the property the MVP needs.

**Nothing here is a foreign key except ``org_id``.** Deliberate, and the same reasoning
`design/03` §F gives for its activity table: the ledger must outlive the configuration it
refers to. An action taken by an agent that was later retired, by a member who has since
left, against an MCP server that was deleted, is exactly the action an investigator wants
six months later. A foreign key would either delete it or refuse the deletion, and both
answers are wrong. ``agent_id`` is additionally nullable because a discovered agent is
observed before anyone registers it, and discovery must never block (`design/14` §9).
``human_member_id`` is *not* nullable: an action nobody can be asked about is not evidence,
so M3 rejects it at the boundary rather than writing an unattributable row.

**Idempotency lives in its own table.** ``agent_action_receipts`` is small and
unpartitioned, with ``UNIQUE (org_id, event_id)``. A partition-local unique key on the
ledger cannot do this job: Postgres requires the partition key in a unique constraint on a
partitioned table, so ``UNIQUE (org_id, event_id, occurred_at)`` would happily accept the
same collector event twice with a corrected timestamp — which is precisely the duplicate a
retrying collector produces. Ingestion claims the receipt and writes the action in one
transaction, so a replay collides on the receipt and rolls back both.

Hand-written per AGENTS.md rule 7, and wants reading line by line before it is applied.

Revision ID: 0024_agent_actions_ledger
Revises: 0023_agent_runtime_identity
Create Date: 2026-09-22
"""

from __future__ import annotations

from alembic import op

revision = "0024_agent_actions_ledger"
down_revision = "0023_agent_runtime_identity"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _facet_validator()
    _effective_grade()
    _agent_actions()
    _append_only()
    _partitions()
    _agent_action_receipts()
    _row_level_security()


def _facet_validator() -> None:
    """Allow-list, type-check and length-bound ``argument_facets``.

    A ``jsonb`` column with no validator is an unbounded hole through which the whole
    argument tree arrives one well-meaning commit later. The three lists below are the
    closed vocabulary, and they are kept in step with
    ``app/domains/agent_actions/schemas.py`` by
    ``tests/unit/test_agent_actions.py`` — the only place that can see both. That test
    exists because the same drift has already happened once in this codebase: D-057, the
    audit ``category`` vocabulary, where four of seven values failed at INSERT and the
    trail looked healthy while one subsystem's history silently never landed.

    Answers Q-I from `design/15` §10 at the storage layer: binary, flags, hosts, paths,
    SQL verbs and tables. No shell grammar, and no key that could hold an argument value.

    The bounds here are deliberately slacker than the boundary layer's, in the same
    direction and for the same reason as `0017`'s ``detail`` check: Pydantic measures
    characters, ``pg_column_size`` measures jsonb's binary layout, and equal numbers would
    make some records fail in Postgres after passing validation. A rejection should be a
    422 that names the field, not a constraint violation from inside a batch.
    """
    op.execute("""
        CREATE OR REPLACE FUNCTION agent_action_facets_valid(facets jsonb)
        RETURNS boolean AS $$
        DECLARE
            -- Short bounded strings: a command binary, an HTTP method, a hostname, a
            -- repository name. Never a value an argument could carry.
            text_keys constant text[] := ARRAY[
                'binary', 'method', 'scheme', 'host',
                'repo', 'branch', 'vcs_operation',
                'registry', 'package',
                'cloud_provider', 'cloud_service', 'cloud_operation'
            ];
            -- Counts and shapes. A depth or a length says how big the thing was without
            -- saying what it contained.
            number_keys constant text[] := ARRAY[
                'argv_count', 'port', 'url_path_depth', 'byte_length'
            ];
            -- Short string arrays. `path_roots` is roots only -- '/etc', '~/.aws' -- so a
            -- full path is not representable; `path_classes` is the classification that
            -- actually drives policy.
            array_keys constant text[] := ARRAY[
                'argv_flags', 'path_roots', 'path_classes', 'sql_verbs', 'sql_tables'
            ];
            facet_key   text;
            facet_value jsonb;
            element     jsonb;
        BEGIN
            IF facets IS NULL THEN
                RETURN true;
            END IF;
            IF jsonb_typeof(facets) <> 'object' THEN
                RETURN false;
            END IF;

            FOR facet_key, facet_value IN SELECT * FROM jsonb_each(facets) LOOP
                IF facet_key = ANY (text_keys) THEN
                    IF jsonb_typeof(facet_value) <> 'string'
                       OR length(facet_value #>> '{}') > 256 THEN
                        RETURN false;
                    END IF;
                ELSIF facet_key = ANY (number_keys) THEN
                    IF jsonb_typeof(facet_value) <> 'number' THEN
                        RETURN false;
                    END IF;
                ELSIF facet_key = ANY (array_keys) THEN
                    IF jsonb_typeof(facet_value) <> 'array'
                       OR jsonb_array_length(facet_value) > 32 THEN
                        RETURN false;
                    END IF;
                    FOR element IN SELECT * FROM jsonb_array_elements(facet_value) LOOP
                        IF jsonb_typeof(element) <> 'string'
                           OR length(element #>> '{}') > 64 THEN
                            RETURN false;
                        END IF;
                    END LOOP;
                ELSE
                    -- An unrecognised key. Refusing it is the whole point: the failure
                    -- mode to prevent is a facet map that grows into a payload.
                    RETURN false;
                END IF;
            END LOOP;

            RETURN true;
        END;
        $$ LANGUAGE plpgsql IMMUTABLE;
    """)


def _effective_grade() -> None:
    """``unknown`` reads as ``E``, in one place, for every reader.

    Not a stored generated column, which was the first design. A generated column on a
    partitioned parent has to be reproduced on every partition, and the partition
    maintenance path below builds partitions with ``CREATE TABLE (LIKE ...)`` and fills
    them with ``INSERT ... SELECT *`` — which cannot write a generated column. A function
    keeps the rule in one place without breaking the mechanism that keeps the table
    droppable by month.
    """
    op.execute("""
        CREATE OR REPLACE FUNCTION effective_enforcement_grade(grade text)
        RETURNS text AS $$
            SELECT CASE
                WHEN grade IS NULL OR grade = 'unknown' THEN 'E'
                ELSE grade
            END;
        $$ LANGUAGE sql IMMUTABLE;
    """)


def _agent_actions() -> None:
    """``aap.action.v1``, as rows. Partitioned monthly by ``occurred_at``.

    Partitioned on ``occurred_at`` rather than ``received_at`` because retention is
    written in the customer's terms — "ninety days of actions" — and expiring a month is
    then a ``DROP TABLE`` rather than a delete across hundreds of millions of rows. The
    primary key must contain the partition key, hence ``(id, occurred_at)``.

    Three timestamps, three different questions, deliberately not collapsed (NAMING.md
    §2): ``occurred_at`` is when the agent did it, ``received_at`` is when the collector
    handed it to us — the pair is the clock-skew and suppression-delay forensics — and
    ``recorded_at`` is when this row was written.
    """
    op.execute("""
        CREATE TABLE agent_actions (
            id                   uuid NOT NULL DEFAULT gen_random_uuid(),
            org_id               uuid NOT NULL,

            occurred_at          timestamptz NOT NULL,
            received_at          timestamptz NOT NULL DEFAULT now(),
            recorded_at          timestamptz NOT NULL DEFAULT now(),

            -- ---------------- identity -------------------------------------------
            -- The collector's own idea of this event. Unique per account through
            -- `agent_action_receipts`, not through a constraint here; see the module
            -- docstring for why a partition-local unique key cannot do the job.
            event_id             uuid NOT NULL,
            collector_id         text NOT NULL,
            collector_version    text NOT NULL,

            -- The root of the chain. `design/14` §1: no action without a human.
            human_member_id      uuid NOT NULL,
            root_human_basis     text NOT NULL,

            agent_id             uuid,
            agent_version_id     uuid,
            -- sha256 of the normalised composition, so a row can be checked against the
            -- version it claims. This is the hook declared-versus-observed
            -- reconciliation hangs off in V2.
            composition_digest   bytea,

            instance_id          uuid,
            session_id           uuid,
            task_id              uuid,
            parent_instance_id   uuid,
            delegation_depth     integer NOT NULL DEFAULT 0,

            environment          lifecycle_state NOT NULL,

            -- ---------------- action ---------------------------------------------
            capability_kind      text NOT NULL,
            capability_id        uuid,
            capability_digest    bytea,
            -- The verb, bounded and lower-cased: 'exec', 'get', 'post', 'read',
            -- 'volume_delete'. Not a closed set -- argv and API operation spaces are
            -- open -- but shaped and short, so it cannot carry a command line.
            operation            text NOT NULL,

            resource_kind        text NOT NULL DEFAULT 'unknown',
            resource_class       text NOT NULL DEFAULT 'unknown',
            -- sha256 of the resource identifier. An investigator needs to know that
            -- forty actions touched the *same* resource; the identifier itself, when it
            -- is safe to keep at all, is a bounded facet.
            resource_digest      bytea,
            destination_class    text NOT NULL DEFAULT 'none',
            data_classes         text[] NOT NULL DEFAULT '{}'::text[],
            is_write             boolean NOT NULL DEFAULT false,
            is_irreversible      boolean NOT NULL DEFAULT false,

            -- ---------------- decision -------------------------------------------
            outcome              text NOT NULL,
            reason_code          text,
            enforcement_grade    text NOT NULL,
            policy_id            uuid,
            policy_version       integer,
            matched_grant_id     uuid,
            approval_id          uuid,
            latency_added_ms     integer,

            -- ---------------- risk -----------------------------------------------
            -- Categorical, per `design/14` §8. There is no risk *score* column, and its
            -- absence is the design: a score that gates an action is the control nobody
            -- can explain. Scoring orders a review queue and lives outside this table.
            risk_class           text NOT NULL DEFAULT 'unknown',
            risk_signals         text[] NOT NULL DEFAULT '{}'::text[],
            session_taint        text NOT NULL DEFAULT 'clean',

            -- ---------------- credential -----------------------------------------
            -- A lease reference and nothing else. The broker and `credential_leases` are
            -- V1's; this column is what makes "which credential did this action use, and
            -- what else did that credential do" one query when they arrive.
            credential_lease_id  uuid,

            -- ---------------- privacy --------------------------------------------
            argument_digest      bytea,
            argument_facets      jsonb NOT NULL DEFAULT '{}'::jsonb,
            arguments_truncated  boolean NOT NULL DEFAULT false,

            -- ---------------- provenance -----------------------------------------
            source_harness       text NOT NULL DEFAULT 'unknown',
            -- The harness's own opaque event identifier, kept so a customer can
            -- reconcile our ledger against the vendor's console.
            source_event_id      text,

            -- ---------------- integrity ------------------------------------------
            -- Per-collector chain. A gap is visible; a deleted row is not. Threat model
            -- AP-9: this is what makes evidence *suppression* detectable rather than
            -- merely making tampering hard.
            prev_event_hash      bytea,
            event_hash           bytea NOT NULL,

            -- ---------------- downstream -----------------------------------------
            -- The SDLC join: this action became this commit, in this release. Set at
            -- ingestion when the collector already knows it. The ledger is append-only,
            -- so a link discovered later is a separate correlation row in M5, never an
            -- UPDATE here.
            downstream_mutation_kind text,
            downstream_mutation_ref  text,

            -- ---------------- call outcome ---------------------------------------
            upstream_status      integer,
            bytes_in             bigint,
            bytes_out            bigint,

            PRIMARY KEY (id, occurred_at),

            -- ================ vocabularies =======================================
            -- All `text` + CHECK rather than Postgres enums, per `design/03`: these lists
            -- grow every time a harness or a capability kind is added, and widening a
            -- CHECK is one catalogue statement instead of a type rewrite on a
            -- partitioned table.

            -- `design/15` §3, in full, including the rows we cannot govern. `browser.act`
            -- is listed because an honest gap beats a silent one (Q-J).
            CONSTRAINT agent_actions_capability_kind_valid CHECK (
                capability_kind IN (
                    'model.invoke', 'mcp.tool', 'shell.exec', 'net.http',
                    'fs.read', 'fs.write', 'vcs.write', 'db.query', 'cloud.api',
                    'agent.delegate', 'memory.write', 'retrieval.query',
                    'package.publish', 'browser.act', 'unknown'
                )
            ),
            -- `design/14` §6.2, plus `observed`. `observed` is the MVP's own outcome: the
            -- ledger is read-only, so most rows record an action that happened with no
            -- decision taken. Folding it into `allow` would claim a permission decision
            -- we never made.
            CONSTRAINT agent_actions_outcome_valid CHECK (
                outcome IN (
                    'observed', 'allow', 'annotate', 'mask', 'tokenize',
                    'route_internal', 'require_approval', 'step_up_auth',
                    'rate_limit', 'quarantine', 'deny', 'error'
                )
            ),
            CONSTRAINT agent_actions_grade_valid CHECK (
                enforcement_grade IN ('A', 'B', 'C', 'D', 'E', 'unknown')
            ),
            -- An enforcing outcome at grade E is a contradiction: E means the action was
            -- not covered, so nothing can have refused, masked or rerouted it. `unknown`
            -- reads as E, so it is refused here too. This is the check that stops the
            -- console displaying protection that did not happen.
            --
            -- Grade D is deliberately still allowed. D is "observed afterwards", and a
            -- vendor control that denied something before we heard about it is a real
            -- denial that we did not perform — the grade already says so, and losing the
            -- row would be worse than recording it honestly.
            CONSTRAINT agent_actions_denial_was_enforceable CHECK (
                outcome NOT IN ('deny', 'quarantine', 'mask', 'tokenize',
                                'route_internal', 'rate_limit')
                OR enforcement_grade NOT IN ('E', 'unknown')
            ),
            CONSTRAINT agent_actions_root_basis_valid CHECK (
                root_human_basis IN ('registered_by', 'approved_by', 'triggered_by')
            ),
            CONSTRAINT agent_actions_resource_kind_valid CHECK (
                resource_kind IN (
                    'host', 'path', 'repo', 'database', 'cloud_resource',
                    'model', 'mcp_server', 'package', 'index', 'memory_store',
                    'agent', 'unknown'
                )
            ),
            CONSTRAINT agent_actions_resource_class_valid CHECK (
                resource_class IN ('public', 'internal', 'confidential',
                                   'restricted', 'unknown')
            ),
            CONSTRAINT agent_actions_destination_class_valid CHECK (
                destination_class IN ('none', 'loopback', 'internal',
                                      'external_allowlisted', 'external_unknown')
            ),
            CONSTRAINT agent_actions_risk_class_valid CHECK (
                risk_class IN ('low', 'medium', 'high', 'critical', 'unknown')
            ),
            CONSTRAINT agent_actions_taint_valid CHECK (
                session_taint IN ('clean', 'tainted', 'tainted_with_secrets')
            ),
            -- Kept identical to `agent_instances.harness` in 0023, and
            -- tests/unit/test_agent_actions.py asserts the two lists agree. Two
            -- vocabularies for one fact is how a fleet view and a ledger view come to
            -- disagree about which harnesses exist.
            CONSTRAINT agent_actions_source_harness_valid CHECK (
                source_harness IN ('claude_code', 'cursor', 'copilot', 'codex',
                                   'gemini_cli', 'langgraph', 'sdk', 'ci',
                                   'custom', 'unknown')
            ),
            CONSTRAINT agent_actions_downstream_kind_valid CHECK (
                downstream_mutation_kind IS NULL
                OR downstream_mutation_kind IN (
                    'commit', 'pull_request', 'ticket', 'cloud_resource',
                    'package_version', 'deployment', 'unknown'
                )
            ),
            -- A reference with no kind is unjoinable, and a kind with no reference is a
            -- claim that something downstream changed without saying what.
            CONSTRAINT agent_actions_downstream_paired CHECK (
                (downstream_mutation_kind IS NULL) = (downstream_mutation_ref IS NULL)
            ),
            CONSTRAINT agent_actions_data_classes_known CHECK (
                data_classes <@ ARRAY[
                    'public', 'internal', 'confidential', 'restricted',
                    'pii', 'phi', 'pci', 'secret', 'source_code', 'unknown'
                ]::text[]
            ),
            -- Closed, because these are what policy is written over and what the console
            -- renders as chips. A free-text signal is a signal nobody filters on.
            CONSTRAINT agent_actions_risk_signals_known CHECK (
                risk_signals <@ ARRAY[
                    'session_tainted', 'credential_path_read_in_session',
                    'secret_in_arguments', 'egress_to_unknown_host',
                    'write_to_production', 'irreversible_operation',
                    'undeclared_capability', 'first_seen_capability_for_version',
                    'unparseable_arguments', 'unattested_instance',
                    'elevated_delegation_depth', 'off_hours', 'unknown'
                ]::text[]
            ),

            -- ================ shape ==============================================
            CONSTRAINT agent_actions_operation_shape CHECK (
                operation ~ '^[a-z][a-z0-9_.:-]*$'
            ),
            CONSTRAINT agent_actions_collector_shape CHECK (
                collector_id ~ '^[a-z0-9][a-z0-9_.:-]*$'
            ),
            -- There is deliberately no `received_at >= occurred_at` check. An agent on a
            -- laptop with a drifting clock will report an action from the future, and
            -- that is the *finding* the two timestamps exist to surface, not an error to
            -- reject. Refusing the row would delete the evidence of the skew.
            CONSTRAINT agent_actions_depth_bounded CHECK (
                delegation_depth BETWEEN 0 AND 8
            ),
            CONSTRAINT agent_actions_counters_sane CHECK (
                (latency_added_ms IS NULL OR latency_added_ms >= 0)
                AND (bytes_in IS NULL OR bytes_in >= 0)
                AND (bytes_out IS NULL OR bytes_out >= 0)
                AND (policy_version IS NULL OR policy_version >= 0)
                AND (upstream_status IS NULL OR upstream_status BETWEEN 0 AND 999)
            ),
            -- 32 bytes each, or the chain cannot be walked and the digests cannot be
            -- compared against anything.
            CONSTRAINT agent_actions_digests_sized CHECK (
                octet_length(event_hash) = 32
                AND (prev_event_hash IS NULL OR octet_length(prev_event_hash) = 32)
                AND (argument_digest IS NULL OR octet_length(argument_digest) = 32)
                AND (resource_digest IS NULL OR octet_length(resource_digest) = 32)
                AND (capability_digest IS NULL OR octet_length(capability_digest) = 32)
                AND (composition_digest IS NULL OR octet_length(composition_digest) = 32)
            ),

            -- ================ AGENTS.md rule 5 ===================================
            -- The storage-layer backstop. Every free-ish text column is bounded to a
            -- length no prompt, completion, command line or tool argument fits into, the
            -- facet map is allow-listed by `agent_action_facets_valid`, and the whole
            -- jsonb column is size-capped so twenty short facets cannot add up to a
            -- payload either.
            CONSTRAINT agent_actions_no_content CHECK (
                length(collector_id) BETWEEN 1 AND 64
                AND length(collector_version) BETWEEN 1 AND 32
                AND length(operation) BETWEEN 1 AND 64
                AND length(coalesce(reason_code, '')) <= 64
                AND length(coalesce(source_event_id, '')) <= 200
                AND length(coalesce(downstream_mutation_ref, '')) <= 200
                AND cardinality(data_classes) <= 16
                AND cardinality(risk_signals) <= 16
                AND agent_action_facets_valid(argument_facets)
                AND pg_column_size(argument_facets) <= 4096
            )
        ) PARTITION BY RANGE (occurred_at);
    """)

    # Declared on the parent so every partition inherits them. `occurred_at DESC` trails
    # each composite because every question about the ledger is time-bounded -- an
    # investigation, a coverage report and a retention sweep all ask "in this window".
    op.execute("""
        -- The list. `(org_id, occurred_at DESC, id DESC)` is the keyset tuple the
        -- pagination helper walks, so the index is the sort order and there is no
        -- offset scan at page four hundred.
        CREATE INDEX agent_actions_keyset_idx
            ON agent_actions (org_id, occurred_at DESC, id DESC);

        -- The six investigation paths from `design/14` §1. Each is a single index
        -- lookup by design: "everything this human's agents did in production last
        -- week" must not become a join across three systems.
        CREATE INDEX agent_actions_human_idx
            ON agent_actions (org_id, human_member_id, occurred_at DESC);
        CREATE INDEX agent_actions_agent_idx
            ON agent_actions (org_id, agent_id, occurred_at DESC)
            WHERE agent_id IS NOT NULL;
        CREATE INDEX agent_actions_instance_idx
            ON agent_actions (org_id, instance_id, occurred_at DESC)
            WHERE instance_id IS NOT NULL;
        CREATE INDEX agent_actions_session_idx
            ON agent_actions (org_id, session_id, occurred_at DESC)
            WHERE session_id IS NOT NULL;
        CREATE INDEX agent_actions_capability_idx
            ON agent_actions (org_id, capability_kind, occurred_at DESC);
        -- The collector chain, which is also how `prev_event_hash` is verified: walk
        -- one collector's events in order and look for a break.
        CREATE INDEX agent_actions_collector_chain_idx
            ON agent_actions (org_id, collector_id, occurred_at DESC, id DESC);

        -- What was denied, and what we could not see. The second one is the honesty
        -- query: the size of the ungraded population is the denominator every coverage
        -- number needs.
        CREATE INDEX agent_actions_outcome_idx
            ON agent_actions (org_id, outcome, occurred_at DESC);
        CREATE INDEX agent_actions_ungraded_idx
            ON agent_actions (org_id, occurred_at DESC)
            WHERE enforcement_grade = 'unknown';

        -- "Did anything touch this data class outside its envelope?" -- the residency
        -- and DLP question, which is a containment test rather than an equality one.
        CREATE INDEX agent_actions_data_classes_idx
            ON agent_actions USING gin (data_classes);
    """)


def _append_only() -> None:
    """No UPDATE, ever. No DELETE except dropping or draining a partition.

    Stricter than `0003`'s evidence trigger, which permits the sealer to stamp
    ``batch_id`` after the fact, and stricter than `0008`'s run trigger, which permits a
    run to be closed. Neither exception applies here: an action is already over when it
    is reported, so there is no second write that is not a rewrite of history. A
    correction is a new event.

    The one sanctioned delete is partition maintenance draining rows out of the default
    partition, gated on ``app.partition_maintenance`` exactly as the three existing
    ledgers gate it.

    The trigger is declared on the partitioned parent. Postgres clones row-level triggers
    onto each partition as it is attached, which is the same mechanism `0003` relies on
    and which `tests/sql/invariants.sql` §2 has been exercising since.
    """
    op.execute("""
        CREATE OR REPLACE FUNCTION forbid_agent_ledger_mutation() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF coalesce(current_setting('app.partition_maintenance', true), 'off')
                   = 'on' THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION '% is append-only: delete is forbidden', TG_TABLE_NAME
                    USING HINT = 'expire the ledger by dropping a month partition';
            END IF;

            RAISE EXCEPTION '% is append-only: update is forbidden', TG_TABLE_NAME
                USING HINT = 'a correction is a new event, not an edit';
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER agent_actions_append_only
            BEFORE UPDATE OR DELETE ON agent_actions
            FOR EACH ROW EXECUTE FUNCTION forbid_agent_ledger_mutation();
    """)


def _partitions() -> None:
    """Month partitions, a default to catch the rest, and one function to make more.

    The default partition exists for the same reason evidence has one: losing a security
    event is worse than misfiling it, and a gap in a ledger outlives whatever caused it.
    ``ensure_agent_action_partition`` therefore also *drains* the default partition for
    the month it is creating, which is the step that makes keeping a default safe.

    Unlike `0003` and `0008` this function also enables row-level security on the
    partition it creates. Those two tables carry RLS on the parent only, which covers
    every read that goes through the parent and covers nothing that names a partition
    directly. For a table an incident responder will query by month, and which will be
    the largest store of security-relevant rows in the product, the policy belongs on
    every relation that can be named. That is also why the drain runs under
    ``app.bypass_rls``: the maintenance transaction has no tenant, and it is moving rows
    for all of them.

    Four months are created: last, current and the next two. `0003` and `0008` pre-create
    a year of history because a customer can import it; there is no ledger history to
    import — a collector starts producing when it is installed — so the only requirement
    is that today and the near future never land in the default partition, plus one month
    behind for a collector replaying a backlog across a month boundary.
    """
    op.execute("""
        CREATE TABLE agent_actions_default PARTITION OF agent_actions DEFAULT;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION ensure_agent_action_partition(p_month date)
        RETURNS text AS $$
        DECLARE
            lo    date := date_trunc('month', p_month)::date;
            hi    date := (date_trunc('month', p_month) + interval '1 month')::date;
            name  text := 'agent_actions_' || to_char(lo, 'YYYYMM');
            moved integer := 0;
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_class WHERE relname = name) THEN
                RETURN name;
            END IF;

            -- Built detached, filled from the default partition, then attached.
            -- Attaching first would make the ATTACH scan the default partition and fail
            -- on the very rows being rescued.
            EXECUTE format(
                'CREATE TABLE %I (LIKE agent_actions INCLUDING DEFAULTS '
                'INCLUDING CONSTRAINTS)', name);

            SET LOCAL app.partition_maintenance = 'on';
            SET LOCAL app.bypass_rls = 'on';

            EXECUTE format(
                'INSERT INTO %I SELECT * FROM agent_actions_default '
                'WHERE occurred_at >= %L AND occurred_at < %L', name, lo, hi);
            GET DIAGNOSTICS moved = ROW_COUNT;

            EXECUTE format(
                'DELETE FROM agent_actions_default '
                'WHERE occurred_at >= %L AND occurred_at < %L', lo, hi);

            EXECUTE format(
                'ALTER TABLE agent_actions ATTACH PARTITION %I '
                'FOR VALUES FROM (%L) TO (%L)', name, lo, hi);

            -- Put both back before returning. `SET LOCAL` lasts to the end of the
            -- caller's transaction, and a worker that calls this from inside a request
            -- transaction would otherwise carry an RLS bypass into whatever it does
            -- next. The existing three maintenance functions leave their flag set; this
            -- one does not, because this one also bypasses tenant isolation.
            SET LOCAL app.partition_maintenance = 'off';
            SET LOCAL app.bypass_rls = 'off';

            EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', name);
            EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', name);
            EXECUTE format(
                'CREATE POLICY %I ON %I '
                'USING (current_org_matches(org_id)) '
                'WITH CHECK (current_org_matches(org_id))',
                name || '_tenant_isolation', name);

            RETURN name || ' (' || moved || ' rows recovered from default)';
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        DO $$
        DECLARE m date;
        BEGIN
            FOR m IN
                SELECT generate_series(
                    date_trunc('month', now()) - interval '1 month',
                    date_trunc('month', now()) + interval '2 months',
                    interval '1 month'
                )::date
            LOOP
                PERFORM ensure_agent_action_partition(m);
            END LOOP;
        END $$;
    """)


def _agent_action_receipts() -> None:
    """The idempotency registry. Small, unpartitioned, one row per accepted event.

    Why this exists at all is in the module docstring: a unique constraint on a
    partitioned table must contain the partition key, so the ledger itself cannot hold
    ``UNIQUE (org_id, event_id)`` and ``UNIQUE (org_id, event_id, occurred_at)`` would
    accept a retried event whose timestamp had been corrected on the way through.

    ``action_id`` plus ``action_occurred_at`` is the address of the row this receipt
    claims: the partition and the id within it. That pair is what turns "this event is
    already ingested" into "and here is the row", which is the answer a retrying
    collector needs in order to stop retrying.

    Append-only under the same trigger as the ledger, so a receipt cannot be re-pointed
    at a different action after the fact. Retention drops receipts alongside the
    partition they refer to, under ``app.partition_maintenance``.
    """
    op.execute("""
        CREATE TABLE agent_action_receipts (
            id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id             uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

            event_id           uuid NOT NULL,
            collector_id       text NOT NULL,

            action_id          uuid NOT NULL,
            action_occurred_at timestamptz NOT NULL,

            claimed_at         timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_action_receipts_event_key UNIQUE (org_id, event_id),
            CONSTRAINT agent_action_receipts_collector_shape CHECK (
                collector_id ~ '^[a-z0-9][a-z0-9_.:-]*$'
                AND length(collector_id) BETWEEN 1 AND 64
            )
        );

        -- Retention: drop the receipts for a month when its partition goes.
        CREATE INDEX agent_action_receipts_month_idx
            ON agent_action_receipts (action_occurred_at);
        -- "Which action did this collector event become?"
        CREATE INDEX agent_action_receipts_action_idx
            ON agent_action_receipts (org_id, action_id);

        CREATE TRIGGER agent_action_receipts_append_only
            BEFORE UPDATE OR DELETE ON agent_action_receipts
            FOR EACH ROW EXECUTE FUNCTION forbid_agent_ledger_mutation();
    """)


def _row_level_security() -> None:
    """Parent, default partition, every month partition, and the receipt registry.

    The month partitions created above already carry their own policy, applied by
    ``ensure_agent_action_partition``. This loop covers the parent, the default partition
    and the receipts table, and then re-asserts the policy on any partition that somehow
    lacks one — which is cheap and means a database that was built before the function
    grew that step ends up in the same state as a fresh one.
    """
    for table in ("agent_actions", "agent_actions_default", "agent_action_receipts"):
        op.execute(f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY {table}_tenant_isolation ON {table}
                USING (current_org_matches(org_id))
                WITH CHECK (current_org_matches(org_id));
        """)

    op.execute("""
        DO $$
        DECLARE part text;
        BEGIN
            FOR part IN
                SELECT c.relname
                  FROM pg_class c
                  JOIN pg_inherits i ON i.inhrelid = c.oid
                  JOIN pg_class p ON p.oid = i.inhparent
                 WHERE p.relname = 'agent_actions'
                   AND NOT c.relrowsecurity
            LOOP
                EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', part);
                EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', part);
                EXECUTE format(
                    'CREATE POLICY %I ON %I '
                    'USING (current_org_matches(org_id)) '
                    'WITH CHECK (current_org_matches(org_id))',
                    part || '_tenant_isolation', part);
            END LOOP;
        END $$;
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS agent_action_receipts CASCADE;
        DROP TABLE IF EXISTS agent_actions CASCADE;

        DROP FUNCTION IF EXISTS ensure_agent_action_partition(date) CASCADE;
        DROP FUNCTION IF EXISTS forbid_agent_ledger_mutation() CASCADE;
        DROP FUNCTION IF EXISTS effective_enforcement_grade(text) CASCADE;
        DROP FUNCTION IF EXISTS agent_action_facets_valid(jsonb) CASCADE;
    """)
