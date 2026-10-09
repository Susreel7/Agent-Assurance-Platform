"""Runtime identity: the chain from an accountable human down to one running copy.

Everything before this revision describes an agent as a *registration*: a row in
``agents``, an immutable ``agent_versions`` descriptor, an ownership window. That is
enough to answer "what did we approve" and not enough to answer the question
`design/14-ai-identity-and-authorization.md` opens with — *a production table was
dropped at 02:14, who is responsible?* Answering it needs the three links the registry
has never held: which running copy, in which context window, under which unit of intent.

```
HUMAN  ─▶ AGENT ─▶ AGENT VERSION ─▶ AGENT INSTANCE ─▶ AGENT SESSION ─▶ AGENT TASK ─▶ ACTION
```

This revision adds the middle four. `0024` adds the action.

**No action without a human at the root** (`design/14` §1). ``human_member_id`` is
``NOT NULL`` on ``agent_instances``, and ``root_human_basis`` records *why* that person
is the root — ``registered_by``, ``approved_by`` or ``triggered_by`` — so a nightly CI
agent is attributed without the evidence implying somebody was at a keyboard. The
alternative, allowing a synthetic ``system`` root, is how accountability disappears, and
it is the failure mode of every service-account model that preceded this one.

**Names, all deliberate, all fixed by the F1 prompt.**

``agent_sessions``, not ``sessions``: `0022` already named the browser session
``auth_sessions`` for this reason. The two serve different principals — a person holding
a cookie, and an agent holding a context window — and collapsing them would make
"revoke this session" ambiguous in the one place ambiguity is a vulnerability.

``agent_tasks``, not ``tasks``: ``jobs`` from `0001` is the internal work queue, and a
table called ``tasks`` next to it invites the wrong join.

``delegations`` keeps the name from `design/14` §4.

**Vocabularies are ``text`` + ``CHECK``, not Postgres enums**, per `design/03`'s
convention: these lists will grow as harnesses appear, and widening a CHECK is one
statement against the catalogue rather than a type rewrite. The exception is
``environment``, which reuses the existing ``lifecycle_state`` enum so an instance,
``agent_runs`` and ``agent_versions`` cannot disagree about what "production" is.

**Nothing here stores context.** A session records *classes* of context source — that a
public issue body was ingested, not what it said. A task records a digest of its intent,
never the intent. AGENTS.md rule 5 applies to this revision in full and the CHECK
constraints below are what make it true rather than merely intended.

Two constraints are added to tables `0001` created. ``agents`` and ``agent_versions``
gain ``UNIQUE (org_id, id)``. Both are no-ops against existing data — ``id`` is already
the primary key, so no two rows can collide on the pair — and both are required so every
foreign key below can be *composite*. A single-column FK to ``agents(id)`` would let an
instance in tenant A reference an agent in tenant B and leave RLS as the only thing
standing between the two; the composite key makes that unrepresentable. The ORM has
declared these constraints since `0001` and the migration never created them, so this
also closes a real declaration-versus-schema drift.

Hand-written per AGENTS.md rule 7, and wants reading line by line before it is applied.

Revision ID: 0023_agent_runtime_identity
Revises: 0022_auth_sessions_and_providers
Create Date: 2026-09-22
"""

from __future__ import annotations

from alembic import op

revision = "0023_agent_runtime_identity"
down_revision = "0022_auth_sessions_and_providers"
branch_labels = None
depends_on = None

# The structural ceiling on agent-spawns-agent nesting. `design/14` §4 sets the *policy*
# default at 3 and makes it an account setting, which V1 owns. This is not that number:
# it is the point past which the chain stops being reconstructable on a screen, and it
# exists so an unbounded spawn loop fails at INSERT rather than after ten thousand rows.
MAX_DELEGATION_DEPTH = 8

_TENANT_TABLES = ("agent_instances", "agent_sessions", "agent_tasks", "delegations")


def upgrade() -> None:
    _composite_keys_on_existing_registry()
    _agent_instances()
    _agent_sessions()
    _agent_tasks()
    _delegations()
    _row_level_security()


