"""${message}

Hand-written per AGENTS.md rule 7. Before writing this migration, confirm:

  * Does it touch an append-only table? Those have immutability triggers; adding a
    column is fine, changing existing rows is not.
  * Does it need a row-level security policy? Every tenant-scoped table gets one.
  * Does it need an index for a query that actually exists? Do not add speculative ones.
  * Does it use any Postgres extension beyond pgcrypto? Managed Postgres will refuse.
  * Is the downgrade correct? It is rarely run, but a wrong one is worse than none.

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision = ${repr(up_revision)}
down_revision = ${repr(down_revision)}
branch_labels = ${repr(branch_labels)}
depends_on = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "raise NotImplementedError"}


def downgrade() -> None:
    ${downgrades if downgrades else "raise NotImplementedError"}
