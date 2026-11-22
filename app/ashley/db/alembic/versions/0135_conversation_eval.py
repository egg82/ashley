"""A conversation an evaluation opened is marked (`eval`), so the person's conversation list and their last word leave it
out. The ones the reach and house evals already opened are found by the thread ids those evals wrote."""

from alembic import op

revision: str = "0135"
down_revision: str | None = "0134"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE conversations ADD COLUMN eval boolean NOT NULL DEFAULT false;
        UPDATE conversations SET eval = true WHERE thread LIKE 'reach-eval-%' OR thread LIKE 'house-eval-%'""")


def downgrade() -> None:
    op.execute("ALTER TABLE conversations DROP COLUMN eval")