def _composite_keys_on_existing_registry() -> None:
    """Make ``(org_id, id)`` addressable on the two registry tables this revision points at.

    ``IF NOT EXISTS`` is not available for ``ADD CONSTRAINT``, so the guard is explicit.
    A database that already carries the constraint — because a future revision added it,
    or because it was applied by hand during the `0017` certification — must not fail
    here.
    """
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'agents_org_id_id_key'
            ) THEN
                ALTER TABLE agents ADD CONSTRAINT agents_org_id_id_key UNIQUE (org_id, id);
            END IF;

            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'agent_versions_org_id_id_key'
            ) THEN
                ALTER TABLE agent_versions
                    ADD CONSTRAINT agent_versions_org_id_id_key UNIQUE (org_id, id);
            END IF;
        END $$;
    """)


def _agent_instances() -> None:
    """One running copy of one approved version, on one host, in one environment.

    This is the entity the threat model needs and the registry has never had. An agent
    is a definition; an instance is a thing that can read a token off a filesystem.

    ``host_fingerprint`` is a digest, not a hostname. An investigator needs to know that
    forty actions came from the *same* laptop; they do not need the laptop's name in a
    multi-tenant control plane, and a hostname is personal data in several of the
    jurisdictions this has to deploy into.

    ``enforcement_grade_available`` is computed at registration from the harness we
    observed and the bindings we could verify (`design/15` §8). It is stored on the
    instance rather than derived at read time because it is a statement about what was
    true *then*: a hook installed next Tuesday does not retroactively protect today's
    actions. ``unknown`` is accepted so an instance can register before the binding
    check completes, and `0024` requires every query to read it as ``E``.
    """
    op.execute(f"""
        CREATE TABLE agent_instances (
            id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id               uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

            agent_id             uuid NOT NULL,
            -- Nullable, and this is the interesting case rather than an oversight: a
            -- discovered agent is observed running before anybody has published a
            -- version for it. Refusing the instance would lose the discovery, which is
            -- the one thing `design/14` §9 says must never block.
            agent_version_id     uuid,

            -- The human root. Rule, not convention: `design/14` §1.
            human_member_id      uuid NOT NULL,
            root_human_basis     text NOT NULL,

            environment          lifecycle_state NOT NULL,
            deployment_location  text NOT NULL DEFAULT 'unknown',
            -- sha256 over the collector's stable host identifier. Never a hostname.
            host_fingerprint     bytea,
            harness              text NOT NULL DEFAULT 'unknown',
            harness_version      text,

            attestation          text NOT NULL DEFAULT 'none',
            enforcement_grade_available text NOT NULL DEFAULT 'unknown',

            lifecycle            text NOT NULL DEFAULT 'active',
            registered_at        timestamptz NOT NULL DEFAULT now(),
            started_at           timestamptz NOT NULL DEFAULT now(),
            last_heartbeat_at    timestamptz,
            ended_at             timestamptz,

            parent_instance_id   uuid,
            delegation_depth     integer NOT NULL DEFAULT 0,

            created_at           timestamptz NOT NULL DEFAULT now(),
            updated_at           timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_instances_org_id_id_key UNIQUE (org_id, id),

            -- Composite so an instance cannot reference another tenant's agent.
            CONSTRAINT agent_instances_agent_same_org_fkey
                FOREIGN KEY (org_id, agent_id)
                REFERENCES agents (org_id, id) ON DELETE CASCADE,
            CONSTRAINT agent_instances_version_same_org_fkey
                FOREIGN KEY (org_id, agent_version_id)
                REFERENCES agent_versions (org_id, id) ON DELETE SET NULL (agent_version_id),
            -- No ON DELETE action, so this is NO ACTION and the check is deferred to the
            -- end of the statement. RESTRICT would be checked immediately and would
            -- therefore refuse `DELETE FROM organizations`, where the member row and the
            -- instance row are both removed by the same cascade. The effect on a *lone*
            -- member delete is identical: refused. Which is the intent — a person who
            -- has run agents is disabled, never erased, or the evidence loses its root.
            CONSTRAINT agent_instances_member_same_org_fkey
                FOREIGN KEY (org_id, human_member_id)
                REFERENCES members (org_id, id),

            -- `design/14` §1. Three bases, and the distinction is the whole point: a
            -- schedule-triggered agent is rooted at whoever approved it, and the
            -- evidence says so rather than implying they were present.
            CONSTRAINT agent_instances_root_basis_valid CHECK (
                root_human_basis IN ('registered_by', 'approved_by', 'triggered_by')
            ),
            CONSTRAINT agent_instances_location_valid CHECK (
                deployment_location IN ('laptop', 'workstation', 'ci_runner',
                                        'server', 'container', 'unknown')
            ),
            -- Widened by the revision that adds a collector for a new harness. Kept as
            -- a CHECK rather than free text so "which harnesses are in the estate" is a
            -- closed question with a correct answer.
            CONSTRAINT agent_instances_harness_valid CHECK (
                harness IN ('claude_code', 'cursor', 'copilot', 'codex', 'gemini_cli',
                            'langgraph', 'sdk', 'ci', 'custom', 'unknown')
            ),
            CONSTRAINT agent_instances_attestation_valid CHECK (
                attestation IN ('none', 'config_signed', 'spiffe_svid', 'tpm')
            ),
            -- A|B|C|D|E from `design/12`, plus `unknown` for the window between
            -- registration and the first binding check. `unknown` reads as E.
            CONSTRAINT agent_instances_grade_valid CHECK (
                enforcement_grade_available IN ('A', 'B', 'C', 'D', 'E', 'unknown')
            ),
            CONSTRAINT agent_instances_lifecycle_valid CHECK (
                lifecycle IN ('active', 'draining', 'ended', 'quarantined')
            ),
            -- Without this the liveness list and the instance count disagree about the
            -- same row: one reads `lifecycle`, the other reads `ended_at`.
            CONSTRAINT agent_instances_ended_consistent CHECK (
                (lifecycle = 'ended') = (ended_at IS NOT NULL)
            ),
            CONSTRAINT agent_instances_window_sane CHECK (
                ended_at IS NULL OR ended_at >= started_at
            ),
            CONSTRAINT agent_instances_heartbeat_sane CHECK (
                last_heartbeat_at IS NULL OR last_heartbeat_at >= started_at
            ),
            -- Depth and parentage are one fact stored twice, so they are constrained to
            -- agree. A root instance at depth 3 would make the delegation chain in
            -- `delegations` unwalkable from either end.
            CONSTRAINT agent_instances_depth_matches_parent CHECK (
                (parent_instance_id IS NULL) = (delegation_depth = 0)
            ),
            CONSTRAINT agent_instances_depth_bounded CHECK (
                delegation_depth BETWEEN 0 AND {MAX_DELEGATION_DEPTH}
            ),
            CONSTRAINT agent_instances_not_own_parent CHECK (
                parent_instance_id IS NULL OR parent_instance_id <> id
            ),

            -- AGENTS.md rule 5 at the storage layer. There is nowhere in this table to
            -- put a prompt, and these bounds are what keep it that way.
            CONSTRAINT agent_instances_no_content CHECK (
                length(coalesce(harness_version, '')) <= 64
                AND (host_fingerprint IS NULL OR octet_length(host_fingerprint) = 32)
            )
        );
    """)

    # The self-referential parent key is added separately rather than inside CREATE
    # TABLE. It references `agent_instances_org_id_id_key`, which is a UNIQUE constraint
    # declared in the same statement, and relying on Postgres to build that index before
    # it validates a foreign key in the same DDL is relying on an ordering nothing
    # documents. NO ACTION rather than CASCADE or SET NULL, for two reasons: SET NULL
    # would leave a child at depth 2 with no parent and violate
    # `agent_instances_depth_matches_parent`, and CASCADE would make deleting one agent
    # silently delete another agent's instances through a delegation edge.
    op.execute("""
        ALTER TABLE agent_instances
            ADD CONSTRAINT agent_instances_parent_same_org_fkey
                FOREIGN KEY (org_id, parent_instance_id)
                REFERENCES agent_instances (org_id, id);
    """)

    op.execute("""
        -- "Everything this agent's instances did" and the per-agent fleet list.
        CREATE INDEX agent_instances_agent_idx
            ON agent_instances (org_id, agent_id, started_at DESC);

        -- The human root query, which is the one the product exists for: "show me every
        -- agent acting for this person". A single index lookup, never a join across
        -- three tables.
        CREATE INDEX agent_instances_human_idx
            ON agent_instances (org_id, human_member_id, started_at DESC);

        CREATE INDEX agent_instances_version_idx
            ON agent_instances (org_id, agent_version_id)
            WHERE agent_version_id IS NOT NULL;

        -- Liveness, and the coverage incident in `design/15` §8: a binding that stopped
        -- reporting three weeks ago is the most likely real failure of this product.
        -- NULLS FIRST so an instance that registered and never sent a heartbeat sorts
        -- to the top of that list rather than the bottom.
        CREATE INDEX agent_instances_liveness_idx
            ON agent_instances (org_id, last_heartbeat_at DESC NULLS FIRST)
            WHERE lifecycle IN ('active', 'draining');

        CREATE INDEX agent_instances_parent_idx
            ON agent_instances (org_id, parent_instance_id)
            WHERE parent_instance_id IS NOT NULL;
    """)


def _agent_sessions() -> None:
    """One continuous context window. Carries taint.

    Taint is the trifecta-breaking control from the threat model, expressed as a column
    so `design/15` §6's ``max_taint`` grant condition has something to read. Once a
    session has ingested untrusted content it stays ingested: the trigger below refuses
    a downgrade, because "tainted → clean" is not a state transition, it is the erasure
    of a security fact. A new context window is a new row.

    ``context_source_classes`` is the classification, never the context. ``issue_public``
    records that a public issue body reached the model; it does not record the body. The
    vocabulary is closed and the array is bounded, so this column cannot become the place
    somebody puts "just a short summary of what was in the prompt".
    """
    op.execute("""
        CREATE TABLE agent_sessions (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id        uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

            instance_id   uuid NOT NULL,

            started_at    timestamptz NOT NULL DEFAULT now(),
            ended_at      timestamptz,
            last_seen_at  timestamptz,

            taint         text NOT NULL DEFAULT 'clean',
            taint_set_at  timestamptz,
            taint_reason_code text,

            context_source_classes text[] NOT NULL DEFAULT '{}'::text[],

            created_at    timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_sessions_org_id_id_key UNIQUE (org_id, id),
            CONSTRAINT agent_sessions_instance_same_org_fkey
                FOREIGN KEY (org_id, instance_id)
                REFERENCES agent_instances (org_id, id) ON DELETE CASCADE,

            CONSTRAINT agent_sessions_taint_valid CHECK (
                taint IN ('clean', 'tainted', 'tainted_with_secrets')
            ),
            -- A tainted session that cannot say when or why is a flag nobody can act
            -- on, and it is indistinguishable from a collector bug.
            CONSTRAINT agent_sessions_taint_explained CHECK (
                taint = 'clean' OR (taint_set_at IS NOT NULL AND taint_reason_code IS NOT NULL)
            ),
            CONSTRAINT agent_sessions_window_sane CHECK (
                ended_at IS NULL OR ended_at >= started_at
            ),
            -- Closed vocabulary, enforced element by element. `<@` on a literal array
            -- is the cheapest way to say "every member of this set is known", and an
            -- unrecognised class is a collector we have not reviewed rather than a new
            -- kind of context.
            CONSTRAINT agent_sessions_context_classes_known CHECK (
                context_source_classes <@ ARRAY[
                    'human_prompt',
                    'repo_internal', 'repo_public',
                    'issue_internal', 'issue_public',
                    'doc_internal', 'web_public',
                    'email', 'ticket', 'chat',
                    'model_output', 'memory_file', 'rule_file',
                    'mcp_resource', 'retrieval_index',
                    'ci_variable', 'unknown'
                ]::text[]
            ),
            CONSTRAINT agent_sessions_no_content CHECK (
                cardinality(context_source_classes) <= 32
                AND length(coalesce(taint_reason_code, '')) <= 64
            )
        );

        -- The session timeline for one instance, and the account-wide keyset list.
        CREATE INDEX agent_sessions_instance_idx
            ON agent_sessions (org_id, instance_id, started_at DESC);
        CREATE INDEX agent_sessions_timeline_idx
            ON agent_sessions (org_id, started_at DESC, id DESC);
        -- "Which context windows are open and dirty right now" — the query a responder
        -- runs first during an incident.
        CREATE INDEX agent_sessions_tainted_open_idx
            ON agent_sessions (org_id, taint, started_at DESC)
            WHERE ended_at IS NULL AND taint <> 'clean';
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION enforce_session_taint_monotonic() RETURNS trigger AS $$
        DECLARE
            ranks constant text[] := ARRAY['clean', 'tainted', 'tainted_with_secrets'];
        BEGIN
            IF array_position(ranks, NEW.taint)
               < array_position(ranks, OLD.taint) THEN
                RAISE EXCEPTION 'session % cannot go from % back to %',
                    OLD.id, OLD.taint, NEW.taint
                    USING HINT = 'a clean context window is a new session, not an edit';
            END IF;

            -- Identity and placement are fixed. Moving a session between instances
            -- would reassign every action already written against it.
            IF  NEW.id          IS DISTINCT FROM OLD.id
             OR NEW.org_id      IS DISTINCT FROM OLD.org_id
             OR NEW.instance_id IS DISTINCT FROM OLD.instance_id
             OR NEW.started_at  IS DISTINCT FROM OLD.started_at
            THEN
                RAISE EXCEPTION 'agent session identity is immutable';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER agent_sessions_taint_monotonic
            BEFORE UPDATE ON agent_sessions
            FOR EACH ROW EXECUTE FUNCTION enforce_session_taint_monotonic();
    """)


def _agent_tasks() -> None:
    """One unit of intent inside a session.

    ``origin`` is load-bearing rather than descriptive. `design/14` §3.4: a task
    originating from a webhook carrying a public issue body is tainted from birth, and
    the only way to know that is to have recorded where the intent came from.

    ``intent_digest`` is a digest of the normalised intent and there is no column for the
    intent itself. That is the difference between this table and a prompt log.
    """
    op.execute("""
        CREATE TABLE agent_tasks (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id        uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

            session_id    uuid NOT NULL,

            origin        text NOT NULL DEFAULT 'unknown',
            -- sha256 over the normalised intent. Never the intent.
            intent_digest bytea,

            started_at    timestamptz NOT NULL DEFAULT now(),
            ended_at      timestamptz,

            created_at    timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT agent_tasks_org_id_id_key UNIQUE (org_id, id),
            CONSTRAINT agent_tasks_session_same_org_fkey
                FOREIGN KEY (org_id, session_id)
                REFERENCES agent_sessions (org_id, id) ON DELETE CASCADE,

            CONSTRAINT agent_tasks_origin_valid CHECK (
                origin IN ('human', 'schedule', 'webhook', 'parent_agent', 'unknown')
            ),
            CONSTRAINT agent_tasks_window_sane CHECK (
                ended_at IS NULL OR ended_at >= started_at
            ),
            CONSTRAINT agent_tasks_no_content CHECK (
                intent_digest IS NULL OR octet_length(intent_digest) = 32
            )
        );

        CREATE INDEX agent_tasks_session_idx
            ON agent_tasks (org_id, session_id, started_at DESC);
        CREATE INDEX agent_tasks_timeline_idx
            ON agent_tasks (org_id, started_at DESC, id DESC);
    """)


def _delegations() -> None:
    """Parent instance grants a subset of its own authority to a child instance.

    Three rules from `design/14` §4, and the third is the only one that needs code.

    1. Delegation, never impersonation — structural here: both ends are instances, and
       an instance always carries its own ``human_member_id``. There is no way to write
       a row that makes an agent look like a person.
    2. Bounded depth — the CHECK below plus ``agent_instances.delegation_depth``.
    3. **Authority attenuates monotonically.** A child's granted set must be a subset of
       its parent's. This is the confused-deputy control (threat model AP-6) and it is
       enforced by a trigger because it is a statement about two rows, which a CHECK
       cannot see.

    ``granted_capability_selectors`` holds selectors, not capability ids: `design/15` §6
    needs ``shell.exec:curl *`` to be grantable without enumerating an unbounded argv
    space. Selectors are compared as text, so attenuation here is set containment and
    not pattern subsumption — a child asking for a *broader pattern* than its parent
    holds is refused because the string is not in the parent's set. Pattern-level
    subsumption is a policy question and belongs to V1's Cedar compilation, not to a
    trigger.
    """
    op.execute(f"""
        CREATE TABLE delegations (
            id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id              uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

            parent_instance_id  uuid NOT NULL,
            child_instance_id   uuid NOT NULL,

            granted_capability_selectors text[] NOT NULL,
            depth               integer NOT NULL,

            reason_code         text,
            granted_by_member_id uuid,

            issued_at           timestamptz NOT NULL DEFAULT now(),
            -- Mandatory. `design/14` §7: a grant with no expiry is how a governance
            -- product becomes a list of permanent exceptions, so it is not
            -- representable in the schema.
            expires_at          timestamptz NOT NULL,
            revoked_at          timestamptz,
            revoked_reason_code text,

            created_at          timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT delegations_org_id_id_key UNIQUE (org_id, id),
            CONSTRAINT delegations_parent_same_org_fkey
                FOREIGN KEY (org_id, parent_instance_id)
                REFERENCES agent_instances (org_id, id) ON DELETE CASCADE,
            CONSTRAINT delegations_child_same_org_fkey
                FOREIGN KEY (org_id, child_instance_id)
                REFERENCES agent_instances (org_id, id) ON DELETE CASCADE,
            CONSTRAINT delegations_member_same_org_fkey
                FOREIGN KEY (org_id, granted_by_member_id)
                REFERENCES members (org_id, id)
                ON DELETE SET NULL (granted_by_member_id),

            CONSTRAINT delegations_not_reflexive CHECK (
                parent_instance_id <> child_instance_id
            ),
            CONSTRAINT delegations_depth_bounded CHECK (
                depth BETWEEN 1 AND {MAX_DELEGATION_DEPTH}
            ),
            CONSTRAINT delegations_window_sane CHECK (expires_at > issued_at),
            -- A revocation with no reason is a privilege that vanished without anybody
            -- removing it, which is the same shape as the `access_grants` rule in 0017.
            CONSTRAINT delegations_revocation_explained CHECK (
                (revoked_at IS NULL) = (revoked_reason_code IS NULL)
            ),
            -- An empty grant is not a delegation; it is a row that looks like authority
            -- and confers none.
            CONSTRAINT delegations_grants_something CHECK (
                cardinality(granted_capability_selectors) BETWEEN 1 AND 64
            ),
            CONSTRAINT delegations_no_content CHECK (
                length(coalesce(reason_code, '')) <= 64
                AND length(coalesce(revoked_reason_code, '')) <= 64
                AND length(array_to_string(granted_capability_selectors, ',')) <= 4096
            )
        );

        -- One live delegation per pair, for the same reason 0017 allows one live access
        -- grant per subject and role: two would make revocation a guessing game, and
        -- the console could not say which grant produced the answer.
        CREATE UNIQUE INDEX delegations_live_pair_idx
            ON delegations (org_id, parent_instance_id, child_instance_id)
            WHERE revoked_at IS NULL;

        -- The authorization-time lookup: "what may this child instance do".
        CREATE INDEX delegations_active_child_idx
            ON delegations (org_id, child_instance_id, expires_at DESC)
            WHERE revoked_at IS NULL;
        CREATE INDEX delegations_active_parent_idx
            ON delegations (org_id, parent_instance_id, expires_at DESC)
            WHERE revoked_at IS NULL;
        -- The expiry sweep. Partial, so it stays proportional to live grants.
        CREATE INDEX delegations_expiring_idx
            ON delegations (expires_at) WHERE revoked_at IS NULL;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION enforce_delegation_attenuation() RETURNS trigger AS $$
        DECLARE
            parent_depth     integer;
            child_parent     uuid;
            child_depth      integer;
            parent_authority text[];
        BEGIN
            SELECT delegation_depth INTO parent_depth
              FROM agent_instances
             WHERE org_id = NEW.org_id AND id = NEW.parent_instance_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'delegation parent instance % is not in org %',
                    NEW.parent_instance_id, NEW.org_id;
            END IF;

            SELECT parent_instance_id, delegation_depth INTO child_parent, child_depth
              FROM agent_instances
             WHERE org_id = NEW.org_id AND id = NEW.child_instance_id;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'delegation child instance % is not in org %',
                    NEW.child_instance_id, NEW.org_id;
            END IF;

            -- The child must already name this parent. Otherwise two delegations could
            -- claim the same child and the chain would have two ancestors at one hop.
            IF child_parent IS DISTINCT FROM NEW.parent_instance_id THEN
                RAISE EXCEPTION
                    'delegation child % names % as its parent instance, not %',
                    NEW.child_instance_id, coalesce(child_parent::text, 'nothing'),
                    NEW.parent_instance_id;
            END IF;

            IF NEW.depth <> parent_depth + 1 THEN
                RAISE EXCEPTION 'delegation depth % does not follow parent depth %',
                    NEW.depth, parent_depth;
            END IF;
            IF child_depth <> NEW.depth THEN
                RAISE EXCEPTION
                    'delegation depth % disagrees with child instance depth %',
                    NEW.depth, child_depth;
            END IF;

            -- The parent's delegated authority is the union of the live delegations
            -- *into* it. A parent with none is acting on its own registered authority,
            -- and this trigger has nothing to compare against -- bounding that case is
            -- the capability grant's job in V1, not this one's. Saying so here is the
            -- difference between a control and the appearance of one.
            SELECT coalesce(array_agg(DISTINCT s.selector), '{}'::text[])
              INTO parent_authority
              FROM delegations d
              CROSS JOIN unnest(d.granted_capability_selectors) AS s(selector)
             WHERE d.org_id = NEW.org_id
               AND d.child_instance_id = NEW.parent_instance_id
               AND d.revoked_at IS NULL
               AND d.expires_at > NEW.issued_at;

            IF cardinality(parent_authority) > 0
               AND NOT (NEW.granted_capability_selectors <@ parent_authority) THEN
                RAISE EXCEPTION 'delegation widens authority beyond its parent'
                    USING HINT =
                      'a child holds a subset of its parent authority, never more';
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        -- INSERT and UPDATE both: widening an existing row is the same defect as
        -- creating a wide one, and it is the easier of the two to reach by accident.
        CREATE TRIGGER delegations_attenuate
            BEFORE INSERT OR UPDATE ON delegations
            FOR EACH ROW EXECUTE FUNCTION enforce_delegation_attenuation();
    """)


def _row_level_security() -> None:
    """Every table above is tenant-owned, so every table above gets the standard policy.

    RLS is the backstop, not the control — AGENTS.md rule 6 still requires the ``org_id``
    filter in every query. Its presence is asserted generically by
    ``tests/sql/invariants.sql`` §8, which fails for any table with a mandatory
    ``org_id`` and no policy.
    """
    for table in _TENANT_TABLES:
        op.execute(f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY {table}_tenant_isolation ON {table}
                USING (current_org_matches(org_id))
                WITH CHECK (current_org_matches(org_id));
        """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS delegations CASCADE;
        DROP TABLE IF EXISTS agent_tasks CASCADE;
        DROP TABLE IF EXISTS agent_sessions CASCADE;
        DROP TABLE IF EXISTS agent_instances CASCADE;

        DROP FUNCTION IF EXISTS enforce_delegation_attenuation() CASCADE;
        DROP FUNCTION IF EXISTS enforce_session_taint_monotonic() CASCADE;
    """)

    # The two registry constraints are left in place deliberately. They are true of any
    # database that ever reached this revision, the ORM has declared them since 0001, and
    # dropping them on the way down would break a re-upgrade that assumes `IF NOT EXISTS`
    # semantics it does not have.
