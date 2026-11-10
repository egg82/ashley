"""A household's locale, unit system and clock, set by its people on the household page. The defaults are what the
shipped code assumed before a household could choose: `en-US` dates and numbers, imperial units, a 24-hour clock."""

from alembic import op

revision: str = "0099"
down_revision: str | None = "0098"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE households
            ADD COLUMN locale text NOT NULL DEFAULT 'en-US',
            ADD COLUMN unit_system text NOT NULL DEFAULT 'imperial' CHECK (unit_system IN ('imperial', 'metric')),
            ADD COLUMN clock text NOT NULL DEFAULT '24h' CHECK (clock IN ('12h', '24h'))""")


def downgrade() -> None:
    op.execute("ALTER TABLE households DROP COLUMN locale, DROP COLUMN unit_system, DROP COLUMN clock")
