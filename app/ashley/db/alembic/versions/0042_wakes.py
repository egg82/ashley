"""Wakes Home Assistant hands in (`/api/wakes`): one row per household and event id, however often it arrives, due
until the `wakes` singleton settles it with what came of it. A device may be the household's Home Assistant (`house`),
the only one that hands wakes in; a satellite or a Discord server never is."""

from alembic import op

revision: str = "0042"
down_revision: str | None = "0041"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE wakes (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            household_id bigint NOT NULL REFERENCES households (id),
            device_id bigint NOT NULL REFERENCES devices (id),
            event_id text NOT NULL CHECK (length(event_id) BETWEEN 1 AND 128),
            event text NOT NULL CHECK (event ~ '^[a-z][a-z0-9_]{0,63}$'),
            who text CHECK (who ~ '^person\\.[a-z0-9_]+$'),
            what text CHECK (what ~ '^[a-z][a-z0-9_]{0,63}$'),
            at timestamptz NOT NULL,
            received_at timestamptz NOT NULL DEFAULT now(),
            settled_at timestamptz,
            outcome text CHECK (outcome IN ('turn', 'failed', 'no_rule', 'ambiguous', 'no_person', 'expired')),
            CHECK ((settled_at IS NULL) = (outcome IS NULL)),
            UNIQUE (household_id, event_id)
        );

        CREATE INDEX wakes_due ON wakes (received_at, id) WHERE settled_at IS NULL;
        CREATE INDEX wakes_settled ON wakes (settled_at) WHERE settled_at IS NOT NULL;

        ALTER TABLE devices ADD COLUMN house boolean NOT NULL DEFAULT false;
        ALTER TABLE devices ADD CONSTRAINT devices_house_alone
            CHECK (NOT house OR (esphome_host IS NULL AND discord_guild_id IS NULL));
        """
    )
