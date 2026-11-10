"""Her turn no longer records what acting on memory did; Memory is shown in the Memory room."""

from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"


def upgrade() -> None:
    op.execute("ALTER TABLE turns DROP COLUMN kept;")
