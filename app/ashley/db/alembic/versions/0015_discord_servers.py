"""A household's Discord device is a server, not one channel: she answers in any channel of it, and the channel she
had becomes her home channel there. A server is held by one unrevoked device at a time. A device named a channel but
no server cannot be completed from what is stored, so its channel is cleared and it is registered again with the CLI."""

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"


def upgrade() -> None:
    op.execute(
        r"""
        DROP INDEX devices_discord_channel;

        UPDATE devices SET discord_channel_id = NULL WHERE discord_channel_id IS NOT NULL;

        ALTER TABLE devices RENAME COLUMN discord_channel_id TO discord_home_channel_id;

        ALTER TABLE devices
            ADD COLUMN discord_guild_id bigint CHECK (discord_guild_id > 0),
            ADD CONSTRAINT devices_discord_server_is_whole
                CHECK ((discord_guild_id IS NULL) = (discord_home_channel_id IS NULL));

        CREATE UNIQUE INDEX devices_discord_guild ON devices (discord_guild_id) WHERE revoked_at IS NULL;
        """
    )
