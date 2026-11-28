"""What her calls brought up beside her words is kept with her turn (`turns.shown`, a list of `{kind, ref}`, only hers):
code sets it from her tools' results, never from her text."""

from alembic import op

revision: str = "0144"
down_revision: str | None = "0143"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE turns ADD COLUMN shown jsonb NOT NULL DEFAULT '[]'::jsonb,
            ADD CONSTRAINT turns_shown_hers CHECK (shown = '[]'::jsonb OR author = 'ashley')""")


def downgrade() -> None:
    op.execute("ALTER TABLE turns DROP CONSTRAINT turns_shown_hers, DROP COLUMN shown")
