"""Discord: a device can be a shared Discord text channel (its channel id, held by one unrevoked device at a time, so a
revoked device frees it), and the claims that let exactly one process answer each Discord message, kept briefly."""

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE devices
            ADD COLUMN discord_channel_id bigint CHECK (discord_channel_id > 0);

        CREATE UNIQUE INDEX devices_discord_channel ON devices (discord_channel_id) WHERE revoked_at IS NULL;

        CREATE TABLE discord_seen (
            message_id bigint PRIMARY KEY,
            channel_id bigint NOT NULL,
            claimed_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE INDEX discord_seen_by_age ON discord_seen (claimed_at);
        """
    )
