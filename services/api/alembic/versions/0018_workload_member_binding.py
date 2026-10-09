"""Bind personal workload credentials to verified account members.

The binding is explicit. ``created_by`` is an audit actor and cannot be used as the
person whose activity a credential represents: administrators routinely issue keys for
other people and for shared services.

Hand-written per AGENTS.md rule 7.

Revision ID: 0018_workload_member_binding
Revises: 0017_account_access_registry
Create Date: 2026-09-18
"""

from __future__ import annotations

from alembic import op

revision = "0018_workload_member_binding"
down_revision = "0017_account_access_registry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE workload_credentials
            ADD COLUMN member_id uuid;

        ALTER TABLE workload_credentials
            ADD CONSTRAINT workload_credentials_member_same_org_fkey
            FOREIGN KEY (org_id, member_id)
            REFERENCES members (org_id, id)
            ON DELETE SET NULL (member_id);

        CREATE INDEX workload_credentials_member_idx
            ON workload_credentials (org_id, member_id)
            WHERE member_id IS NOT NULL;
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS workload_credentials_member_idx;
        ALTER TABLE workload_credentials
            DROP CONSTRAINT IF EXISTS workload_credentials_member_same_org_fkey;
        ALTER TABLE workload_credentials DROP COLUMN IF EXISTS member_id;
    """)
