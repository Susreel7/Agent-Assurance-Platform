"""Account members, RBAC, provider connections, MCP registry and security audit.

Implements the storage half of ``docs/architecture/account-access-console-redesign.md``.
``org_id`` remains the tenant root (D-006, D-034); "Account" is a console word only.

Five concerns, one revision, because they share a dependency cycle at the schema level:
a grant references a member and a role, a connection grant references an agent, and an
MCP grant references an agent version. Splitting them would produce revisions that
cannot be applied independently anyway.

Scale notes, since this is the tier that must carry millions of accounts:

- Every tenant index leads with ``org_id``. A query that does not filter by it is a bug
  (AGENTS.md rule 6), so an index that does not lead with it is dead weight.
- ``security_audit_events`` is partitioned by month like ``evidence_events`` and
  ``agent_runs``. Retention drops partitions; it never issues a bulk DELETE.
- Audit and capability-usage reads are keyset paginated, so the indexes are ordered to
  match ``(org_id, occurred_at DESC, id DESC)`` rather than to support OFFSET.
- Per-call MCP volume is deliberately *not* stored per row here. Billions of tool calls
  a day land in ClickHouse through Observe; this schema keeps the daily rollup that the
  console and the grant reviewer actually read.

Hand-written per AGENTS.md rule 7.

Revision ID: 0017_account_access_registry
Revises: 0016_router_runtime_hardening
Create Date: 2026-09-18
"""

from __future__ import annotations

from alembic import op

revision = "0017_account_access_registry"
down_revision = "0016_router_runtime_hardening"
branch_labels = None
depends_on = None

_TENANT_TABLES = (
    "members",
    "member_identities",
    "teams",
    "team_members",
    "roles",
    "access_grants",
    "access_requests",
    "provider_connections",
    "connection_secret_versions",
    "connection_grants",
    "mcp_servers",
    "mcp_snapshots",
    "mcp_capabilities",
    "mcp_grants",
    "mcp_capability_usage_daily",
    "security_audit_events",
)


def upgrade() -> None:
    _enums()
    _members()
    _access()
    _connections()
    _mcp_registry()
    _security_audit()
    _row_level_security()


def _enums() -> None:
    op.execute("""
        CREATE TYPE member_status AS ENUM (
            'invited', 'active', 'suspended', 'disabled'
        );

        CREATE TYPE access_subject_kind AS ENUM (
            'member', 'team', 'agent', 'agent_version', 'workload', 'project'
        );

        CREATE TYPE access_scope_kind AS ENUM (
            'account', 'project', 'environment', 'agent', 'mcp_server', 'engagement'
        );

        CREATE TYPE access_request_state AS ENUM (
            'pending', 'approved', 'denied', 'withdrawn', 'expired'
        );

        CREATE TYPE connection_provider_kind AS ENUM (
            'openai', 'anthropic', 'azure_openai', 'bedrock', 'vertex', 'mistral',
            'cohere', 'vllm', 'ollama', 'mcp_http', 'custom'
        );

        CREATE TYPE connection_auth_kind AS ENUM (
            'api_key', 'oauth_client', 'iam_role', 'mtls', 'workload_identity', 'none'
        );

        CREATE TYPE connection_status AS ENUM (
            'pending', 'healthy', 'degraded', 'rotating', 'disabled'
        );

        CREATE TYPE mcp_transport AS ENUM (
            'stdio', 'http', 'sse', 'streamable_http'
        );

        CREATE TYPE mcp_trust_tier AS ENUM (
            'internal', 'accredited', 'partner', 'community', 'unverified'
        );

        CREATE TYPE mcp_server_state AS ENUM (
            'draft', 'in_review', 'approved', 'quarantined', 'retired'
        );

        CREATE TYPE mcp_capability_kind AS ENUM ('tool', 'resource', 'prompt');

        CREATE TYPE risk_tier AS ENUM ('low', 'medium', 'high', 'critical');

        CREATE TYPE health_state AS ENUM (
            'unknown', 'healthy', 'degraded', 'unreachable', 'drift'
        );

        CREATE TYPE audit_actor_kind AS ENUM (
            'member', 'workload', 'agent', 'service', 'system'
        );

        CREATE TYPE audit_outcome AS ENUM (
            'allowed', 'denied', 'created', 'updated', 'revoked', 'failed', 'expired'
        );

        CREATE TYPE audit_severity AS ENUM ('info', 'notice', 'warning', 'critical');
    """)


