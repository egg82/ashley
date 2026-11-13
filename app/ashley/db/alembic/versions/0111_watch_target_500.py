"""A watch's target holds up to 500 characters, so a `tool` watch can carry a tool's fixed arguments and the fields it
tracks (`ashley.watches.tool_target`)."""

from alembic import op

revision: str = "0111"
down_revision: str | None = "0110"


def upgrade() -> None:
    op.execute("ALTER TABLE watches DROP CONSTRAINT watches_target_check")
    op.execute("ALTER TABLE watches ADD CONSTRAINT watches_target_check CHECK (length(target) BETWEEN 1 AND 500)")


def downgrade() -> None:
    op.execute("ALTER TABLE watches DROP CONSTRAINT watches_target_check")
    op.execute("ALTER TABLE watches ADD CONSTRAINT watches_target_check CHECK (length(target) BETWEEN 1 AND 200)")
