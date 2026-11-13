"""A standing errand is a repeating reminder that names her method (`ashley.senses.wakes.Reminder.method`): the
household's skill kind, a slug of the shape `app/ashley/skills/skills.json` gives. Only a repeating `time` reminder
with no end carries one, and each next occurrence carries it on."""

from alembic import op

revision: str = "0120"
down_revision: str | None = "0119"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE wakes
            ADD COLUMN method text CHECK (method ~ '^[a-z0-9][a-z0-9-]*$' AND length(method) <= 40),
            ADD CONSTRAINT wakes_standing_errand CHECK (method IS NULL
                OR (kind = 'reminder' AND trigger = 'time' AND repeat IS NOT NULL AND ends_at IS NULL))""")


def downgrade() -> None:
    op.execute("ALTER TABLE wakes DROP COLUMN method")
