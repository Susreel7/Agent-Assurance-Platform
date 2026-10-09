"""Give an existing unadministered account to its earliest live identity.

Revision ID: 0020_backfill_account_owner
Revises: 0019_account_owner_role
Create Date: 2026-09-19
"""

from __future__ import annotations

from alembic import op

revision = "0020_backfill_account_owner"
down_revision = "0019_account_owner_role"
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
        ),
        unadministered AS (
            SELECT owner.org_id, owner.member_id
            FROM first_live_identity AS owner
            WHERE NOT EXISTS (
                SELECT 1
                FROM access_grants AS grant_row
                JOIN roles AS role_row
                  ON role_row.key = grant_row.role_key
                 AND (
                     role_row.org_id IS NULL
                     OR role_row.org_id = grant_row.org_id
                 )
                JOIN member_identities AS administrator
                  ON administrator.org_id = grant_row.org_id
                 AND administrator.revoked_at IS NULL
                 AND (
                     (
                         grant_row.subject_kind = 'member'
                         AND grant_row.subject_id = administrator.member_id
                     )
                     OR (
                         grant_row.subject_kind = 'team'
                         AND EXISTS (
                             SELECT 1
                             FROM team_members AS membership
                             WHERE membership.org_id = grant_row.org_id
                               AND membership.team_id = grant_row.subject_id
                               AND membership.member_id = administrator.member_id
                         )
                     )
                 )
                WHERE grant_row.org_id = owner.org_id
                  AND grant_row.revoked_at IS NULL
                  AND (
                      grant_row.expires_at IS NULL
                      OR grant_row.expires_at > now()
                  )
                  AND 'access:write' = ANY(role_row.permissions)
            )
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
            org_id,
            'member'::access_subject_kind,
            member_id,
            'account_owner',
            'account'::access_scope_kind,
            NULL,
            'migration:0020',
            'backfill owner for account with no live directory administrator'
        FROM unadministered
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM access_grants
        WHERE role_key = 'account_owner'
          AND granted_by = 'migration:0020';
    """)