def _members() -> None:
    """Verified people, and the IdP subjects that prove who they are.

    ``member_identities`` is globally unique on ``(issuer, subject)`` rather than unique
    per organisation. One IdP subject is one human; letting the same subject bind to two
    members in two accounts would make "who did this" unanswerable at exactly the moment
    somebody needs an answer.
    """
    op.execute("""
        CREATE TABLE members (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            email text NOT NULL,
            display_name text NOT NULL,
            status member_status NOT NULL DEFAULT 'invited',
            job_title text,
            timezone text NOT NULL DEFAULT 'UTC',
            avatar_tone text NOT NULL DEFAULT 'default',
            primary_team_id uuid,
            invited_by text,
            last_seen_at timestamptz,
            disabled_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT members_email_present CHECK (email <> '' AND length(email) <= 320),
            CONSTRAINT members_email_shape CHECK (position('@' in email) > 1),
            CONSTRAINT members_display_name_present CHECK (
                display_name <> '' AND length(display_name) <= 256
            ),
            CONSTRAINT members_job_title_len CHECK (length(coalesce(job_title, '')) <= 256),
            CONSTRAINT members_timezone_len CHECK (
                timezone <> '' AND length(timezone) <= 64
            ),
            CONSTRAINT members_avatar_tone_valid CHECK (
                avatar_tone IN ('default', 'blue', 'purple', 'amber', 'dark')
            ),
            CONSTRAINT members_disabled_has_timestamp CHECK (
                (status = 'disabled') = (disabled_at IS NOT NULL)
            ),
            CONSTRAINT members_org_id_id_key UNIQUE (org_id, id)
        );

        CREATE UNIQUE INDEX members_org_email_idx ON members (org_id, lower(email));
        -- Console list: newest-first keyset over a single account.
        CREATE INDEX members_org_created_idx ON members (org_id, created_at DESC, id DESC);
        CREATE INDEX members_org_status_idx ON members (org_id, status)
            WHERE status <> 'disabled';
    """)

    op.execute("""
        CREATE TABLE member_identities (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            member_id uuid NOT NULL,
            issuer text NOT NULL,
            subject text NOT NULL,
            email_verified boolean NOT NULL DEFAULT false,
            mfa_verified boolean NOT NULL DEFAULT false,
            directory_groups text[] NOT NULL DEFAULT '{}'::text[],
            last_login_at timestamptz,
            revoked_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT member_identities_issuer_present CHECK (
                issuer <> '' AND length(issuer) <= 512
            ),
            CONSTRAINT member_identities_subject_present CHECK (
                subject <> '' AND length(subject) <= 512
            ),
            CONSTRAINT member_identities_groups_cardinality CHECK (
                cardinality(directory_groups) <= 256
            ),
            CONSTRAINT member_identities_groups_total_len CHECK (
                length(array_to_string(directory_groups, '')) <= 16384
            ),
            CONSTRAINT member_identities_member_same_org_fkey
                FOREIGN KEY (org_id, member_id)
                REFERENCES members (org_id, id)
                ON DELETE CASCADE,
            CONSTRAINT member_identities_org_id_id_key UNIQUE (org_id, id)
        );

        -- Global, not per-tenant: one verified subject resolves to one member. Partial so
        -- a revoked binding stays on the table without blocking its replacement, the same
        -- shape migration 0007 used for identity_bindings.
        CREATE UNIQUE INDEX member_identities_issuer_subject_idx
            ON member_identities (issuer, subject)
            WHERE revoked_at IS NULL;
        CREATE INDEX member_identities_member_idx ON member_identities (org_id, member_id);
    """)

    op.execute("""
        CREATE TABLE teams (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            slug text NOT NULL,
            name text NOT NULL,
            description text,
            parent_team_id uuid,
            source text NOT NULL DEFAULT 'manual',
            directory_group_id text,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT teams_slug_present CHECK (slug <> '' AND length(slug) <= 128),
            CONSTRAINT teams_name_present CHECK (name <> '' AND length(name) <= 256),
            CONSTRAINT teams_description_len CHECK (length(coalesce(description, '')) <= 1024),
            CONSTRAINT teams_source_valid CHECK (source IN ('manual', 'directory')),
            CONSTRAINT teams_directory_source_has_group CHECK (
                source <> 'directory' OR directory_group_id IS NOT NULL
            ),
            CONSTRAINT teams_not_own_parent CHECK (parent_team_id IS DISTINCT FROM id),
            CONSTRAINT teams_parent_same_org_fkey
                FOREIGN KEY (org_id, parent_team_id)
                REFERENCES teams (org_id, id)
                ON DELETE SET NULL (parent_team_id),
            CONSTRAINT teams_org_id_id_key UNIQUE (org_id, id)
        );

        CREATE UNIQUE INDEX teams_org_slug_idx ON teams (org_id, lower(slug));
        CREATE INDEX teams_org_parent_idx ON teams (org_id, parent_team_id)
            WHERE parent_team_id IS NOT NULL;
    """)

    op.execute("""
        ALTER TABLE members
            ADD CONSTRAINT members_primary_team_same_org_fkey
            FOREIGN KEY (org_id, primary_team_id)
            REFERENCES teams (org_id, id)
            ON DELETE SET NULL (primary_team_id);
    """)

    op.execute("""
        CREATE TABLE team_members (
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            team_id uuid NOT NULL,
            member_id uuid NOT NULL,
            is_lead boolean NOT NULL DEFAULT false,
            added_by text,
            added_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (org_id, team_id, member_id),
            CONSTRAINT team_members_team_same_org_fkey
                FOREIGN KEY (org_id, team_id)
                REFERENCES teams (org_id, id)
                ON DELETE CASCADE,
            CONSTRAINT team_members_member_same_org_fkey
                FOREIGN KEY (org_id, member_id)
                REFERENCES members (org_id, id)
                ON DELETE CASCADE
        );

        -- Reverse direction: "which teams is this person in" is the hot authorization
        -- lookup, and the primary key cannot serve it.
        CREATE INDEX team_members_member_idx ON team_members (org_id, member_id);
    """)


