"""What code shows beside her answer after a tainted turn is kept with her turn (`turns.receipts`, only hers) and with a
reply queued in the outbox (`outbox.receipts`); a change that ran without asking keeps the headline it was shown under
(`outside_actions.label`). `outbox.agree` is still written for one release."""

from alembic import op

revision: str = "0093"
down_revision: str | None = "0092"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE turns ADD COLUMN receipts jsonb,
            ADD CONSTRAINT turns_receipts_hers CHECK (receipts IS NULL OR author = 'ashley');
        ALTER TABLE outbox ADD COLUMN receipts jsonb;
        ALTER TABLE outside_actions ADD COLUMN label text NOT NULL DEFAULT ''""")


def downgrade() -> None:
    op.execute("""
        ALTER TABLE outside_actions DROP COLUMN label;
        ALTER TABLE outbox DROP COLUMN receipts;
        ALTER TABLE turns DROP CONSTRAINT turns_receipts_hers, DROP COLUMN receipts""")
