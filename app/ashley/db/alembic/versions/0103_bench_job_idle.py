"""A Claude Code bench job that sits idle without a result is prompted once to finish: `idle_since` is when it was first
seen idle since it last worked, `nudged_at` when the prompt was sent, so a retake on either site never sends a second."""

from alembic import op

revision: str = "0103"
down_revision: str | None = "0102"


def upgrade() -> None:
    op.execute("ALTER TABLE bench_jobs ADD COLUMN idle_since timestamptz, ADD COLUMN nudged_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE bench_jobs DROP COLUMN idle_since, DROP COLUMN nudged_at")
