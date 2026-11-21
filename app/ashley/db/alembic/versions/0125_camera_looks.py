"""A look through a camera is on no bench: `bench_looks.bench_id` may be null, as `piece_id` already may."""

from alembic import op

revision: str = "0125"
down_revision: str | None = "0123"


def upgrade() -> None:
    op.execute("ALTER TABLE bench_looks ALTER COLUMN bench_id DROP NOT NULL")
