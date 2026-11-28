"""A piece on a bench has no size class any more (the mindmap draws it by its own box); only a piece on a device's screen
has one, so `place_size` may be null. Pieces already stored keep the size they had."""

from alembic import op

revision: str = "0144"
down_revision: str | None = "0143"


def upgrade() -> None:
    op.execute("ALTER TABLE bench_pieces ALTER COLUMN place_size DROP NOT NULL")


def downgrade() -> None:
    op.execute("UPDATE bench_pieces SET place_size = 'medium' WHERE place_size IS NULL")
    op.execute("ALTER TABLE bench_pieces ALTER COLUMN place_size SET NOT NULL")
