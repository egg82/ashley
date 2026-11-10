"""A conversation records the channel and place it started on. Both are null for conversations from before."""

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE conversations
            ADD COLUMN channel text CHECK (channel IN ('voice', 'discord', 'device', 'web')),
            ADD COLUMN place text;
        """
    )
