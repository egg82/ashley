"""An open screen may be showing a camera's live feed (`live_screens.feed_camera`, the camera's id) until `feed_until`,
so any pod of either site can say what a screen shows and clear it. The row goes with the screen when it closes."""

from alembic import op

revision: str = "0131"
down_revision: str | None = "0130"


def upgrade() -> None:
    op.execute("ALTER TABLE live_screens ADD COLUMN feed_camera text, ADD COLUMN feed_until timestamptz")


def downgrade() -> None:
    op.execute("ALTER TABLE live_screens DROP COLUMN feed_camera, DROP COLUMN feed_until")
