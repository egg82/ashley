"""A clip announced on a screen carries the line the screen shows beside her voice (`voice_clips.line`); a clip for a
satellite or room speaker has none, since its body is respelled for the voice and nothing reads it."""

from alembic import op

revision: str = "0118"
down_revision: str | None = "0117"


def upgrade() -> None:
    op.execute(r"ALTER TABLE voice_clips ADD COLUMN line text CHECK (line ~ '\S')")


def downgrade() -> None:
    op.execute("ALTER TABLE voice_clips DROP COLUMN line")
