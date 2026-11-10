"""A queued reply can carry the id of the held proposal its text shows (`outbox.agree`), so a push notification for it
offers an Agree button."""

from alembic import op

revision: str = "0090"
down_revision: str | None = "0089"


def upgrade() -> None:
    op.execute("ALTER TABLE outbox ADD COLUMN agree bigint CHECK (agree IS NULL OR agree > 0)")


def downgrade() -> None:
    op.execute("ALTER TABLE outbox DROP COLUMN agree")
