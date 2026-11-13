"""What a device can do, set when it is registered (`devices.capabilities`, a closed set; today only `controls`, the
touch controls a screen shows). Existing rows get what the old rule gave them: a text device that is not a satellite,
a Discord server or the house."""

from alembic import op

revision: str = "0107"
down_revision: str | None = "0106"


def upgrade() -> None:
    op.execute("""
        ALTER TABLE devices ADD COLUMN capabilities text[] NOT NULL DEFAULT '{}';
        UPDATE devices SET capabilities = ARRAY['controls']
            WHERE medium = 'text' AND esphome_host IS NULL AND discord_guild_id IS NULL AND NOT house;
        ALTER TABLE devices ADD CONSTRAINT devices_capabilities_known CHECK (capabilities <@ ARRAY['controls']);
        ALTER TABLE devices ADD CONSTRAINT devices_controls_need_a_text_screen
            CHECK (NOT capabilities @> ARRAY['controls']
                   OR (medium = 'text' AND esphome_host IS NULL AND discord_guild_id IS NULL AND NOT house));
        """)


def downgrade() -> None:
    op.execute("ALTER TABLE devices DROP COLUMN capabilities")