def _access() -> None:
    """Roles as data, grants as scoped facts, requests as the answer to a 403.

    Built-in roles are reference rows (``org_id IS NULL``) readable by every tenant and
    writable by none, matching the ``obligation_templates`` pattern. A customer may add
    its own roles alongside them.
    """
    op.execute("""
        CREATE TABLE roles (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid REFERENCES organizations(id) ON DELETE CASCADE,
            key text NOT NULL,
            name text NOT NULL,
            description text NOT NULL,
            builtin boolean NOT NULL DEFAULT false,
            permissions text[] NOT NULL DEFAULT '{}'::text[],
            assignable_scopes access_scope_kind[] NOT NULL DEFAULT '{}'::access_scope_kind[],
            separation_of_duty boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT roles_key_present CHECK (key <> '' AND length(key) <= 64),
            CONSTRAINT roles_key_shape CHECK (key ~ '^[a-z][a-z0-9_]*$'),
            CONSTRAINT roles_name_present CHECK (name <> '' AND length(name) <= 128),
            CONSTRAINT roles_description_present CHECK (
                description <> '' AND length(description) <= 512
            ),
            CONSTRAINT roles_permissions_cardinality CHECK (
                cardinality(permissions) >= 1 AND cardinality(permissions) <= 256
            ),
            CONSTRAINT roles_permissions_shape CHECK (
                array_position(permissions, '') IS NULL
                AND length(array_to_string(permissions, '')) <= 8192
            ),
            CONSTRAINT roles_builtin_is_reference CHECK (builtin = (org_id IS NULL))
        );

        CREATE UNIQUE INDEX roles_builtin_key_idx ON roles (key) WHERE org_id IS NULL;
        CREATE UNIQUE INDEX roles_org_key_idx ON roles (org_id, key) WHERE org_id IS NOT NULL;
    """)

    # Permissions are `resource:action`. The set is closed here rather than in the
    # application so a typo cannot create a permission nothing will ever check.
    op.execute("""
        INSERT INTO roles (org_id, key, name, description, builtin, permissions,
                           assignable_scopes, separation_of_duty)
        VALUES
        (NULL, 'viewer', 'Viewer',
         'Read non-sensitive metadata for granted resources.', true,
         ARRAY['agent:read', 'activity:read', 'registry:read', 'assurance:read'],
         ARRAY['account', 'project', 'environment', 'agent']::access_scope_kind[], false),
        (NULL, 'auditor', 'Auditor',
         'Review evidence and audit history without mutating anything.', true,
         ARRAY['agent:read', 'activity:read', 'registry:read', 'assurance:read',
               'evidence:read', 'audit:read', 'connection:read', 'mcp:read'],
         ARRAY['account', 'engagement']::access_scope_kind[], false),
        (NULL, 'operator', 'Operator',
         'Run, monitor and respond without governance approval.', true,
         ARRAY['agent:read', 'agent:run', 'activity:read', 'activity:replay',
               'registry:read', 'mcp:read', 'mcp:discover', 'mcp:invoke',
               'connection:read', 'assurance:read'],
         ARRAY['project', 'environment', 'agent']::access_scope_kind[], false),
        (NULL, 'engineer', 'Developer',
         'Build, test and publish agents within granted scopes.', true,
         ARRAY['agent:read', 'agent:write', 'agent:run', 'agent:publish',
               'activity:read', 'activity:replay', 'registry:read', 'registry:write',
               'mcp:read', 'mcp:discover', 'mcp:invoke', 'connection:read',
               'key:read', 'key:write', 'assurance:read', 'prompt:write',
               'evaluate:write'],
         ARRAY['project', 'environment', 'agent']::access_scope_kind[], false),
        (NULL, 'approver', 'Approver',
         'Decide release, materiality and accreditation outcomes.', true,
         ARRAY['agent:read', 'activity:read', 'registry:read', 'assurance:read',
               'release:approve', 'accreditation:approve', 'materiality:adjudicate',
               'access:approve', 'mcp:approve', 'mcp:grant'],
         ARRAY['account', 'project', 'environment', 'agent',
               'engagement']::access_scope_kind[], true),
        (NULL, 'security_admin', 'Security admin',
         'Own connections, keys, runtime policy and revocation.', true,
         ARRAY['agent:read', 'activity:read', 'registry:read', 'assurance:read',
               'audit:read', 'connection:read', 'connection:write', 'connection:rotate',
               'key:read', 'key:write', 'key:revoke', 'mcp:read', 'mcp:write',
               'mcp:discover', 'mcp:approve', 'mcp:grant', 'mcp:quarantine',
               'policy:write', 'access:read', 'access:write', 'access:approve',
               'payload:reveal'],
         ARRAY['account']::access_scope_kind[], true),
        (NULL, 'identity_admin', 'Identity admin',
         'Manage directory federation, members and team mapping.', true,
         ARRAY['member:read', 'member:write', 'team:read', 'team:write',
               'access:read', 'access:write', 'audit:read'],
         ARRAY['account']::access_scope_kind[], false),
        (NULL, 'account_admin', 'Account admin',
         'Manage people, teams, projects and ordinary settings.', true,
         ARRAY['member:read', 'member:write', 'team:read', 'team:write',
               'project:read', 'project:write', 'access:read', 'access:write',
               'agent:read', 'activity:read', 'registry:read', 'assurance:read',
               'connection:read', 'key:read', 'mcp:read'],
         ARRAY['account']::access_scope_kind[], false);
    """)

    op.execute("""
        CREATE TABLE access_grants (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            subject_kind access_subject_kind NOT NULL,
            subject_id uuid NOT NULL,
            role_key text NOT NULL,
            scope_kind access_scope_kind NOT NULL,
            scope_id uuid,
            granted_by text NOT NULL,
            reason text,
            request_id uuid,
            expires_at timestamptz,
            revoked_at timestamptz,
            revoked_by text,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT access_grants_subject_is_principal CHECK (
                subject_kind IN ('member', 'team')
            ),
            CONSTRAINT access_grants_role_key_shape CHECK (
                role_key <> '' AND length(role_key) <= 64
            ),
            CONSTRAINT access_grants_granted_by_len CHECK (
                granted_by <> '' AND length(granted_by) <= 512
            ),
            CONSTRAINT access_grants_reason_len CHECK (length(coalesce(reason, '')) <= 1024),
            CONSTRAINT access_grants_account_scope_has_no_id CHECK (
                (scope_kind = 'account') = (scope_id IS NULL)
            ),
            CONSTRAINT access_grants_revoked_pair CHECK (
                (revoked_at IS NULL) = (revoked_by IS NULL)
            ),
            CONSTRAINT access_grants_org_id_id_key UNIQUE (org_id, id)
        );

        -- The authorization hot path: every request resolves a subject's live grants.
        -- Partial on live rows so expired and revoked history never enters the scan.
        CREATE INDEX access_grants_live_subject_idx
            ON access_grants (org_id, subject_kind, subject_id, scope_kind)
            WHERE revoked_at IS NULL;
        CREATE INDEX access_grants_scope_idx
            ON access_grants (org_id, scope_kind, scope_id)
            WHERE revoked_at IS NULL;
        -- Expiry sweep: the worker asks only for grants that have actually lapsed.
        CREATE INDEX access_grants_expiring_idx ON access_grants (expires_at)
            WHERE revoked_at IS NULL AND expires_at IS NOT NULL;
        CREATE UNIQUE INDEX access_grants_unique_live_idx
            ON access_grants (
                org_id, subject_kind, subject_id, role_key, scope_kind,
                coalesce(scope_id, '00000000-0000-0000-0000-000000000000'::uuid)
            )
            WHERE revoked_at IS NULL;
    """)

    op.execute("""
        CREATE TABLE access_requests (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            requester_member_id uuid NOT NULL,
            role_key text NOT NULL,
            scope_kind access_scope_kind NOT NULL,
            scope_id uuid,
            duration_minutes integer NOT NULL,
            reason text NOT NULL,
            ticket_ref text,
            risk risk_tier NOT NULL DEFAULT 'low',
            state access_request_state NOT NULL DEFAULT 'pending',
            decided_by text,
            decided_at timestamptz,
            decision_note text,
            granted_grant_id uuid,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT access_requests_duration_bounded CHECK (
                duration_minutes >= 15 AND duration_minutes <= 43200
            ),
            CONSTRAINT access_requests_reason_present CHECK (
                reason <> '' AND length(reason) <= 1024
            ),
            CONSTRAINT access_requests_ticket_len CHECK (
                length(coalesce(ticket_ref, '')) <= 128
            ),
            CONSTRAINT access_requests_note_len CHECK (
                length(coalesce(decision_note, '')) <= 1024
            ),
            CONSTRAINT access_requests_role_key_shape CHECK (
                role_key <> '' AND length(role_key) <= 64
            ),
            CONSTRAINT access_requests_account_scope_has_no_id CHECK (
                (scope_kind = 'account') = (scope_id IS NULL)
            ),
            -- A decided request names its decider; a pending one cannot.
            CONSTRAINT access_requests_decision_complete CHECK (
                (state = 'pending')
                    = (decided_by IS NULL AND decided_at IS NULL)
            ),
            CONSTRAINT access_requests_approved_has_grant CHECK (
                state <> 'approved' OR granted_grant_id IS NOT NULL
            ),
            CONSTRAINT access_requests_requester_same_org_fkey
                FOREIGN KEY (org_id, requester_member_id)
                REFERENCES members (org_id, id)
                ON DELETE CASCADE,
            CONSTRAINT access_requests_grant_same_org_fkey
                FOREIGN KEY (org_id, granted_grant_id)
                REFERENCES access_grants (org_id, id)
                ON DELETE SET NULL (granted_grant_id),
            CONSTRAINT access_requests_org_id_id_key UNIQUE (org_id, id)
        );

        CREATE INDEX access_requests_pending_idx
            ON access_requests (org_id, created_at DESC, id DESC)
            WHERE state = 'pending';
        CREATE INDEX access_requests_requester_idx
            ON access_requests (org_id, requester_member_id, created_at DESC);

        ALTER TABLE access_grants
            ADD CONSTRAINT access_grants_request_same_org_fkey
            FOREIGN KEY (org_id, request_id)
            REFERENCES access_requests (org_id, id)
            ON DELETE SET NULL (request_id);
    """)


