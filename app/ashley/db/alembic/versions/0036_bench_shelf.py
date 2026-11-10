"""A bench's shelf: a piece archived off its bench's layout keeps its row, marked `shelved`, at the place it left. It
does not count among the bench's pieces; closed benches are listed by when they closed."""

from alembic import op

revision: str = "0036"
down_revision: str | None = "0035"


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE bench_pieces ADD COLUMN shelved boolean NOT NULL DEFAULT false;

        CREATE INDEX benches_closed_by_owner ON benches (owner_id, closed_at DESC, id DESC) WHERE closed_at IS NOT NULL;
        """
    )
