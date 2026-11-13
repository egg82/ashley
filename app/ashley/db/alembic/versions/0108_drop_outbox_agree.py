"""The proposal a queued reply offers is read from `outbox.receipts`; the `agree` column is gone."""

from alembic import op

revision: str = "0108"
down_revision: str | None = "0107"


def upgrade() -> None:
    op.execute("ALTER TABLE outbox DROP COLUMN agree")


def downgrade() -> None:
    op.execute("ALTER TABLE outbox ADD COLUMN agree bigint CHECK (agree IS NULL OR agree > 0)")