def _connections() -> None:
    """Customer-owned provider agreements, referenced but never stored.

    ``credential_ref`` is a pointer into the customer's secret provider. No column here
    holds a secret value, and none ever should: AGENTS.md rule 9 puts secret material
    behind ``app/providers/``, and in BYOC the provider differs per customer.
    ``fingerprint`` is a SHA-256 digest kept so a rotation can be *proven* to have
    changed the material without revealing any of it.
    """
    op.execute("""
        CREATE TABLE provider_connections (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            slug text NOT NULL,
            name text NOT NULL,
            provider_kind connection_provider_kind NOT NULL,
            auth_kind connection_auth_kind NOT NULL,
            status connection_status NOT NULL DEFAULT 'pending',
            owner_team_id uuid,
            personal_member_id uuid,
            endpoint_url text,
            region text,
            residency_zone text,
            environments lifecycle_state[] NOT NULL DEFAULT '{}'::lifecycle_state[],
            active_secret_version_id uuid,
            rotation_due_at timestamptz,
            last_used_at timestamptz,
            last_health_at timestamptz,
            health_detail text,
            disabled_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            created_by text NOT NULL,
            CONSTRAINT provider_connections_slug_present CHECK (
                slug <> '' AND length(slug) <= 128
            ),
            CONSTRAINT provider_connections_name_present CHECK (
                name <> '' AND length(name) <= 256
            ),
            CONSTRAINT provider_connections_endpoint_len CHECK (
                length(coalesce(endpoint_url, '')) <= 2048
            ),
            CONSTRAINT provider_connections_region_len CHECK (
                length(coalesce(region, '')) <= 64
            ),
            CONSTRAINT provider_connections_residency_len CHECK (
                length(coalesce(residency_zone, '')) <= 64
            ),
            CONSTRAINT provider_connections_health_detail_len CHECK (
                length(coalesce(health_detail, '')) <= 512
            ),
            CONSTRAINT provider_connections_created_by_len CHECK (
                created_by <> '' AND length(created_by) <= 512
            ),
            CONSTRAINT provider_connections_environments_cardinality CHECK (
                cardinality(environments) <= 5
            ),
            -- A personal BYOK connection is development-only by construction: it cannot
            -- carry a production environment, so no policy can widen it later.
            CONSTRAINT provider_connections_personal_is_dev_only CHECK (
                personal_member_id IS NULL
                OR NOT ('production'::lifecycle_state = ANY (environments))
            ),
            CONSTRAINT provider_connections_disabled_pair CHECK (
                (status = 'disabled') = (disabled_at IS NOT NULL)
            ),
            CONSTRAINT provider_connections_owner_team_same_org_fkey
                FOREIGN KEY (org_id, owner_team_id)
                REFERENCES teams (org_id, id)
                ON DELETE SET NULL (owner_team_id),
            CONSTRAINT provider_connections_personal_member_same_org_fkey
                FOREIGN KEY (org_id, personal_member_id)
                REFERENCES members (org_id, id)
                ON DELETE CASCADE,
            CONSTRAINT provider_connections_org_id_id_key UNIQUE (org_id, id)
        );

        CREATE UNIQUE INDEX provider_connections_org_slug_idx
            ON provider_connections (org_id, lower(slug));
        CREATE INDEX provider_connections_org_kind_idx
            ON provider_connections (org_id, provider_kind, status);
        CREATE INDEX provider_connections_rotation_idx
            ON provider_connections (rotation_due_at)
            WHERE disabled_at IS NULL AND rotation_due_at IS NOT NULL;
    """)

    op.execute("""
        CREATE TABLE connection_secret_versions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            connection_id uuid NOT NULL,
            version_number integer NOT NULL,
            credential_ref text NOT NULL,
            fingerprint bytea NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            activated_at timestamptz,
            retired_at timestamptz,
            created_by text NOT NULL,
            CONSTRAINT connection_secret_versions_number_positive CHECK (version_number >= 1),
            CONSTRAINT connection_secret_versions_ref_present CHECK (
                credential_ref <> '' AND length(credential_ref) <= 1024
            ),
            CONSTRAINT connection_secret_versions_fingerprint_len CHECK (
                octet_length(fingerprint) = 32
            ),
            CONSTRAINT connection_secret_versions_created_by_len CHECK (
                created_by <> '' AND length(created_by) <= 512
            ),
            CONSTRAINT connection_secret_versions_connection_same_org_fkey
                FOREIGN KEY (org_id, connection_id)
                REFERENCES provider_connections (org_id, id)
                ON DELETE CASCADE,
            CONSTRAINT connection_secret_versions_org_connection_id_key
                UNIQUE (org_id, connection_id, id)
        );

        CREATE UNIQUE INDEX connection_secret_versions_number_idx
            ON connection_secret_versions (connection_id, version_number);
        CREATE INDEX connection_secret_versions_connection_idx
            ON connection_secret_versions (org_id, connection_id, version_number DESC);
    """)

    op.execute("""
        ALTER TABLE provider_connections
            ADD CONSTRAINT provider_connections_active_secret_fkey
            FOREIGN KEY (org_id, id, active_secret_version_id)
            REFERENCES connection_secret_versions (org_id, connection_id, id)
            ON DELETE RESTRICT
            DEFERRABLE INITIALLY DEFERRED;
    """)

    op.execute("""
        CREATE TABLE connection_grants (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            connection_id uuid NOT NULL,
            subject_kind access_subject_kind NOT NULL,
            subject_id uuid NOT NULL,
            environments lifecycle_state[] NOT NULL DEFAULT '{}'::lifecycle_state[],
            granted_by text NOT NULL,
            reason text,
            expires_at timestamptz,
            revoked_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT connection_grants_subject_is_workload CHECK (
                subject_kind IN ('agent', 'team', 'project')
            ),
            CONSTRAINT connection_grants_granted_by_len CHECK (
                granted_by <> '' AND length(granted_by) <= 512
            ),
            CONSTRAINT connection_grants_reason_len CHECK (
                length(coalesce(reason, '')) <= 1024
            ),
            CONSTRAINT connection_grants_environments_present CHECK (
                cardinality(environments) >= 1 AND cardinality(environments) <= 5
            ),
            CONSTRAINT connection_grants_connection_same_org_fkey
                FOREIGN KEY (org_id, connection_id)
                REFERENCES provider_connections (org_id, id)
                ON DELETE CASCADE,
            CONSTRAINT connection_grants_org_id_id_key UNIQUE (org_id, id)
        );

        CREATE INDEX connection_grants_live_subject_idx
            ON connection_grants (org_id, subject_kind, subject_id)
            WHERE revoked_at IS NULL;
        CREATE UNIQUE INDEX connection_grants_unique_live_idx
            ON connection_grants (org_id, connection_id, subject_kind, subject_id)
            WHERE revoked_at IS NULL;
    """)


