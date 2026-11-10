"""A person's turn may carry the block they pasted with it: an optional title and the text, kept beside the turn and read
with it. Both columns are null together on every turn that has none."""

from alembic import op

revision: str = "0050"
down_revision: str | None = "0049"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE turns
            ADD COLUMN attachment text,
            ADD COLUMN attachment_title text,
            ADD CONSTRAINT turns_attachment_title_needs_text CHECK (attachment_title IS NULL OR attachment IS NOT NULL),
            ADD CONSTRAINT turns_attachment_is_a_persons CHECK (attachment IS NULL OR author = 'person');
        """
    )
