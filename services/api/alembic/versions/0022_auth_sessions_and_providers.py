"""Server-side console sessions, and auth providers as data rather than build flags.

Two tables, for the two halves of the login defect this revision closes.

``auth_providers`` moves the decision "which sign-in buttons exist" out of the browser's
build-time environment and into the database, keyed by account. Today the console reads
``VITE_OIDC_ISSUER`` at build time and decides for itself whether Entra is configured,
which means a misconfigured deployment renders a button that cannot work and a correct
one cannot be changed without a rebuild. See `design/02-identity-and-onboarding.md`.

``auth_sessions`` makes the session durable and revocable. The console currently keeps a
provider access token in ``sessionStorage`` and writes it *before* server-side onboarding
has been attempted, so "a session exists but the member is not bound" is representable —
and is exactly what a reload turns into a different, stranger error. A row here is created
only after a member has been resolved, which makes that state unrepresentable instead.

Named ``auth_sessions``, deliberately not ``sessions``: F1 introduces ``agent_sessions``
for agent context windows, and two tables whose names differ by a prefix nobody types is
a defect waiting to happen.

``org_id`` rather than ``account_id`` throughout. The ``organizations`` → ``accounts``
rename is F1's to make, and half-renaming here would leave the tenant root ambiguous
across two revisions.

Hand-written per AGENTS.md rule 7.

Revision ID: 0022_auth_sessions_and_providers
Revises: 0021_ensure_account_owner
Create Date: 2026-09-22
"""

from __future__ import annotations

from alembic import op

revision = "0022_auth_sessions_and_providers"
down_revision = "0021_ensure_account_owner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    _auth_providers()
    _auth_sessions()
    _row_level_security()
    _seed_development_provider()


def _auth_providers() -> None:
    """One row per way into an account.

    The ``kind`` vocabulary is deliberately narrower than the five kinds in `design/02`.
    A row whose kind no verification path implements is a provider that renders a button
    and authenticates nobody, which is the failure mode this whole revision exists to
    remove. ``saml``, ``ldap`` and ``local`` join the CHECK in the revision that
    implements them.
    """
    op.execute("""
        CREATE TABLE auth_providers (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            kind text NOT NULL,
            label text NOT NULL,
            issuer text,
            client_id text,
            client_secret_ref uuid,
            jwks_uri text,
            authorize_url text,
            token_url text,
            scopes text NOT NULL DEFAULT 'openid profile email',
            claim_map jsonb NOT NULL DEFAULT '{}'::jsonb,
            group_claim text,
            email_domains text[] NOT NULL DEFAULT '{}'::text[],
            onboarding_mode text NOT NULL DEFAULT 'invite',
            require_mfa_claim boolean NOT NULL DEFAULT false,
            precedence integer NOT NULL DEFAULT 100,
            enabled boolean NOT NULL DEFAULT true,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),

            CONSTRAINT auth_providers_kind_known
                CHECK (kind IN ('oidc', 'development')),
            -- Narrowed for the same reason as `kind` above: `scim`, `directory_pull`
            -- and `bulk` describe how members arrive *before* anybody signs in, and no
            -- sync path implements them yet. A row claiming one of them would silently
            -- behave as `invite`, which is a configuration that lies about itself.
            CONSTRAINT auth_providers_onboarding_mode_known
                CHECK (onboarding_mode IN ('invite', 'jit')),
            CONSTRAINT auth_providers_label_present
                CHECK (label <> '' AND length(label) <= 128),
            -- An OIDC row without these four cannot complete a code exchange. Refusing it
            -- here means the failure surfaces when an operator configures the provider,
            -- not when the first employee tries to sign in on a Monday morning.
            CONSTRAINT auth_providers_oidc_is_complete CHECK (
                kind <> 'oidc'
                OR (
                    issuer IS NOT NULL AND issuer <> ''
                    AND client_id IS NOT NULL AND client_id <> ''
                    AND authorize_url IS NOT NULL AND authorize_url <> ''
                    AND token_url IS NOT NULL AND token_url <> ''
                )
            ),
            -- `jit` provisions a member from a claim set alone, so the allowlist is the
            -- only thing standing between "anyone the IdP will sign in" and a member row.
            CONSTRAINT auth_providers_jit_needs_domains CHECK (
                onboarding_mode <> 'jit' OR cardinality(email_domains) > 0
            ),
            CONSTRAINT auth_providers_secret_ref_fkey
                FOREIGN KEY (org_id, client_secret_ref)
                REFERENCES provider_connections (org_id, id)
                ON DELETE SET NULL (client_secret_ref),
            CONSTRAINT auth_providers_org_id_id_key UNIQUE (org_id, id)
        );

        -- One issuer means one provider per account: two rows for the same issuer make
        -- "which claim_map applies to this token" ambiguous, and the answer decides who
        -- the caller is.
        CREATE UNIQUE INDEX auth_providers_org_issuer_idx
            ON auth_providers (org_id, issuer)
            WHERE issuer IS NOT NULL;

        -- The login screen's query: enabled rows for this account in button order.
        CREATE INDEX auth_providers_enabled_idx
            ON auth_providers (org_id, precedence, id)
            WHERE enabled;

        -- Account discovery by email domain, unauthenticated. GIN because the question is
        -- "which provider lists this domain", and the array is short but the table is
        -- scanned before we know who is asking.
        CREATE INDEX auth_providers_email_domains_idx
            ON auth_providers USING gin (email_domains);
    """)