def _mcp_registry() -> None:
    """Canonical MCP identity, immutable capability snapshots, and effective access.

    The registry's whole value is that a snapshot cannot change under an approval, so
    ``mcp_snapshots`` and ``mcp_capabilities`` are append-only by trigger. Approving a
    server pins one snapshot id; a newly discovered snapshot with a different digest is
    drift, and drift is what quarantine acts on.
    """
    op.execute("""
        CREATE TABLE mcp_servers (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            slug text NOT NULL,
            name text NOT NULL,
            description text,
            transport mcp_transport NOT NULL,
            endpoint_url text,
            command text,
            owner_team_id uuid,
            connection_id uuid,
            trust_tier mcp_trust_tier NOT NULL DEFAULT 'unverified',
            state mcp_server_state NOT NULL DEFAULT 'draft',
            risk_tier risk_tier NOT NULL DEFAULT 'medium',
            health health_state NOT NULL DEFAULT 'unknown',
            environments lifecycle_state[] NOT NULL DEFAULT '{}'::lifecycle_state[],
            approved_snapshot_id uuid,
            observed_snapshot_id uuid,
            requires_approval_for_writes boolean NOT NULL DEFAULT true,
            quarantined_at timestamptz,
            quarantine_reason text,
            last_discovered_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            created_by text NOT NULL,
            CONSTRAINT mcp_servers_slug_present CHECK (slug <> '' AND length(slug) <= 128),
            CONSTRAINT mcp_servers_name_present CHECK (name <> '' AND length(name) <= 256),
            CONSTRAINT mcp_servers_description_len CHECK (
                length(coalesce(description, '')) <= 1024
            ),
            CONSTRAINT mcp_servers_endpoint_len CHECK (
                length(coalesce(endpoint_url, '')) <= 2048
            ),
            CONSTRAINT mcp_servers_command_len CHECK (length(coalesce(command, '')) <= 2048),
            CONSTRAINT mcp_servers_quarantine_reason_len CHECK (
                length(coalesce(quarantine_reason, '')) <= 512
            ),
            CONSTRAINT mcp_servers_created_by_len CHECK (
                created_by <> '' AND length(created_by) <= 512
            ),
            CONSTRAINT mcp_servers_environments_cardinality CHECK (
                cardinality(environments) <= 5
            ),
            -- A remote transport needs an endpoint; stdio needs a command. Without this
            -- an unreachable server sits in the registry looking approved.
            CONSTRAINT mcp_servers_addressable CHECK (
                (transport = 'stdio' AND command IS NOT NULL)
                OR (transport <> 'stdio' AND endpoint_url IS NOT NULL)
            ),
            CONSTRAINT mcp_servers_quarantine_pair CHECK (
                (state = 'quarantined') = (quarantined_at IS NOT NULL)
            ),
            CONSTRAINT mcp_servers_approved_has_snapshot CHECK (
                state <> 'approved' OR approved_snapshot_id IS NOT NULL
            ),
            CONSTRAINT mcp_servers_owner_team_same_org_fkey
                FOREIGN KEY (org_id, owner_team_id)
                REFERENCES teams (org_id, id)
                ON DELETE SET NULL (owner_team_id),
            CONSTRAINT mcp_servers_connection_same_org_fkey
                FOREIGN KEY (org_id, connection_id)
                REFERENCES provider_connections (org_id, id)
                ON DELETE SET NULL (connection_id),
            CONSTRAINT mcp_servers_org_id_id_key UNIQUE (org_id, id)
        );

        CREATE UNIQUE INDEX mcp_servers_org_slug_idx ON mcp_servers (org_id, lower(slug));
        CREATE INDEX mcp_servers_org_state_idx ON mcp_servers (org_id, state, trust_tier);
        CREATE INDEX mcp_servers_attention_idx ON mcp_servers (org_id, updated_at DESC)
            WHERE state IN ('quarantined', 'in_review') OR health = 'drift';
    """)

    op.execute("""
        CREATE TABLE mcp_snapshots (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            server_id uuid NOT NULL,
            capability_digest bytea NOT NULL,
            protocol_version text,
            source text NOT NULL DEFAULT 'discovery',
            tool_count integer NOT NULL DEFAULT 0,
            resource_count integer NOT NULL DEFAULT 0,
            prompt_count integer NOT NULL DEFAULT 0,
            discovered_at timestamptz NOT NULL DEFAULT now(),
            discovered_by text NOT NULL,
            approved_at timestamptz,
            approved_by text,
            superseded_at timestamptz,
            CONSTRAINT mcp_snapshots_digest_len CHECK (octet_length(capability_digest) = 32),
            CONSTRAINT mcp_snapshots_protocol_len CHECK (
                length(coalesce(protocol_version, '')) <= 32
            ),
            CONSTRAINT mcp_snapshots_source_valid CHECK (
                source IN ('discovery', 'import', 'manual', 'observed')
            ),
            CONSTRAINT mcp_snapshots_counts_non_negative CHECK (
                tool_count >= 0 AND resource_count >= 0 AND prompt_count >= 0
            ),
            CONSTRAINT mcp_snapshots_counts_bounded CHECK (
                tool_count <= 4096 AND resource_count <= 4096 AND prompt_count <= 4096
            ),
            CONSTRAINT mcp_snapshots_discovered_by_len CHECK (
                discovered_by <> '' AND length(discovered_by) <= 512
            ),
            CONSTRAINT mcp_snapshots_approval_pair CHECK (
                (approved_at IS NULL) = (approved_by IS NULL)
            ),
            CONSTRAINT mcp_snapshots_server_same_org_fkey
                FOREIGN KEY (org_id, server_id)
                REFERENCES mcp_servers (org_id, id)
                ON DELETE CASCADE,
            CONSTRAINT mcp_snapshots_org_server_id_key UNIQUE (org_id, server_id, id)
        );

        -- One row per distinct capability set per server. Re-discovering an unchanged
        -- server touches ``discovered_at`` on the existing row instead of growing the
        -- table, which is what keeps this bounded under continuous discovery.
        CREATE UNIQUE INDEX mcp_snapshots_server_digest_idx
            ON mcp_snapshots (server_id, capability_digest);
        CREATE INDEX mcp_snapshots_server_recent_idx
            ON mcp_snapshots (org_id, server_id, discovered_at DESC);
    """)

    op.execute("""
        ALTER TABLE mcp_servers
            ADD CONSTRAINT mcp_servers_approved_snapshot_fkey
            FOREIGN KEY (org_id, id, approved_snapshot_id)
            REFERENCES mcp_snapshots (org_id, server_id, id)
            ON DELETE RESTRICT
            DEFERRABLE INITIALLY DEFERRED;

        ALTER TABLE mcp_servers
            ADD CONSTRAINT mcp_servers_observed_snapshot_fkey
            FOREIGN KEY (org_id, id, observed_snapshot_id)
            REFERENCES mcp_snapshots (org_id, server_id, id)
            ON DELETE SET NULL (observed_snapshot_id)
            DEFERRABLE INITIALLY DEFERRED;
    """)

    # Rule 5 applies with full force here. A capability row records *shape* — name,
    # schema digest, declared annotation, verified risk — and never an argument value.
    op.execute("""
        CREATE TABLE mcp_capabilities (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            snapshot_id uuid NOT NULL,
            server_id uuid NOT NULL,
            kind mcp_capability_kind NOT NULL,
            name text NOT NULL,
            title text,
            input_schema_digest bytea,
            declared_read_only boolean,
            declared_destructive boolean,
            declared_idempotent boolean,
            declared_open_world boolean,
            verified_risk risk_tier NOT NULL DEFAULT 'medium',
            verified_write boolean NOT NULL DEFAULT false,
            verified_irreversible boolean NOT NULL DEFAULT false,
            review_note text,
            reviewed_by text,
            reviewed_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT mcp_capabilities_name_present CHECK (
                name <> '' AND length(name) <= 256
            ),
            CONSTRAINT mcp_capabilities_title_len CHECK (length(coalesce(title, '')) <= 256),
            CONSTRAINT mcp_capabilities_schema_digest_len CHECK (
                input_schema_digest IS NULL OR octet_length(input_schema_digest) = 32
            ),
            -- Bounded and content-free: a reviewer's note, never a captured payload.
            CONSTRAINT mcp_capabilities_review_note_len CHECK (
                length(coalesce(review_note, '')) <= 512
            ),
            CONSTRAINT mcp_capabilities_reviewed_pair CHECK (
                (reviewed_at IS NULL) = (reviewed_by IS NULL)
            ),
            CONSTRAINT mcp_capabilities_irreversible_is_write CHECK (
                NOT verified_irreversible OR verified_write
            ),
            CONSTRAINT mcp_capabilities_snapshot_same_org_fkey
                FOREIGN KEY (org_id, server_id, snapshot_id)
                REFERENCES mcp_snapshots (org_id, server_id, id)
                ON DELETE CASCADE,
            CONSTRAINT mcp_capabilities_org_id_id_key UNIQUE (org_id, id)
        );

        CREATE UNIQUE INDEX mcp_capabilities_snapshot_kind_name_idx
            ON mcp_capabilities (snapshot_id, kind, name);
        CREATE INDEX mcp_capabilities_server_name_idx
            ON mcp_capabilities (org_id, server_id, name);
        CREATE INDEX mcp_capabilities_dangerous_idx
            ON mcp_capabilities (org_id, server_id)
            WHERE verified_irreversible OR verified_risk IN ('high', 'critical');
    """)

    # An approved snapshot that can be edited is not evidence of anything.
    op.execute("""
        CREATE OR REPLACE FUNCTION forbid_mcp_snapshot_rewrite() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF coalesce(current_setting('app.registry_maintenance', true), 'off') = 'on'
                THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION 'mcp_snapshots is append-only: delete is forbidden'
                    USING HINT = 'retire the server, or supersede the snapshot';
            END IF;

            IF NEW.id                IS DISTINCT FROM OLD.id
             OR NEW.org_id           IS DISTINCT FROM OLD.org_id
             OR NEW.server_id        IS DISTINCT FROM OLD.server_id
             OR NEW.capability_digest IS DISTINCT FROM OLD.capability_digest
             OR NEW.tool_count       IS DISTINCT FROM OLD.tool_count
             OR NEW.resource_count   IS DISTINCT FROM OLD.resource_count
             OR NEW.prompt_count     IS DISTINCT FROM OLD.prompt_count
            THEN
                RAISE EXCEPTION 'snapshot % is immutable; record a new snapshot', OLD.id;
            END IF;

            -- An approval cannot be silently moved to a different actor or time.
            IF OLD.approved_at IS NOT NULL
               AND (NEW.approved_at IS DISTINCT FROM OLD.approved_at
                    OR NEW.approved_by IS DISTINCT FROM OLD.approved_by)
            THEN
                RAISE EXCEPTION 'snapshot % approval is already recorded', OLD.id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER mcp_snapshots_append_only
            BEFORE UPDATE OR DELETE ON mcp_snapshots
            FOR EACH ROW EXECUTE FUNCTION forbid_mcp_snapshot_rewrite();
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION forbid_mcp_capability_rewrite() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF coalesce(current_setting('app.registry_maintenance', true), 'off') = 'on'
                THEN
                    RETURN OLD;
                END IF;
                RAISE EXCEPTION 'mcp_capabilities is append-only: delete is forbidden';
            END IF;

            IF NEW.id                  IS DISTINCT FROM OLD.id
             OR NEW.org_id             IS DISTINCT FROM OLD.org_id
             OR NEW.snapshot_id       IS DISTINCT FROM OLD.snapshot_id
             OR NEW.server_id         IS DISTINCT FROM OLD.server_id
             OR NEW.kind              IS DISTINCT FROM OLD.kind
             OR NEW.name              IS DISTINCT FROM OLD.name
             OR NEW.input_schema_digest IS DISTINCT FROM OLD.input_schema_digest
            THEN
                RAISE EXCEPTION 'capability %/% is immutable within its snapshot',
                    OLD.server_id, OLD.name;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER mcp_capabilities_append_only
            BEFORE UPDATE OR DELETE ON mcp_capabilities
            FOR EACH ROW EXECUTE FUNCTION forbid_mcp_capability_rewrite();
    """)

    # The grant that the gateway actually enforces. ``capability_name IS NULL`` grants
    # the whole server; a named capability narrows it. Both forms are common: a team
    # gets a server, a production agent version gets three named tools.
    op.execute("""
        CREATE TABLE mcp_grants (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            server_id uuid NOT NULL,
            capability_name text,
            subject_kind access_subject_kind NOT NULL,
            subject_id uuid NOT NULL,
            environments lifecycle_state[] NOT NULL DEFAULT '{}'::lifecycle_state[],
            permission text NOT NULL DEFAULT 'invoke',
            requires_approval boolean NOT NULL DEFAULT false,
            pinned_snapshot_id uuid,
            granted_by text NOT NULL,
            reason text,
            expires_at timestamptz,
            revoked_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT mcp_grants_capability_len CHECK (
                length(coalesce(capability_name, '')) <= 256
            ),
            CONSTRAINT mcp_grants_permission_valid CHECK (
                permission IN ('invoke', 'read')
            ),
            CONSTRAINT mcp_grants_granted_by_len CHECK (
                granted_by <> '' AND length(granted_by) <= 512
            ),
            CONSTRAINT mcp_grants_reason_len CHECK (length(coalesce(reason, '')) <= 1024),
            CONSTRAINT mcp_grants_environments_present CHECK (
                cardinality(environments) >= 1 AND cardinality(environments) <= 5
            ),
            CONSTRAINT mcp_grants_server_same_org_fkey
                FOREIGN KEY (org_id, server_id)
                REFERENCES mcp_servers (org_id, id)
                ON DELETE CASCADE,
            CONSTRAINT mcp_grants_pinned_snapshot_fkey
                FOREIGN KEY (org_id, server_id, pinned_snapshot_id)
                REFERENCES mcp_snapshots (org_id, server_id, id)
                ON DELETE SET NULL (pinned_snapshot_id),
            CONSTRAINT mcp_grants_org_id_id_key UNIQUE (org_id, id)
        );

        -- Enforcement lookup: subject first, because the gateway knows who is calling
        -- before it knows which tool the model will pick.
        CREATE INDEX mcp_grants_live_subject_idx
            ON mcp_grants (org_id, subject_kind, subject_id, server_id)
            WHERE revoked_at IS NULL;
        CREATE INDEX mcp_grants_live_server_idx
            ON mcp_grants (org_id, server_id, capability_name)
            WHERE revoked_at IS NULL;
        CREATE UNIQUE INDEX mcp_grants_unique_live_idx
            ON mcp_grants (
                org_id, server_id, coalesce(capability_name, '*'),
                subject_kind, subject_id
            )
            WHERE revoked_at IS NULL;
    """)

    # Billions of tool calls a day cannot each become a control-plane row. Observe keeps
    # the per-call record in ClickHouse; this is the daily rollup the console reads and
    # the grant reviewer reasons about.
    op.execute("""
        CREATE TABLE mcp_capability_usage_daily (
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            usage_date date NOT NULL,
            server_id uuid NOT NULL,
            capability_name text NOT NULL,
            -- The all-zero UUID means "not attributed to one", not "unknown". A primary
            -- key cannot contain an expression, so nullable columns here would need a
            -- unique index over coalesce() and an upsert naming the same expression. A
            -- sentinel keeps the key a plain column list and the ON CONFLICT trivial.
            agent_id uuid NOT NULL DEFAULT '00000000-0000-0000-0000-000000000000'::uuid,
            member_id uuid NOT NULL DEFAULT '00000000-0000-0000-0000-000000000000'::uuid,
            call_count bigint NOT NULL DEFAULT 0,
            denied_count bigint NOT NULL DEFAULT 0,
            approval_count bigint NOT NULL DEFAULT 0,
            error_count bigint NOT NULL DEFAULT 0,
            p95_latency_ms integer,
            cost_micros bigint NOT NULL DEFAULT 0,
            updated_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (
                org_id, usage_date, server_id, capability_name,
                agent_id, member_id
            ),
            CONSTRAINT mcp_capability_usage_daily_capability_len CHECK (
                capability_name <> '' AND length(capability_name) <= 256
            ),
            CONSTRAINT mcp_capability_usage_daily_counts_non_negative CHECK (
                call_count >= 0 AND denied_count >= 0
                AND approval_count >= 0 AND error_count >= 0
                AND cost_micros >= 0
            ),
            CONSTRAINT mcp_capability_usage_daily_latency_non_negative CHECK (
                p95_latency_ms IS NULL OR p95_latency_ms >= 0
            ),
            CONSTRAINT mcp_capability_usage_daily_server_same_org_fkey
                FOREIGN KEY (org_id, server_id)
                REFERENCES mcp_servers (org_id, id)
                ON DELETE CASCADE
        );

        CREATE INDEX mcp_capability_usage_daily_window_idx
            ON mcp_capability_usage_daily (org_id, usage_date DESC, server_id);
        CREATE INDEX mcp_capability_usage_daily_denied_idx
            ON mcp_capability_usage_daily (org_id, usage_date DESC)
            WHERE denied_count > 0;
    """)


