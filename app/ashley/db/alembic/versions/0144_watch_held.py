"""A person can pause a watch: `held_at` is when they did, null for a watch running as usual. It is kept apart from `state`,
which says how the reads are going."""

from alembic import op

revision: str = "0144"
down_revision: str | None = "0143"


def upgrade() -> None:
    op.execute("ALTER TABLE watches ADD COLUMN held_at timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE watches DROP COLUMN held_at")
