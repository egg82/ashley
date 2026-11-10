"""Her turn records that she asked to keep a memory as she answered, and how keeping it ended."""

from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE turns ADD COLUMN kept text CHECK (kept IN ('keeping', 'kept', 'known', 'failed'));")
