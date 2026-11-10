"""Voice satellites: what a connection to a device needs (its ESPHome host, and the room speaker that plays her reply
instead of its own), and the short-lived clips a satellite or room speaker fetches her spoken reply from."""

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"


def upgrade() -> None:
    op.execute(
        r"""
        ALTER TABLE devices
            ADD COLUMN esphome_host text CHECK (esphome_host ~ '^\S+$'),
            ADD COLUMN room_speaker text CHECK (room_speaker ~ '^media_player\.[a-z0-9_]+$'),
            ADD CONSTRAINT devices_room_speaker_needs_a_satellite
                CHECK (room_speaker IS NULL OR esphome_host IS NOT NULL),
            ADD UNIQUE (id, household_id);

        CREATE TABLE voice_clips (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            token_sha256 bytea NOT NULL UNIQUE CHECK (length(token_sha256) = 32),
            household_id bigint NOT NULL,
            device_id bigint NOT NULL,
            body text NOT NULL CHECK (body ~ '\S'),
            woke_at timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            FOREIGN KEY (device_id, household_id) REFERENCES devices (id, household_id)
        );

        CREATE INDEX voice_clips_by_age ON voice_clips (created_at);
        """
    )
