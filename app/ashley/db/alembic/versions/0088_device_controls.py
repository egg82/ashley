"""The touch controls a device shows (`device_controls`, one row per button, gone with the device). A household
starts with none."""

from alembic import op

revision: str = "0088"
down_revision: str | None = "0087"


def upgrade() -> None:
    op.execute("""
        CREATE TABLE device_controls (
            device_id bigint NOT NULL,
            household_id bigint NOT NULL,
            name text NOT NULL CHECK (name ~ '^[a-z0-9-]{1,40}$'),
            position integer NOT NULL CHECK (position >= 0),
            label text NOT NULL CHECK (char_length(label) BETWEEN 1 AND 40 AND label = btrim(label)),
            action text NOT NULL CHECK (action ~ '^[a-z_]+\\.[a-z_]+$'),
            entity_id text NOT NULL CHECK (entity_id ~ '^[a-z_]+\\.[a-z0-9_]+$'),
            PRIMARY KEY (device_id, name),
            UNIQUE (device_id, position),
            FOREIGN KEY (device_id, household_id) REFERENCES devices (id, household_id) ON DELETE CASCADE
        )""")


def downgrade() -> None:
    op.execute("DROP TABLE device_controls")
