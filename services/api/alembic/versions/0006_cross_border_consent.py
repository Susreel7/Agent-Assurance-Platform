"""Add `permitted_with_consent` as a fourth cross-border rung.

Closes Q-011, which is a process failure as much as a schema one.

D-021 split the cross-border ladder into four rungs: `prohibited`,
`permitted_with_safeguards`, `permitted_with_consent`, `permitted`. Consent under GDPR
Article 49 and safeguards under Article 46 are different legal bases, and consent is the
weaker of the two because it is withdrawable and carries no continuing obligation. An
engagement that agreed one and an agent that declares the other are genuinely in
conflict, and collapsing them hid a material change behind a synonym.

That decision was first applied by editing the `CHECK` constraint inside `0002` — which
had already run. A database created afterwards got four values; every database already
past `0002` kept three and rejected `permitted_with_consent` on insert, while both
reported the same head revision. The seed generator found it by failing on a real
constraint violation. `0002` has been restored to its shipped text and the widening
lives here, which is the only arrangement where both populations converge on the same
schema.

This revision is written to be safe on either population: it drops the constraint by
name if present and adds the four-value form, so it is correct whether it meets the
three-value original or a database that briefly carried the edited version.

Hand-written per AGENTS.md rule 7.

Revision ID: 0006_cross_border_consent
Revises: 0005_assurance
Create Date: 2026-09-13
"""

from __future__ import annotations

from alembic import op

revision = "0006_cross_border_consent"
down_revision = "0005_assurance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE engagements
            DROP CONSTRAINT IF EXISTS engagements_cross_border_valid;
    """)
    op.execute("""
        ALTER TABLE engagements
            ADD CONSTRAINT engagements_cross_border_valid CHECK (
                cross_border_transfer IN
                    ('prohibited','permitted_with_safeguards',
                     'permitted_with_consent','permitted')
            );
    """)


def downgrade() -> None:
    # Rows on the rung being removed have to go somewhere, and they cannot simply be
    # narrowed to `permitted`: that would silently record a weaker transfer basis than
    # the engagement agreed. `permitted_with_safeguards` is the conservative direction —
    # it overstates the protection in place rather than understating it, so a later
    # comparison against an agent errs towards flagging a change rather than missing one.
    op.execute("""
        UPDATE engagements
           SET cross_border_transfer = 'permitted_with_safeguards'
         WHERE cross_border_transfer = 'permitted_with_consent';
    """)
    op.execute("""
        ALTER TABLE engagements
            DROP CONSTRAINT IF EXISTS engagements_cross_border_valid;
    """)
    op.execute("""
        ALTER TABLE engagements
            ADD CONSTRAINT engagements_cross_border_valid CHECK (
                cross_border_transfer IN
                    ('prohibited','permitted_with_safeguards','permitted')
            );
    """)
