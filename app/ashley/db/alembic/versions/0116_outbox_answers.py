"""A reply queued in the outbox names the person turn it answers (`outbox.answers`), so one that waits past `stale_s` is
held for the asker's next reply as an errand (`ashley.channels.postgres_outbox`)."""

from alembic import op

revision: str = "0116"
down_revision: str | None = "0115"


def upgrade() -> None:
    op.execute("ALTER TABLE outbox ADD COLUMN answers bigint REFERENCES turns (id) ON DELETE CASCADE")


def downgrade() -> None:
    op.execute("ALTER TABLE outbox DROP COLUMN answers")
