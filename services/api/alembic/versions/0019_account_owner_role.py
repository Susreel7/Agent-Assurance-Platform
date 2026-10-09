"""The built-in role a tenant's first member holds.

Every other built-in role is deliberately partial: an approver cannot rotate keys, a
security admin cannot publish an agent. That separation is right once an account has
staff, and wrong on the day it is provisioned, because there is nobody to grant the
first person anything. Without an owner the first sign-in resolves to a member with no
grants, and every guarded route answers 403.

``account_owner`` is therefore the one role that unions the whole vocabulary, assignable
only at account scope. It is flagged ``separation_of_duty`` so an account that has grown
past one person can see in the grant list that it still holds a combined role.

Hand-written per AGENTS.md rule 7.

Revision ID: 0019_account_owner_role
Revises: 0018_workload_member_binding
Create Date: 2026-09-18
"""

from __future__ import annotations

from alembic import op

revision = "0019_account_owner_role"
down_revision = "0018_workload_member_binding"
branch_labels = None
depends_on = None

# Kept literal rather than derived from the application's PERMISSIONS set: a migration
# that changes shape when Python changes is not a migration. Mirrors app.domains.access.
_PERMISSIONS = [
    "member:read",
    "member:write",
    "team:read",
    "team:write",
    "project:read",
    "project:write",
    "agent:read",
    "agent:write",
    "agent:run",
    "agent:publish",
    "activity:read",
    "activity:replay",
    "registry:read",
    "registry:write",
    "prompt:write",
    "evaluate:write",
    "connection:read",
    "connection:write",
    "connection:rotate",
    "key:read",
    "key:write",
    "key:revoke",
    "mcp:read",
    "mcp:write",
    "mcp:discover",
    "mcp:invoke",
    "mcp:approve",
    "mcp:grant",
    "mcp:quarantine",
    "assurance:read",
    "evidence:read",
    "policy:write",
    "release:approve",
    "accreditation:approve",
    "materiality:adjudicate",
    "access:read",
    "access:write",
    "access:approve",
    "payload:reveal",
    "audit:read",
]


def upgrade() -> None:
    permissions = ", ".join(f"'{permission}'" for permission in _PERMISSIONS)
    op.execute(f"""
        INSERT INTO roles (org_id, key, name, description, builtin, permissions,
                           assignable_scopes, separation_of_duty)
        VALUES
        (NULL, 'account_owner', 'Account owner',
         'Full control of the account. Held by whoever provisions it.', true,
         ARRAY[{permissions}],
         ARRAY['account']::access_scope_kind[], true)
        ON CONFLICT DO NOTHING;
    """)


def downgrade() -> None:
    op.execute("""
        DELETE FROM access_grants WHERE role_key = 'account_owner';
        DELETE FROM roles WHERE org_id IS NULL AND key = 'account_owner';
    """)