def _security_audit() -> None:
    """Append-only identity, authorization, credential and enforcement history.

    Partitioned by month for the same reason ``evidence_events`` is: retention on a table
    this size has to be a partition drop. A bulk DELETE across a billion rows would
    take the table's autovacuum with it.

    ``detail`` is JSONB and deliberately size-capped. It records classifications,
    digests and decisions — never a prompt, completion or tool argument (rule 5).
    """
    op.execute("""
        CREATE TABLE security_audit_events (
            id uuid NOT NULL DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            occurred_at timestamptz NOT NULL DEFAULT now(),
            event_type text NOT NULL,
            category text NOT NULL,
            severity audit_severity NOT NULL DEFAULT 'info',
            outcome audit_outcome NOT NULL,
            actor_kind audit_actor_kind NOT NULL,
            actor_id uuid,
            actor_label text NOT NULL,
            target_kind text,
            target_id uuid,
            target_label text,
            reason_code text,
            policy_digest bytea,
            request_id text,
            trace_id text,
            source_ip inet,
            user_agent_digest bytea,
            detail jsonb NOT NULL DEFAULT '{}'::jsonb,
            PRIMARY KEY (id, occurred_at),
            CONSTRAINT security_audit_events_event_type_len CHECK (
                event_type <> '' AND length(event_type) <= 128
            ),
            -- Kept in step with security_audit.schemas.Category by
            -- tests/unit/test_security_audit.py. Text rather than an enum because the
            -- console treats this as a tab strip and the list will grow.
            CONSTRAINT security_audit_events_category_valid CHECK (
                category IN ('identity', 'access', 'credential', 'mcp',
                             'routing', 'data', 'admin')
            ),
            CONSTRAINT security_audit_events_actor_label_len CHECK (
                actor_label <> '' AND length(actor_label) <= 512
            ),
            CONSTRAINT security_audit_events_target_kind_len CHECK (
                length(coalesce(target_kind, '')) <= 64
            ),
            CONSTRAINT security_audit_events_target_label_len CHECK (
                length(coalesce(target_label, '')) <= 512
            ),
            CONSTRAINT security_audit_events_reason_code_len CHECK (
                length(coalesce(reason_code, '')) <= 128
            ),
            CONSTRAINT security_audit_events_policy_digest_len CHECK (
                policy_digest IS NULL OR octet_length(policy_digest) = 32
            ),
            CONSTRAINT security_audit_events_request_id_len CHECK (
                length(coalesce(request_id, '')) <= 128
            ),
            CONSTRAINT security_audit_events_trace_id_len CHECK (
                length(coalesce(trace_id, '')) <= 128
            ),
            CONSTRAINT security_audit_events_ua_digest_len CHECK (
                user_agent_digest IS NULL OR octet_length(user_agent_digest) = 32
            ),
            -- The rule-5 backstop. An audit row is a decision record; if somebody
            -- starts putting model output in ``detail`` this is what stops them.
            --
            -- Slack against the 2 KiB the API enforces on the JSON encoding:
            -- pg_column_size measures jsonb's binary layout, which is a different
            -- quantity. A writer going through the API can never reach this; one that
            -- bypassed it is what the constraint is for.
            CONSTRAINT security_audit_events_detail_bounded CHECK (
                pg_column_size(detail) <= 4096
            )
        ) PARTITION BY RANGE (occurred_at);
    """)

    # Declared on the parent so every partition inherits them. Ordered DESC to match the
    # keyset reads the console issues; there is no OFFSET path to support.
    op.execute("""
        CREATE INDEX security_audit_events_org_time_idx
            ON security_audit_events (org_id, occurred_at DESC, id DESC);
        CREATE INDEX security_audit_events_org_category_idx
            ON security_audit_events (org_id, category, occurred_at DESC);
        CREATE INDEX security_audit_events_actor_idx
            ON security_audit_events (org_id, actor_kind, actor_id, occurred_at DESC);
        CREATE INDEX security_audit_events_target_idx
            ON security_audit_events (org_id, target_id, occurred_at DESC)
            WHERE target_id IS NOT NULL;
        CREATE INDEX security_audit_events_denied_idx
            ON security_audit_events (org_id, occurred_at DESC)
            WHERE outcome = 'denied' OR severity = 'critical';
        CREATE INDEX security_audit_events_trace_idx
            ON security_audit_events (org_id, trace_id)
            WHERE trace_id IS NOT NULL;
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION forbid_security_audit_mutation() RETURNS trigger AS $$
        BEGIN
            IF coalesce(current_setting('app.partition_maintenance', true), 'off') = 'on'
            THEN
                RETURN CASE TG_OP WHEN 'DELETE' THEN OLD ELSE NEW END;
            END IF;

            RAISE EXCEPTION 'security_audit_events is append-only: % is forbidden', TG_OP
                USING HINT = 'expire audit history by dropping a partition';
        END;
        $$ LANGUAGE plpgsql;

        CREATE TRIGGER security_audit_events_append_only
            BEFORE UPDATE OR DELETE ON security_audit_events
            FOR EACH ROW EXECUTE FUNCTION forbid_security_audit_mutation();
    """)

    op.execute("""
        CREATE TABLE security_audit_events_default
            PARTITION OF security_audit_events DEFAULT;
    """)

    # Same shape as ensure_run_partition and ensure_evidence_partition, written out
    # again rather than generalised: three explicit functions review better than one
    # that builds statements from an identifier argument.
    op.execute("""
        CREATE OR REPLACE FUNCTION ensure_security_audit_partition(p_month date)
        RETURNS text AS $$
        DECLARE
            lo    date := date_trunc('month', p_month)::date;
            hi    date := (date_trunc('month', p_month) + interval '1 month')::date;
            name  text := 'security_audit_events_' || to_char(lo, 'YYYYMM');
            moved integer := 0;
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_class WHERE relname = name) THEN
                RETURN name;
            END IF;

            EXECUTE format(
                'CREATE TABLE %I (LIKE security_audit_events INCLUDING DEFAULTS '
                'INCLUDING CONSTRAINTS)', name);

            SET LOCAL app.partition_maintenance = 'on';

            EXECUTE format(
                'INSERT INTO %I SELECT * FROM security_audit_events_default '
                'WHERE occurred_at >= %L AND occurred_at < %L', name, lo, hi);
            GET DIAGNOSTICS moved = ROW_COUNT;

            EXECUTE format(
                'DELETE FROM security_audit_events_default '
                'WHERE occurred_at >= %L AND occurred_at < %L', lo, hi);

            EXECUTE format(
                'ALTER TABLE security_audit_events ATTACH PARTITION %I '
                'FOR VALUES FROM (%L) TO (%L)', name, lo, hi);

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
                    date_trunc('month', now()) - interval '13 months',
                    date_trunc('month', now()) + interval '3 months',
                    interval '1 month'
                )::date
            LOOP
                PERFORM ensure_security_audit_partition(m);
            END LOOP;
        END $$;
    """)


