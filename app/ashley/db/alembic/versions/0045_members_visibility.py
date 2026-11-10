"""Household money is heard by any member alone: `members` joins the visibilities, and money no owner said to keep
private becomes the household's."""

from alembic import op

revision: str = "0045"
down_revision: str | None = "0044"


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE facts
            DROP CONSTRAINT facts_visibility_check,
            ADD CONSTRAINT facts_visibility_check
                CHECK (visibility IN ('shared', 'discreet', 'members', 'private'));
        UPDATE facts SET owner_id = NULL, visibility = 'members'
            WHERE kind = 'finance' AND NOT visibility_stated AND valid_to IS NULL;
        """
    )
