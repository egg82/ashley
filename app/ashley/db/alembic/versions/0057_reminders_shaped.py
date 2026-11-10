"""A reminder carries where its words go (`route`) and the tools its turn may use (`tools`, NULL for the ones that only
read); a proposal may be for a plain reminder or an edit of one (`rule` NULL, `due_at`, `repeat`, `route`, `tools`,
`target`), so acting reminders are agreed to before they exist."""

from alembic import op

revision: str = "0057"
down_revision: str | None = "0056"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE wakes
            ADD COLUMN route text NOT NULL DEFAULT 'phone' CHECK (route IN ('phone', 'quiet')),
            ADD COLUMN tools text[];
        ALTER TABLE deposit_proposals
            ALTER COLUMN rule DROP NOT NULL,
            ADD COLUMN due_at timestamptz,
            ADD COLUMN repeat jsonb CHECK (jsonb_typeof(repeat) = 'object'),
            ADD COLUMN route text NOT NULL DEFAULT 'phone' CHECK (route IN ('phone', 'quiet')),
            ADD COLUMN tools text[],
            ADD COLUMN target bigint;
        """
    )
