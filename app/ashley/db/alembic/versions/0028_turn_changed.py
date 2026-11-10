"""Her turn can record that acting on memory changed or ended facts, not only kept new ones."""

from alembic import op

revision: str = "0028"
down_revision: str | None = "0027"


def upgrade() -> None:
    op.execute("ALTER TABLE turns DROP CONSTRAINT turns_kept_check;")
    op.execute(
        "ALTER TABLE turns ADD CONSTRAINT turns_kept_check "
        "CHECK (kept IN ('keeping', 'kept', 'changed', 'known', 'failed'));")
