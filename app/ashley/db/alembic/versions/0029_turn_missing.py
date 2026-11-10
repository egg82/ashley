"""Her turn can record that a correction or a forget matched no fact she held."""

from alembic import op

revision: str = "0029"
down_revision: str | None = "0028"


def upgrade() -> None:
    op.execute("ALTER TABLE turns DROP CONSTRAINT turns_kept_check;")
    op.execute(
        "ALTER TABLE turns ADD CONSTRAINT turns_kept_check "
        "CHECK (kept IN ('keeping', 'kept', 'changed', 'known', 'missing', 'failed'));")
