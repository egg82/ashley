"""A camera's detector events, each recorded once (the key is the camera and the time its detector saw it), so the
event a pod on each site both heard acts once, and `shown` marks the ones that put a feed on the screens, which is
what a per-camera minimum gap counts from."""

from alembic import op

revision: str = "0133"
down_revision: str | None = "0132"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE camera_detections (
            household_id bigint NOT NULL REFERENCES households (id) ON DELETE CASCADE,
            camera_id text NOT NULL,
            at timestamptz NOT NULL,
            kind text NOT NULL,
            shown boolean NOT NULL DEFAULT false,
            PRIMARY KEY (household_id, camera_id, at)
        );

        CREATE INDEX camera_detections_at ON camera_detections (at);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE camera_detections")
