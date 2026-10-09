"""Bind verified token claims to organisations.

Closes Q-004. Until now the organisation came from an `X-Org-Id` request header, which
any caller could set to any value — the only thing standing between two tenants was a
string the client chose. This table is the replacement: the other half of it is
`app/auth`, which verifies the token these claims come from.

**Why a table rather than a claim.** The obvious design reads the organisation from an
`org_id` claim. That only works when we control the identity provider. An enterprise
customer authenticating against their own Entra or Okta tenant will not add a claim for
us, and asking them to is the kind of request that turns a two-week pilot into a
two-quarter one. So the mapping lives on our side: they tell us their issuer and tenant
id, we bind it to their organisation.

The binding is (issuer, claim_name, claim_value) because the value alone is not unique.
Entra's `tid` is a GUID that is unique globally, but a Keycloak realm's `iss` or a Google
Workspace `hd` is only meaningful alongside which provider asserted it, and a binding
that matched on value alone would let any issuer claim any tenant.

`org_id` is intentionally *not* part of the unique key. One binding resolves to exactly
one organisation, or the request is ambiguous and there is no safe way to pick.

Hand-written per AGENTS.md rule 7.

Revision ID: 0007_identity_bindings
Revises: 0006_cross_border_consent
Create Date: 2026-09-13
"""

from __future__ import annotations

from alembic import op

revision = "0007_identity_bindings"
down_revision = "0006_cross_border_consent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE identity_bindings (
            id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            org_id      uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

            -- The `iss` claim of tokens this binding accepts, stored without a trailing
            -- slash so the two spellings of the same issuer cannot both exist.
            issuer      text NOT NULL,
            claim_name  text NOT NULL,
            claim_value text NOT NULL,

            -- Free text for whoever has to work out why a customer cannot log in.
            note        text,

            -- A binding is the authorisation decision "this directory speaks for this
            -- customer". Who made it and when is audit material, not metadata.
            created_at  timestamptz NOT NULL DEFAULT now(),
            created_by  text NOT NULL,
            disabled_at timestamptz,

            CONSTRAINT identity_bindings_issuer_normalised CHECK (
                issuer = rtrim(issuer, '/') AND issuer <> ''
            ),
            CONSTRAINT identity_bindings_claim_name_present CHECK (claim_name <> ''),
            CONSTRAINT identity_bindings_claim_value_present CHECK (claim_value <> '')
        );
    """)

    # Partial unique index rather than a constraint: a disabled binding has to remain on
    # the table as a record that it once existed, and must not block re-creating it.
    op.execute("""
        CREATE UNIQUE INDEX identity_bindings_live_key
            ON identity_bindings (issuer, claim_name, claim_value)
         WHERE disabled_at IS NULL;
    """)
    op.execute("""
        CREATE INDEX identity_bindings_org_idx ON identity_bindings (org_id);
    """)

    # Row-level security, same as every other table carrying an org_id.
    #
    # The first draft left it off, reasoning that a table read *to determine* the
    # organisation has nothing to scope by yet. `tests/sql/invariants.sql` rejected that
    # within the hour, and it was right to: `current_org_matches` has an explicit bypass
    # that `admin_session` sets, so the pre-tenant lookup in `app/auth/orgs.py` works
    # with the policy in place. Enabling it costs nothing and means a future read through
    # a tenant session — the mistake the backstop exists for — sees only its own rows.
    op.execute("""
        ALTER TABLE identity_bindings ENABLE ROW LEVEL SECURITY;
        ALTER TABLE identity_bindings FORCE ROW LEVEL SECURITY;
        CREATE POLICY identity_bindings_tenant_isolation ON identity_bindings
            USING (current_org_matches(org_id))
            WITH CHECK (current_org_matches(org_id));
    """)

    op.execute("""
        COMMENT ON TABLE identity_bindings IS
            'Maps verified OIDC claims to organisations. Read pre-tenant through an '
            'admin session, which bypasses the policy below. See app/auth/orgs.py.';
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS identity_bindings;")
