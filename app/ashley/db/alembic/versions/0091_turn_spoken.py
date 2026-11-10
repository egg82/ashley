"""A turn of hers can keep what she chose to say aloud (`turns.spoken`), so a page she was spoken to from can play it.
Only her turns carry one, and never an empty one."""

from alembic import op

revision: str = "0091"
down_revision: str | None = "0090"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE turns ADD COLUMN spoken text,
            ADD CONSTRAINT turns_spoken_hers CHECK (spoken IS NULL OR (author = 'ashley' AND spoken <> ''))""")


def downgrade() -> None:
    op.execute("ALTER TABLE turns DROP CONSTRAINT turns_spoken_hers, DROP COLUMN spoken")