def _row_level_security() -> None:
    """RLS on every tenant table, plus reference-read for built-in roles.

    ``roles`` is the one table here with global rows, so it gets the two-policy shape
    that ``obligation_templates`` uses: reference rows readable by all, writable by none.
    """
    for table in _TENANT_TABLES:
        if table == "roles":
            continue
        op.execute(f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY {table}_tenant_isolation ON {table}
                USING (current_org_matches(org_id))
                WITH CHECK (current_org_matches(org_id));
        """)

    op.execute("""
        ALTER TABLE roles ENABLE ROW LEVEL SECURITY;
        ALTER TABLE roles FORCE ROW LEVEL SECURITY;
        CREATE POLICY roles_reference_read ON roles
            FOR SELECT
            USING (org_id IS NULL OR current_org_matches(org_id));
        CREATE POLICY roles_tenant_write ON roles
            FOR ALL
            USING (current_org_matches(org_id))
            WITH CHECK (current_org_matches(org_id));
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS security_audit_events CASCADE;
        DROP FUNCTION IF EXISTS ensure_security_audit_partition(date);
        DROP FUNCTION IF EXISTS forbid_security_audit_mutation();

        DROP TABLE IF EXISTS mcp_capability_usage_daily CASCADE;
        DROP TABLE IF EXISTS mcp_grants CASCADE;
        DROP TABLE IF EXISTS mcp_capabilities CASCADE;
        DROP TABLE IF EXISTS mcp_snapshots CASCADE;
        DROP TABLE IF EXISTS mcp_servers CASCADE;
        DROP FUNCTION IF EXISTS forbid_mcp_capability_rewrite();
        DROP FUNCTION IF EXISTS forbid_mcp_snapshot_rewrite();

        DROP TABLE IF EXISTS connection_grants CASCADE;
        DROP TABLE IF EXISTS connection_secret_versions CASCADE;
        DROP TABLE IF EXISTS provider_connections CASCADE;

        DROP TABLE IF EXISTS access_requests CASCADE;
        DROP TABLE IF EXISTS access_grants CASCADE;
        DROP TABLE IF EXISTS roles CASCADE;
        DROP TABLE IF EXISTS team_members CASCADE;
        DROP TABLE IF EXISTS member_identities CASCADE;
        DROP TABLE IF EXISTS members CASCADE;
        DROP TABLE IF EXISTS teams CASCADE;

        DROP TYPE IF EXISTS audit_severity;
        DROP TYPE IF EXISTS audit_outcome;
        DROP TYPE IF EXISTS audit_actor_kind;
        DROP TYPE IF EXISTS health_state;
        DROP TYPE IF EXISTS risk_tier;
        DROP TYPE IF EXISTS mcp_capability_kind;
        DROP TYPE IF EXISTS mcp_server_state;
        DROP TYPE IF EXISTS mcp_trust_tier;
        DROP TYPE IF EXISTS mcp_transport;
        DROP TYPE IF EXISTS connection_status;
        DROP TYPE IF EXISTS connection_auth_kind;
        DROP TYPE IF EXISTS connection_provider_kind;
        DROP TYPE IF EXISTS access_request_state;
        DROP TYPE IF EXISTS access_scope_kind;
        DROP TYPE IF EXISTS access_subject_kind;
        DROP TYPE IF EXISTS member_status;
    """)
