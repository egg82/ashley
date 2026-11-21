"""The wake events an install wrote to the house: the `event` of each wake action in the config it wrote
(`ashley.workshop.wake_action`), so the bench can say which installed automation sends a wake rule's event even after
the piece is edited. Empty for an uninstall, an automation with no wake action and every install before this."""

from alembic import op

revision: str = "0128"
down_revision: str | None = "0124"


def upgrade() -> None:
    op.execute("ALTER TABLE bench_installs ADD COLUMN wake_events text[] NOT NULL DEFAULT '{}'")


def downgrade() -> None:
    op.execute("ALTER TABLE bench_installs DROP COLUMN wake_events")
