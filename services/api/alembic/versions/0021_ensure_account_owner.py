"""Ensure every existing account with a live identity has an account owner.

``security_admin`` can grant access but intentionally cannot read people or projects.
The previous backfill therefore mistook a partial administrator for an account owner.

Revision ID: 0021_ensure_account_owner
Revises: 0020_backfill_account_owner
Create Date: 2026-09-19
"""

from __future__ import annotations

from alembic import op

revision = "0021_ensure_account_owner"
down_revision = "0020_backfill_account_owner"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        WITH first_live_identity AS (
            SELECT DISTINCT ON (mi.org_id)
                mi.org_id,
                mi.member_id
            FROM member_identities AS mi
            JOIN members AS m
              ON m.org_id = mi.org_id
             AND m.id = mi.member_id
            WHERE mi.revoked_at IS NULL
              AND m.status = 'active'
            ORDER BY mi.org_id, mi.created_at, mi.id
        )
        INSERT INTO access_grants (
            org_id,
            subject_kind,
            subject_id,
            role_key,
            scope_kind,
            scope_id,
            granted_by,
            reason
        )
        SELECT
            owner.org_id,
            'member'::access_subject_kind,
            owner.member_id,
            'account_owner',
            'account'::access_scope_kind,
            NULL,
            'migration:0021',
            'ensure account has a full owner rather than only partial administrators'
        FROM first_live_identity AS owner
        WHERE NOT EXISTS (
            SELECT 1
            FROM access_grants AS grant_row
            WHERE grant_row.org_id = owner.org_id
              AND grant_row.role_key = 'account_owner'
              AND grant_row.revoked_at IS NULL
              AND (
                  grant_row.expires_at IS NULL
                  OR grant_row.expires_at > now()
              )
        )
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM access_grants
        WHERE role_key = 'account_owner'
          AND granted_by = 'migration:0021';
    """)
