"""An errand she carries out over time is a reminder that sets its own next check (`ashley.senses.wakes.Reminder`):
`ends_at` is the latest a check may fall, `plan` what she noted for this check at the one before, and `follows` the
occurrence whose turn set it, one next check per occurrence (`ashley.senses.wakes.Wakes.follow_up`)."""

from alembic import op

revision: str = "0114"
down_revision: str | None = "0113"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE wakes
            ADD COLUMN ends_at timestamptz,
            ADD COLUMN plan text CHECK (length(plan) BETWEEN 1 AND 500),
            ADD COLUMN follows bigint REFERENCES wakes (id) ON DELETE SET NULL,
            ADD CONSTRAINT wakes_errand_fields CHECK ((ends_at IS NULL AND plan IS NULL AND follows IS NULL)
                OR (ends_at IS NOT NULL AND kind = 'reminder' AND trigger = 'time' AND repeat IS NULL))""")
    op.execute("CREATE UNIQUE INDEX wakes_follows ON wakes (follows) WHERE follows IS NOT NULL")


def downgrade() -> None:
    op.execute("DELETE FROM wakes WHERE ends_at IS NOT NULL")
    op.execute("ALTER TABLE wakes DROP COLUMN follows, DROP COLUMN plan, DROP COLUMN ends_at")