def _auth_sessions() -> None:
    """The console session, held server side so it can be listed and revoked.

    ``token_hash`` is a SHA-256 of the opaque cookie value and is globally unique, not
    unique per account: the cookie is presented before any tenant is known, so the lookup
    that resolves it cannot be scoped. Storing the hash rather than the value means a
    database backup is not a set of live sessions.

    There is no separate refresh token. Renewal extends ``expires_at`` against the
    ``absolute_expires_at`` ceiling, which is the property that matters — a session
    cannot outlive its ceiling however often it is renewed. A second token would only
    shorten the replay window for a value the browser never has access to anyway, since
    the cookie is ``HttpOnly``.
    """
    op.execute("""
        CREATE TABLE auth_sessions (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
            member_id uuid NOT NULL,
            provider_id uuid,
            token_hash bytea NOT NULL,
            -- The verified principal, stored with the session that it created.
            -- Not a denormalisation of `member_identities`: those rows say who a person
            -- *is now*, and these say who signed in *then*. The request pipeline needs
            -- them on every request to build a `Principal` without a second query, and
            -- an audit row written during this session should name the identity that
            -- started it even if the member is rebound or renamed afterwards.
            identity_issuer text NOT NULL,
            identity_subject text NOT NULL,
            identity_email text,
            -- The directory groups the provider asserted at sign-in. Frozen for the life
            -- of the session, exactly as they were frozen for the life of a bearer token
            -- before this — and now bounded by `absolute_expires_at`, which a token's
            -- own expiry never was under our control.
            identity_groups text[] NOT NULL DEFAULT '{}'::text[],
            issued_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL,
            absolute_expires_at timestamptz NOT NULL,
            last_seen_at timestamptz NOT NULL DEFAULT now(),
            revoked_at timestamptz,
            revoked_reason text,
            mfa_verified boolean NOT NULL DEFAULT false,
            client_ip inet,
            user_agent text,
            created_at timestamptz NOT NULL DEFAULT now(),

            -- Silent renew may extend `expires_at`, never past the absolute ceiling.
            -- Without this a session refreshed every four minutes lives forever, which
            -- is the property deprovisioning is supposed to remove.
            CONSTRAINT auth_sessions_expiry_ordering
                CHECK (expires_at <= absolute_expires_at),
            CONSTRAINT auth_sessions_revoked_reason_present
                CHECK (revoked_at IS NULL OR revoked_reason IS NOT NULL),
            CONSTRAINT auth_sessions_user_agent_bounded
                CHECK (user_agent IS NULL OR length(user_agent) <= 512),
            CONSTRAINT auth_sessions_member_same_org_fkey
                FOREIGN KEY (org_id, member_id)
                REFERENCES members (org_id, id)
                ON DELETE CASCADE,
            CONSTRAINT auth_sessions_provider_same_org_fkey
                FOREIGN KEY (org_id, provider_id)
                REFERENCES auth_providers (org_id, id)
                ON DELETE SET NULL (provider_id),
            CONSTRAINT auth_sessions_org_id_id_key UNIQUE (org_id, id)
        );

        -- The hot path: one cookie presented on every request, resolved before the tenant
        -- is known. Unique rather than merely indexed so a hash collision or a replayed
        -- insert is a constraint violation instead of two live sessions.
        CREATE UNIQUE INDEX auth_sessions_token_hash_idx ON auth_sessions (token_hash);

        -- The profile page's "your sessions" list, and the deprovisioning sweep.
        CREATE INDEX auth_sessions_member_live_idx
            ON auth_sessions (org_id, member_id, issued_at DESC)
            WHERE revoked_at IS NULL;
        CREATE INDEX auth_sessions_expiring_idx
            ON auth_sessions (absolute_expires_at)
            WHERE revoked_at IS NULL;
    """)


def _row_level_security() -> None:
    """Both tables are tenant-owned, so both get the standard policy.

    The cookie lookup deliberately runs under ``admin_session`` — it has no tenant to
    scope to until it has resolved one — so these policies guard every other reader:
    the provider list, the session list on the profile page, and revocation.
    """
    for table in ("auth_providers", "auth_sessions"):
        op.execute(f"""
            ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
            ALTER TABLE {table} FORCE ROW LEVEL SECURITY;
            CREATE POLICY {table}_tenant_isolation ON {table}
                USING (current_org_matches(org_id))
                WITH CHECK (current_org_matches(org_id));
        """)


def _seed_development_provider() -> None:
    """A local stub provider, for the ``default`` organisation only.

    ``default`` is the organisation migration 0001 seeds; a provisioned production
    account does not have it, so this row does not appear in a customer's database. The
    runtime refuses the ``development`` kind outside ``AAP_ENVIRONMENT=development`` and
    omits it from ``/v1/auth/config`` there as well, so the row is inert even if it is
    somehow carried into a production database by a restore.

    The email domain is ``localhost`` and must stay that way. A real company domain here
    would make a development convenience look like a production identity in the audit
    trail.
    """
    op.execute("""
        INSERT INTO auth_providers (
            org_id, kind, label, claim_map, email_domains, onboarding_mode, precedence
        )
        SELECT
            id,
            'development',
            'Continue as a local developer',
            '{"subject": "sub", "email": ["email"], "name": ["name"]}'::jsonb,
            ARRAY['localhost']::text[],
            'invite',
            900
        FROM organizations
        WHERE slug = 'default'
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS auth_sessions CASCADE;
        DROP TABLE IF EXISTS auth_providers CASCADE;
    """)
