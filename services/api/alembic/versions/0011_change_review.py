"""Semantic review — composition change categories and digest-bound approval.

Revision ID: 0011_change_review
Revises: 0010_agent_composition
Create Date: 2026-03-23

Extends the release diff vocabulary so composition elements diff by stable identity,
including renames. Approval can bind to the exact descriptor digest that was reviewed.
"""

from alembic import op

revision = "0011_change_review"
down_revision = "0010_agent_composition"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE change_operation ADD VALUE IF NOT EXISTS 'renamed'")
    for value in (
        "skill",
        "sub_agent",
        "config",
        "rule_obligation",
        "model_policy",
        "memory_retrieval",
        "rule_source",
    ):
        op.execute(f"ALTER TYPE change_category ADD VALUE IF NOT EXISTS '{value}'")
    op.execute(
        """
        ALTER TABLE releases
            ADD COLUMN IF NOT EXISTS reviewed_descriptor_digest text;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE releases DROP COLUMN IF EXISTS reviewed_descriptor_digest")
    # PostgreSQL cannot remove enum values safely; leave extended types in place.
