"""Her turn can record that it went out while her answer was still to come (a held "let me check")."""

from alembic import op

revision: str = "0034"
down_revision: str | None = "0033"


def upgrade() -> None:
    op.execute("ALTER TABLE turns ADD COLUMN follows boolean NOT NULL DEFAULT false;")
